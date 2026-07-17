"""build_event_cumulative の LLM 二次重複統合ロジック。"""
from __future__ import annotations

import json
import hashlib
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from github_models_client import (
    DEFAULT_API_VERSION,
    call_chat_completion,
    get_github_models_token,
    load_dotenv,
)
from atomic_io import atomic_write_text
from event_cumulative_core import (
    build_similarity_clusters,
    compact_text,
    merge_event_group,
    renumber_records,
    secondary_group_key,
    suppress_preview_like_records,
)


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = ROOT_DIR / ".env"
DEFAULT_MODEL = "openai/gpt-5"
DEFAULT_DEDUPE_CACHE_PATH = ROOT_DIR / "data" / "output" / "_state" / "event_dedupe_cache.json"
CACHE_VERSION = 1

SECONDARY_DEDUPE_SYSTEM_PROMPT = """あなたは日本語の公演イベント重複統合アシスタントです。
入力される複数レコードは、同日かつ同一会場または同一団体で候補絞り込み済みです。
同じ公演の表記揺れだけを統合してください。別公演は絶対に統合しないでください。

同一とみなしてよい例:
- 副題の有無
- 記号や装飾の有無
- LIVE TOUR 2026 と LIVE TOUR 2026 DANCE ON AIR のように、同じ公演名の主題と副題の差
- 「in小松」の有無など軽微な表記差
- 開催期間全体の投稿と、その期間内の単日投稿や千秋楽投稿の差

同一とみなしてはいけない例:
- 開催期間が重ならない別日程
- 会場違い
- 同一シリーズでも別公演回
- 募集と本公演

出力はJSONオブジェクトのみで返してください。
形式:
{
    "decisions": [
        {"member_ids": ["1", "2"], "canonical_name": "統合後名称"},
        {"member_ids": ["3"], "canonical_name": "そのままの名称"}
    ]
}

必ずすべての id を一度だけ decisions に含めてください。"""


def call_dedupe_model(token: str, api_version: str, model: str, prompt: str) -> dict[str, Any]:
    return call_chat_completion(
        token=token,
        api_version=api_version,
        model=model,
        messages=[
            {"role": "system", "content": SECONDARY_DEDUPE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
        retry_label="dedupe",
    )


def extract_json_content(response_payload: dict[str, Any]) -> dict[str, Any]:
    content = response_payload["choices"][0]["message"]["content"]
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
        content = "".join(text_parts)

    if not isinstance(content, str):
        raise RuntimeError("GitHub Models の応答形式が想定外です。")

    return json.loads(content)


def build_dedupe_prompt(records: list[dict[str, Any]]) -> str:
    payload = {
        "records": [
            {
                "id": str(index),
                "event_name": record.get("event_name") or "",
                "normalized_event_name": record.get("normalized_event_name") or "",
                "organization": record.get("organization") or "",
                "normalized_venue_name": record.get("normalized_venue_name") or record.get("venue_name") or "",
                "start_date": record.get("start_date") or "",
                "end_date": record.get("end_date") or "",
                "start_time": record.get("start_time") or "",
                "category": record.get("category") or "",
                "source_text": record.get("source_text") or "",
            }
            for index, record in enumerate(records, start=1)
        ]
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def load_dedupe_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": CACHE_VERSION, "entries": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        print(f"dedupe cache ignored: {path}", file=sys.stderr)
        return {"version": CACHE_VERSION, "entries": {}}
    if not isinstance(payload, dict) or payload.get("version") != CACHE_VERSION:
        return {"version": CACHE_VERSION, "entries": {}}
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        return {"version": CACHE_VERSION, "entries": {}}
    return {"version": CACHE_VERSION, "entries": entries}


def write_dedupe_cache(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def build_dedupe_cache_key(records: list[dict[str, Any]], model: str, api_version: str) -> str:
    cache_payload = {
        "version": CACHE_VERSION,
        "model": model,
        "api_version": api_version,
        "system_prompt": SECONDARY_DEDUPE_SYSTEM_PROMPT,
        "prompt": json.loads(build_dedupe_prompt(records)),
    }
    serialized = json.dumps(cache_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def validate_dedupe_decisions(payload: Any, valid_ids: set[str]) -> list[dict[str, Any]] | None:
    decisions = payload.get("decisions") if isinstance(payload, dict) else None
    if not isinstance(decisions, list):
        return None
    consumed: list[str] = []
    normalized: list[dict[str, Any]] = []
    for decision in decisions:
        if not isinstance(decision, dict) or not isinstance(decision.get("member_ids"), list):
            return None
        member_ids = [str(value) for value in decision["member_ids"]]
        if not member_ids or any(value not in valid_ids for value in member_ids):
            return None
        if any(value in consumed for value in member_ids):
            return None
        canonical_name = decision.get("canonical_name")
        if not isinstance(canonical_name, str):
            return None
        consumed.extend(member_ids)
        normalized.append({"member_ids": member_ids, "canonical_name": canonical_name})
    if set(consumed) != valid_ids or len(consumed) != len(valid_ids):
        return None
    return normalized


def secondary_dedupe(
    records: list[dict[str, Any]],
    model: str,
    cache_path: Path | None = DEFAULT_DEDUPE_CACHE_PATH,
) -> list[dict[str, Any]]:
    load_dotenv(DEFAULT_ENV_FILE)
    api_version = os.getenv("GITHUB_MODELS_API_VERSION", DEFAULT_API_VERSION).strip() or DEFAULT_API_VERSION
    cache = load_dedupe_cache(cache_path) if cache_path else {"version": CACHE_VERSION, "entries": {}}
    cache_changed = False
    github_token = get_github_models_token()

    grouped_records: dict[str, list[dict[str, Any]]] = {}
    passthrough_records: list[dict[str, Any]] = []
    for record in records:
        group_key = secondary_group_key(record)
        if not group_key:
            passthrough_records.append(record)
            continue
        grouped_records.setdefault(group_key, []).append(record)

    merged_records: list[dict[str, Any]] = list(passthrough_records)
    for group_key, group in grouped_records.items():
        for cluster_index, cluster in enumerate(build_similarity_clusters(group), start=1):
            unique_names = {
                compact_text(record.get("normalized_event_name") or record.get("event_name") or "")
                for record in cluster
                if (record.get("normalized_event_name") or record.get("event_name") or "")
            }
            if len(cluster) < 2 or len(unique_names) < 2:
                merged_records.extend(cluster)
                continue

            id_to_record = {str(index): record for index, record in enumerate(cluster, start=1)}
            valid_ids = set(id_to_record)
            cache_key = build_dedupe_cache_key(cluster, model, api_version)
            cached_entry = cache["entries"].get(cache_key)
            decisions = None
            if isinstance(cached_entry, dict):
                decisions = validate_dedupe_decisions(cached_entry.get("decision"), valid_ids)

            if decisions is None:
                if not github_token:
                    print("secondary dedupe skipped: GH_MODELS_TOKEN または GITHUB_TOKEN が見つかりません")
                    merged_records.extend(cluster)
                    continue
                prompt = build_dedupe_prompt(cluster)
                try:
                    response_payload = call_dedupe_model(github_token, api_version, model, prompt)
                    decision_payload = extract_json_content(response_payload)
                    decisions = validate_dedupe_decisions(decision_payload, valid_ids)
                    if decisions is None:
                        raise RuntimeError("LLMの重複統合decisionが全IDを網羅していません")
                except Exception as exc:
                    print(f"secondary dedupe skipped for group {group_key} cluster {cluster_index}: {exc}", file=sys.stderr)
                    merged_records.extend(cluster)
                    continue

                if cache_path:
                    cache["entries"][cache_key] = {
                        "model": model,
                        "api_version": api_version,
                        "decision": {"decisions": decisions},
                        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    }
                    cache_changed = True

            consumed_ids: set[str] = set()
            if decisions is None:
                merged_records.extend(cluster)
                continue

            for decision in decisions:
                if not isinstance(decision, dict):
                    continue
                member_ids = [str(member_id) for member_id in decision.get("member_ids", []) if str(member_id) in id_to_record]
                member_ids = [member_id for member_id in member_ids if member_id not in consumed_ids]
                if not member_ids:
                    continue
                consumed_ids.update(member_ids)
                member_records = [id_to_record[member_id] for member_id in member_ids]
                merged_records.append(merge_event_group(member_records, str(decision.get("canonical_name") or "")))

            for member_id, record in id_to_record.items():
                if member_id not in consumed_ids:
                    merged_records.append(record)

    if cache_path and cache_changed:
        write_dedupe_cache(cache_path, cache)
    return renumber_records(suppress_preview_like_records(merged_records))
