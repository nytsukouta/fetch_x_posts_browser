from __future__ import annotations

import argparse
import csv
import difflib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib import error, request


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = ROOT_DIR / ".env"
DEFAULT_INPUT_CSV = ROOT_DIR / "data" / "output" / "structured_events_filtered_cumulative.csv"
DEFAULT_OUTPUT_CSV = ROOT_DIR / "data" / "output" / "event_cumulative.csv"
DEFAULT_MODEL = "openai/gpt-4.1-mini"
DEFAULT_API_VERSION = "2026-03-10"
INFERENCE_URL = "https://models.github.ai/inference/chat/completions"
NON_ALNUM_RE = re.compile(r"[^0-9a-zA-Z\u3040-\u30ff\u3400-\u9fff]+")
TITLE_SIMILARITY_THRESHOLD = 0.6

MERGE_FIELDS = [
    "event_name",
    "normalized_event_name",
    "organization",
    "venue_name",
    "location",
    "normalized_venue_name",
    "normalized_location",
    "start_date",
    "end_date",
    "start_time",
    "category",
    "reasoning",
    "source_text",
    "author_name",
    "author_username",
]

SECONDARY_DEDUPE_SYSTEM_PROMPT = """あなたは日本語の公演イベント重複統合アシスタントです。
入力される複数レコードは、同日かつ同一会場または同一団体で候補絞り込み済みです。
同じ公演の表記揺れだけを統合してください。別公演は絶対に統合しないでください。

同一とみなしてよい例:
- 副題の有無
- 記号や装飾の有無
- LIVE TOUR 2026 と LIVE TOUR 2026 DANCE ON AIR のように、同じ公演名の主題と副題の差
- 「in小松」の有無など軽微な表記差

同一とみなしてはいけない例:
- 日付違い
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build event-level cumulative records from filtered cumulative tweet records")
    parser.add_argument("--input-csv", default=str(DEFAULT_INPUT_CSV), help="filtered cumulative CSV のパス")
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV), help="イベント累積CSVの保存先")
    parser.add_argument("--model", default=os.getenv("GITHUB_MODELS_MODEL", DEFAULT_MODEL), help="二次統合で使う GitHub Models のモデルID")
    return parser.parse_args()


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_dotenv(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def compact_text(value: str) -> str:
    cleaned = NON_ALNUM_RE.sub("", value.strip().lower())
    return cleaned


def build_event_key(row: dict[str, str]) -> str:
    event_name = compact_text(row.get("normalized_event_name") or row.get("event_name") or "")
    organization = compact_text(row.get("organization") or "")
    venue_name = compact_text(row.get("normalized_venue_name") or row.get("venue_name") or "")
    location = compact_text(row.get("normalized_location") or row.get("location") or "")
    start_date = (row.get("start_date") or "").strip()
    end_date = (row.get("end_date") or "").strip()
    start_time = (row.get("start_time") or "").strip()
    category = (row.get("category") or "").strip()

    if event_name:
        primary = [event_name, organization, venue_name, start_date, end_date, start_time]
    else:
        primary = [organization, venue_name, location, start_date, end_date, start_time, category]
    return "|".join(primary)


def call_github_models(token: str, api_version: str, model: str, prompt: str) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SECONDARY_DEDUPE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }

    last_error: Exception | None = None
    for attempt in range(5):
        api_request = request.Request(
            INFERENCE_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": api_version,
            },
            method="POST",
        )

        try:
            with request.urlopen(api_request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 4:
                raise RuntimeError(f"GitHub Models API error {exc.code}: {details}") from exc
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            wait_seconds = float(retry_after) if retry_after else min(30, 2 * (attempt + 1))
            print(f"retrying dedupe after API error {exc.code}: wait {wait_seconds:.0f}s", file=sys.stderr)
            time.sleep(wait_seconds)
            last_error = exc
        except error.URLError as exc:
            if attempt == 4:
                raise RuntimeError(f"GitHub Models API へ接続できません: {exc}") from exc
            wait_seconds = min(30, 2 * (attempt + 1))
            print(f"retrying dedupe after connection error: wait {wait_seconds:.0f}s", file=sys.stderr)
            time.sleep(wait_seconds)
            last_error = exc
        except TimeoutError as exc:
            if attempt == 4:
                raise RuntimeError(f"GitHub Models API の応答待ちがタイムアウトしました: {exc}") from exc
            wait_seconds = min(30, 2 * (attempt + 1))
            print(f"retrying dedupe after read timeout: wait {wait_seconds:.0f}s", file=sys.stderr)
            time.sleep(wait_seconds)
            last_error = exc

    raise RuntimeError(f"GitHub Models API の呼び出しに失敗しました: {last_error}")


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


def slugify(value: str, fallback_prefix: str, fallback_number: int) -> str:
    cleaned = NON_ALNUM_RE.sub("-", value.strip().lower()).strip("-")
    if cleaned:
        return cleaned
    return f"{fallback_prefix}-{fallback_number:04d}"


def row_quality(row: dict[str, str]) -> tuple[float, int, int, str]:
    confidence = float(row.get("confidence") or 0)
    signal_count = sum(1 for field in MERGE_FIELDS if (row.get(field) or "").strip())
    text_length = len((row.get("source_text") or "").strip())
    created_at = (row.get("created_at") or "").strip()
    return confidence, signal_count, text_length, created_at


def choose_value(current: str, candidate: str) -> str:
    current_value = (current or "").strip()
    candidate_value = (candidate or "").strip()
    if not current_value:
        return candidate_value
    if not candidate_value:
        return current_value
    if len(candidate_value) > len(current_value):
        return candidate_value
    return current_value


def title_similarity(left: str, right: str) -> float:
    normalized_left = compact_text(left)
    normalized_right = compact_text(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left == normalized_right:
        return 1.0
    return difflib.SequenceMatcher(None, normalized_left, normalized_right).ratio()


def titles_are_similar(left: str, right: str) -> bool:
    normalized_left = compact_text(left)
    normalized_right = compact_text(right)
    if not normalized_left or not normalized_right:
        return False
    if normalized_left == normalized_right:
        return True
    if normalized_left in normalized_right or normalized_right in normalized_left:
        shorter = min(len(normalized_left), len(normalized_right))
        longer = max(len(normalized_left), len(normalized_right))
        if shorter >= max(6, int(longer * 0.5)):
            return True
    return title_similarity(left, right) >= TITLE_SIMILARITY_THRESHOLD


def build_similarity_clusters(records: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    clusters: list[list[dict[str, Any]]] = []
    remaining_records = list(records)

    while remaining_records:
        seed = remaining_records.pop(0)
        cluster = [seed]
        changed = True

        while changed:
            changed = False
            next_remaining: list[dict[str, Any]] = []
            for candidate in remaining_records:
                candidate_title = str(candidate.get("normalized_event_name") or candidate.get("event_name") or "")
                if any(
                    titles_are_similar(
                        candidate_title,
                        str(member.get("normalized_event_name") or member.get("event_name") or ""),
                    )
                    for member in cluster
                ):
                    cluster.append(candidate)
                    changed = True
                else:
                    next_remaining.append(candidate)
            remaining_records = next_remaining

        clusters.append(cluster)

    return clusters


def secondary_group_key(record: dict[str, Any]) -> str:
    start_date = (record.get("start_date") or "").strip()
    end_date = (record.get("end_date") or "").strip()
    category = (record.get("category") or "").strip()
    venue_name = compact_text(record.get("normalized_venue_name") or record.get("venue_name") or "")
    organization = compact_text(record.get("organization") or "")

    if not start_date:
        return ""
    if venue_name:
        anchor = f"venue:{venue_name}"
    elif organization:
        anchor = f"org:{organization}"
    else:
        return ""
    return "|".join([start_date, end_date, category, anchor])


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


def choose_canonical_name(records: list[dict[str, Any]], suggested_name: str) -> str:
    canonical = (suggested_name or "").strip()
    if canonical:
        return canonical
    candidates = [
        (record.get("normalized_event_name") or record.get("event_name") or "").strip()
        for record in records
    ]
    candidates = [candidate for candidate in candidates if candidate]
    if not candidates:
        return ""
    return max(candidates, key=len)


def merge_event_group(records: list[dict[str, Any]], canonical_name: str) -> dict[str, Any]:
    best_record = max(records, key=row_quality)
    merged = dict(best_record)
    source_tweet_urls: set[str] = set()
    source_author_usernames: set[str] = set()
    first_seen = ""
    last_seen = ""
    max_confidence = 0.0

    for record in records:
        for field in MERGE_FIELDS:
            merged[field] = choose_value(str(merged.get(field) or ""), str(record.get(field) or ""))

        for tweet_url in str(record.get("source_tweet_urls") or record.get("tweet_url") or "").split(" | "):
            cleaned = tweet_url.strip()
            if cleaned:
                source_tweet_urls.add(cleaned)

        for username in str(record.get("source_author_usernames") or record.get("author_username") or "").split(" | "):
            cleaned = username.strip()
            if cleaned:
                source_author_usernames.add(cleaned)

        created_at = str(record.get("created_at") or "").strip()
        first_seen_candidate = str(record.get("first_seen_created_at") or created_at).strip()
        last_seen_candidate = str(record.get("last_seen_created_at") or created_at).strip()
        if first_seen_candidate and (not first_seen or first_seen_candidate < first_seen):
            first_seen = first_seen_candidate
        if last_seen_candidate and (not last_seen or last_seen_candidate > last_seen):
            last_seen = last_seen_candidate

        confidence = float(record.get("confidence") or 0)
        if confidence > max_confidence:
            max_confidence = confidence

    merged["normalized_event_name"] = choose_canonical_name(records, canonical_name)
    merged["tweet_url"] = sorted(source_tweet_urls)[0] if source_tweet_urls else str(merged.get("tweet_url") or "")
    merged["created_at"] = last_seen or str(merged.get("created_at") or "")
    merged["confidence"] = max_confidence
    merged["source_tweet_count"] = len(source_tweet_urls)
    merged["source_tweet_urls"] = " | ".join(sorted(source_tweet_urls))
    merged["source_author_usernames"] = " | ".join(sorted(source_author_usernames))
    merged["first_seen_created_at"] = first_seen
    merged["last_seen_created_at"] = last_seen
    return merged


def renumber_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sorted_records = sorted(
        records,
        key=lambda item: ((item.get("last_seen_created_at") or item.get("created_at") or ""), build_event_key(item)),
        reverse=True,
    )

    normalized_records: list[dict[str, Any]] = []
    for index, record in enumerate(sorted_records, start=1):
        normalized_record = dict(record)
        normalized_record["event_key"] = build_event_key(normalized_record)
        id_seed = (
            (normalized_record.get("normalized_event_name") or "").strip()
            or (normalized_record.get("event_name") or "").strip()
            or (normalized_record.get("organization") or "").strip()
            or (normalized_record.get("normalized_venue_name") or normalized_record.get("venue_name") or "").strip()
            or normalized_record["event_key"]
        )
        normalized_record["event_id"] = f"event-{slugify(id_seed, 'event', index)}"
        normalized_records.append(normalized_record)
    return normalized_records


def secondary_dedupe(records: list[dict[str, Any]], model: str) -> list[dict[str, Any]]:
    load_dotenv(DEFAULT_ENV_FILE)
    github_token = os.getenv("GITHUB_TOKEN", "").strip()
    api_version = os.getenv("GITHUB_MODELS_API_VERSION", DEFAULT_API_VERSION).strip() or DEFAULT_API_VERSION
    if not github_token:
        print("secondary dedupe skipped: GITHUB_TOKEN が見つかりません")
        return records

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
        unique_names = {
            compact_text(record.get("normalized_event_name") or record.get("event_name") or "")
            for record in group
            if (record.get("normalized_event_name") or record.get("event_name") or "")
        }
        if len(group) < 2 or len(unique_names) < 2:
            merged_records.extend(group)
            continue

        similarity_clusters = build_similarity_clusters(group)
        if len(similarity_clusters) > 1:
            for cluster in similarity_clusters:
                merged_records.extend(secondary_dedupe(cluster, model) if len(cluster) >= 2 else cluster)
            continue

        prompt = build_dedupe_prompt(group)
        try:
            response_payload = call_github_models(github_token, api_version, model, prompt)
            decision_payload = extract_json_content(response_payload)
        except Exception as exc:
            print(f"secondary dedupe skipped for group {group_key}: {exc}", file=sys.stderr)
            merged_records.extend(group)
            continue

        id_to_record = {str(index): record for index, record in enumerate(group, start=1)}
        consumed_ids: set[str] = set()
        decisions = decision_payload.get("decisions") if isinstance(decision_payload, dict) else None
        if not isinstance(decisions, list):
            merged_records.extend(group)
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

    return renumber_records(merged_records)


def build_event_records(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}

    for row in rows:
        if str(row.get("is_noise") or "").lower() == "true":
            continue

        event_key = build_event_key(row)
        if not event_key.replace("|", ""):
            continue

        bucket = buckets.setdefault(
            event_key,
            {
                "event_key": event_key,
                "best_row": row,
                "best_score": row_quality(row),
                "source_tweet_urls": set(),
                "source_author_usernames": set(),
                "first_seen_created_at": (row.get("created_at") or "").strip(),
                "last_seen_created_at": (row.get("created_at") or "").strip(),
                "max_confidence": float(row.get("confidence") or 0),
            },
        )

        tweet_url = (row.get("tweet_url") or "").strip()
        if tweet_url:
            bucket["source_tweet_urls"].add(tweet_url)

        author_username = (row.get("author_username") or "").strip()
        if author_username:
            bucket["source_author_usernames"].add(author_username)

        created_at = (row.get("created_at") or "").strip()
        if created_at:
            if not bucket["first_seen_created_at"] or created_at < bucket["first_seen_created_at"]:
                bucket["first_seen_created_at"] = created_at
            if not bucket["last_seen_created_at"] or created_at > bucket["last_seen_created_at"]:
                bucket["last_seen_created_at"] = created_at

        confidence = float(row.get("confidence") or 0)
        if confidence > bucket["max_confidence"]:
            bucket["max_confidence"] = confidence

        candidate_score = row_quality(row)
        if candidate_score > bucket["best_score"]:
            bucket["best_row"] = row
            bucket["best_score"] = candidate_score

        best_row = bucket["best_row"]
        for field in MERGE_FIELDS:
            best_row[field] = choose_value(best_row.get(field) or "", row.get(field) or "")

    records: list[dict[str, Any]] = []
    for index, bucket in enumerate(
        sorted(buckets.values(), key=lambda item: (item["last_seen_created_at"], item["event_key"]), reverse=True),
        start=1,
    ):
        best_row = dict(bucket["best_row"])
        event_name = (best_row.get("event_name") or "").strip()
        normalized_event_name = (best_row.get("normalized_event_name") or event_name).strip()
        organization = (best_row.get("organization") or "").strip()
        venue_name = (best_row.get("normalized_venue_name") or best_row.get("venue_name") or "").strip()
        id_seed = normalized_event_name or event_name or organization or venue_name or bucket["event_key"]

        records.append(
            {
                "event_id": f"event-{slugify(id_seed, 'event', index)}",
                "event_key": bucket["event_key"],
                "tweet_url": sorted(bucket["source_tweet_urls"])[0] if bucket["source_tweet_urls"] else "",
                "created_at": bucket["last_seen_created_at"],
                "author_name": (best_row.get("author_name") or "").strip(),
                "author_username": (best_row.get("author_username") or "").strip(),
                "event_name": event_name,
                "normalized_event_name": normalized_event_name,
                "organization": organization,
                "venue_name": (best_row.get("venue_name") or "").strip(),
                "location": (best_row.get("location") or "").strip(),
                "normalized_venue_name": (best_row.get("normalized_venue_name") or "").strip(),
                "normalized_location": (best_row.get("normalized_location") or "").strip(),
                "start_date": (best_row.get("start_date") or "").strip(),
                "end_date": (best_row.get("end_date") or "").strip(),
                "start_time": (best_row.get("start_time") or "").strip(),
                "category": (best_row.get("category") or "").strip(),
                "is_recruitment": (best_row.get("is_recruitment") or "").strip(),
                "confidence": bucket["max_confidence"],
                "reasoning": (best_row.get("reasoning") or "").strip(),
                "source_text": (best_row.get("source_text") or "").strip(),
                "source_tweet_count": len(bucket["source_tweet_urls"]),
                "source_tweet_urls": " | ".join(sorted(bucket["source_tweet_urls"])),
                "source_author_usernames": " | ".join(sorted(bucket["source_author_usernames"])),
                "first_seen_created_at": bucket["first_seen_created_at"],
                "last_seen_created_at": bucket["last_seen_created_at"],
            }
        )
    return records


def write_csv(records: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "event_id",
        "event_key",
        "tweet_url",
        "created_at",
        "author_name",
        "author_username",
        "event_name",
        "normalized_event_name",
        "organization",
        "venue_name",
        "location",
        "normalized_venue_name",
        "normalized_location",
        "start_date",
        "end_date",
        "start_time",
        "category",
        "is_recruitment",
        "confidence",
        "reasoning",
        "source_text",
        "source_tweet_count",
        "source_tweet_urls",
        "source_author_usernames",
        "first_seen_created_at",
        "last_seen_created_at",
    ]
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def main() -> int:
    args = parse_args()
    rows = load_rows(Path(args.input_csv))
    records = build_event_records(rows)
    records = secondary_dedupe(records, args.model)
    write_csv(records, Path(args.output_csv))

    print(f"saved event cumulative: {args.output_csv}")
    print(f"rows: {len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())