from __future__ import annotations

import unicodedata
from datetime import date
from typing import Any


THEATER_SIGNAL_PATTERNS = [
    "演劇",
    "劇団",
    "朗読",
    "朗読劇",
    "歌舞伎",
    "舞台",
    "上演",
    "演芸",
    "ドラマ",
    "観劇",
    "怪談",
    "一座",
]

NON_THEATER_PATTERNS = [
    "アイドル",
    "live",
    "tour",
    "ライブ",
    "ダンス",
    "バンド",
    "コンサート",
    "勉強会",
    "ビジネス",
    "子ども向けイベント",
    "カイロ",
    "アートフェス",
    "展",
]

CONDITIONAL_NOISE_PATTERNS = [
    "ワークショップ",
    "フェス",
    "祭り",
]

EXCLUDED_VENUE_PATTERNS = [
    "金沢おぐら座",
    "おぐら座",
]


def parse_iso_date(value: str) -> date | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        return None


def parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None

    cleaned = str(value).strip().lower()
    if cleaned in {"true", "1", "yes"}:
        return True
    if cleaned in {"false", "0", "no"}:
        return False
    return None


def normalize_posting_recommendation(value: Any) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in {"post", "review", "skip"}:
        return cleaned
    return ""


def source_text_mentions_exact_start_date(row: dict[str, str]) -> bool:
    start_date = parse_iso_date(row.get("start_date") or "")
    if start_date is None:
        return False

    source_text = unicodedata.normalize("NFKC", (row.get("source_text") or "").strip())
    if not source_text:
        return False

    month = start_date.month
    day = start_date.day
    patterns = {
        start_date.isoformat(),
        f"{start_date.year}/{month}/{day}",
        f"{start_date.year}/{start_date.month:02d}/{start_date.day:02d}",
        f"{month}/{day}",
        f"{start_date.month:02d}/{start_date.day:02d}",
        f"{month}月{day}日",
        f"{start_date.month:02d}月{start_date.day:02d}日",
    }
    return any(pattern in source_text for pattern in patterns)


def has_postable_event_details(row: dict[str, str]) -> bool:
    posting_recommendation = normalize_posting_recommendation(row.get("posting_recommendation"))
    is_event_announcement = parse_bool(row.get("is_event_announcement"))
    has_actionable_schedule_info = parse_bool(row.get("has_actionable_schedule_info"))

    if posting_recommendation == "post":
        return True
    if posting_recommendation == "skip":
        return False
    if is_event_announcement is False:
        return False
    if has_actionable_schedule_info is True:
        return True

    if not source_text_mentions_exact_start_date(row):
        return False

    has_venue = bool((row.get("normalized_venue_name") or row.get("venue_name") or "").strip())
    has_organization = bool((row.get("organization") or "").strip())
    return has_venue or has_organization


def contains_any(value: str, patterns: list[str]) -> bool:
    lowered = value.lower()
    return any(pattern.lower() in lowered for pattern in patterns)


def build_date_range(row: dict[str, str]) -> str:
    start_date = (row.get("start_date") or "").strip()
    end_date = (row.get("end_date") or "").strip()
    start_time = (row.get("start_time") or "").strip()
    if start_date and end_date and start_date != end_date:
        if start_time:
            return f"{start_date} - {end_date} {start_time}"
        return f"{start_date} - {end_date}"
    if start_date:
        if start_time:
            return f"{start_date} {start_time}"
        return start_date
    return ""


def is_schedule_eligible_event(row: dict[str, str]) -> bool:
    event_name = (row.get("event_name") or "").strip()
    organization_name = (row.get("organization") or "").strip()
    venue_name = (row.get("normalized_venue_name") or row.get("venue_name") or "").strip()
    date_range = build_date_range(row)
    manual_publish_status = (row.get("manual_publish_status") or "default").strip().lower()

    if manual_publish_status == "excluded":
        return False
    if manual_publish_status == "published":
        return parse_iso_date(row.get("start_date") or "") is not None and bool(event_name or organization_name)

    if not date_range:
        return False
    if not event_name and not organization_name:
        return False
    if not venue_name and not organization_name:
        return False
    if not has_postable_event_details(row):
        return False
    if contains_any(venue_name, EXCLUDED_VENUE_PATTERNS):
        return False

    signal_text = " ".join(
        [
            event_name,
            organization_name,
            venue_name,
            (row.get("category") or "").strip(),
            (row.get("source_text") or "").strip(),
        ]
    )
    has_theater_signal = contains_any(signal_text, THEATER_SIGNAL_PATTERNS)

    if contains_any(signal_text, NON_THEATER_PATTERNS) and not has_theater_signal:
        return False
    if contains_any(signal_text, CONDITIONAL_NOISE_PATTERNS) and not has_theater_signal:
        return False
    if not has_theater_signal and not contains_any((row.get("category") or "").strip(), ["公演", "朗読劇"]):
        return False

    return True