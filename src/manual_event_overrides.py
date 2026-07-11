"""公演単位の永続的な手動補正を検証・適用する。"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from atomic_io import atomic_write_text


SCHEMA_VERSION = 1
EDITABLE_FIELDS = frozenset(
    {
        "event_name",
        "normalized_event_name",
        "organization",
        "venue_name",
        "normalized_venue_name",
        "location",
        "normalized_location",
        "start_date",
        "end_date",
        "start_time",
        "category",
        "posting_recommendation",
        "is_event_announcement",
        "has_actionable_schedule_info",
        "manual_reference_url",
        "manual_publish_status",
    }
)
BOOLEAN_FIELDS = frozenset({"is_event_announcement", "has_actionable_schedule_info"})
PUBLISH_STATUSES = frozenset({"default", "published", "excluded"})
POSTING_RECOMMENDATIONS = frozenset({"", "post", "review", "skip"})
TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class ManualOverrideError(ValueError):
    """手動補正データが不正な場合のエラー。"""


def empty_override_payload() -> dict[str, Any]:
    return {"version": SCHEMA_VERSION, "overrides": []}


def split_source_tweet_urls(record: dict[str, Any]) -> set[str]:
    urls: set[str] = set()
    tweet_url = str(record.get("tweet_url") or "").strip()
    if tweet_url:
        urls.add(tweet_url)
    for value in str(record.get("source_tweet_urls") or "").split("|"):
        cleaned = value.strip()
        if cleaned:
            urls.add(cleaned)
    return urls


def _validate_date(field: str, value: str) -> None:
    if not value:
        return
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ManualOverrideError(f"{field} は YYYY-MM-DD 形式で入力してください") from exc


def _validate_url(field: str, value: str) -> None:
    if not value:
        return
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ManualOverrideError(f"{field} は http:// または https:// のURLにしてください")


def _validate_override(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ManualOverrideError("override はオブジェクトである必要があります")

    event_id = str(raw.get("target_event_id") or "").strip()
    if not event_id:
        raise ManualOverrideError("target_event_id は必須です")

    raw_urls = raw.get("target_source_tweet_urls", [])
    if not isinstance(raw_urls, list) or any(not isinstance(value, str) for value in raw_urls):
        raise ManualOverrideError("target_source_tweet_urls は文字列配列である必要があります")
    urls = list(dict.fromkeys(value.strip() for value in raw_urls if value.strip()))
    for value in urls:
        _validate_url("target_source_tweet_urls", value)

    raw_set = raw.get("set")
    if not isinstance(raw_set, dict):
        raise ManualOverrideError("set はオブジェクトである必要があります")
    unknown_fields = sorted(set(raw_set) - EDITABLE_FIELDS)
    if unknown_fields:
        raise ManualOverrideError(f"編集できないフィールドです: {', '.join(unknown_fields)}")

    normalized_set: dict[str, str] = {}
    for field, raw_value in raw_set.items():
        if not isinstance(raw_value, (str, bool)):
            raise ManualOverrideError(f"{field} は文字列である必要があります")
        value = str(raw_value).lower() if isinstance(raw_value, bool) else raw_value.strip()
        normalized_set[field] = value

    for field in ("start_date", "end_date"):
        if field in normalized_set:
            _validate_date(field, normalized_set[field])
    start_date = normalized_set.get("start_date", "")
    end_date = normalized_set.get("end_date", "")
    if start_date and end_date and date.fromisoformat(end_date) < date.fromisoformat(start_date):
        raise ManualOverrideError("end_date は start_date 以降にしてください")

    if "start_time" in normalized_set:
        value = normalized_set["start_time"]
        if value and not TIME_PATTERN.fullmatch(value):
            raise ManualOverrideError("start_time は HH:MM 形式で入力してください")
    if normalized_set.get("posting_recommendation", "") not in POSTING_RECOMMENDATIONS:
        raise ManualOverrideError("posting_recommendation が不正です")
    for field in BOOLEAN_FIELDS:
        if field in normalized_set and normalized_set[field].lower() not in {"", "true", "false"}:
            raise ManualOverrideError(f"{field} は true / false / 空文字のいずれかです")
        if field in normalized_set:
            normalized_set[field] = normalized_set[field].lower()
    if "manual_publish_status" in normalized_set:
        normalized_set["manual_publish_status"] = normalized_set["manual_publish_status"].lower()
        if normalized_set["manual_publish_status"] not in PUBLISH_STATUSES:
            raise ManualOverrideError("manual_publish_status が不正です")
    if "manual_reference_url" in normalized_set:
        _validate_url("manual_reference_url", normalized_set["manual_reference_url"])

    return {
        "target_event_id": event_id,
        "target_source_tweet_urls": urls,
        "set": normalized_set,
        "note": str(raw.get("note") or "").strip(),
        "updated_at": str(raw.get("updated_at") or "").strip(),
    }


def validate_manual_event_overrides(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ManualOverrideError("補正JSONのトップレベルはオブジェクトである必要があります")
    if payload.get("version") != SCHEMA_VERSION:
        raise ManualOverrideError(f"補正JSONの version は {SCHEMA_VERSION} である必要があります")
    raw_overrides = payload.get("overrides")
    if not isinstance(raw_overrides, list):
        raise ManualOverrideError("overrides は配列である必要があります")

    overrides = [_validate_override(raw) for raw in raw_overrides]
    ids = [override["target_event_id"] for override in overrides]
    duplicates = sorted({event_id for event_id in ids if ids.count(event_id) > 1})
    if duplicates:
        raise ManualOverrideError(f"target_event_id が重複しています: {', '.join(duplicates)}")
    return {"version": SCHEMA_VERSION, "overrides": overrides}


def load_manual_event_overrides(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_override_payload()
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ManualOverrideError("補正JSONを読み込めません") from exc
    return validate_manual_event_overrides(payload)


def write_manual_event_overrides(path: Path, payload: Any) -> dict[str, Any]:
    validated = validate_manual_event_overrides(payload)
    text = json.dumps(validated, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(path, text, encoding="utf-8")
    return validated


def override_revision(payload: Any) -> str:
    validated = validate_manual_event_overrides(payload)
    stable = json.dumps(validated, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def upsert_manual_event_override(payload: Any, override: Any) -> dict[str, Any]:
    validated = validate_manual_event_overrides(payload)
    normalized = _validate_override(override)
    result = deepcopy(validated)
    replaced = False
    for index, existing in enumerate(result["overrides"]):
        if existing["target_event_id"] == normalized["target_event_id"]:
            result["overrides"][index] = normalized
            replaced = True
            break
    if not replaced:
        result["overrides"].append(normalized)
    result["overrides"].sort(key=lambda item: item["target_event_id"])
    return validate_manual_event_overrides(result)


def delete_manual_event_override(payload: Any, target_event_id: str) -> dict[str, Any]:
    validated = validate_manual_event_overrides(payload)
    event_id = target_event_id.strip()
    result = deepcopy(validated)
    result["overrides"] = [
        override for override in result["overrides"] if override["target_event_id"] != event_id
    ]
    return result


def apply_manual_event_overrides(
    records: list[dict[str, Any]], overrides: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    normalized_overrides = validate_manual_event_overrides(
        {"version": SCHEMA_VERSION, "overrides": overrides}
    )["overrides"]
    effective = [dict(record) for record in records]
    stats: dict[str, Any] = {"applied": 0, "orphan": [], "ambiguous": []}

    for override in normalized_overrides:
        event_id = override["target_event_id"]
        candidates = [index for index, record in enumerate(effective) if str(record.get("event_id") or "").strip() == event_id]
        if not candidates:
            target_urls = set(override["target_source_tweet_urls"])
            if target_urls:
                candidates = [
                    index
                    for index, record in enumerate(effective)
                    if split_source_tweet_urls(record) & target_urls
                ]
        if not candidates:
            stats["orphan"].append(event_id)
            continue
        if len(candidates) > 1:
            stats["ambiguous"].append(event_id)
            continue

        record = dict(effective[candidates[0]])
        record.update(override["set"])
        record["manual_override_updated_at"] = override["updated_at"]
        effective[candidates[0]] = record
        stats["applied"] += 1

    return effective, stats


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
