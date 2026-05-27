from __future__ import annotations

import argparse
import csv
from datetime import date, datetime
import json
from pathlib import Path
import re
from typing import Any

from event_candidate_rules import build_date_range, is_schedule_eligible_event


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_EVENTS_CSV = ROOT_DIR / "data" / "output" / "structured_events_filtered.csv"
DEFAULT_ORGANIZATION_MASTER_CSV = ROOT_DIR / "data" / "output" / "organization_master.csv"
DEFAULT_VENUE_MASTER_CSV = ROOT_DIR / "data" / "output" / "venue_master.csv"
DEFAULT_OUTPUT_CSV = ROOT_DIR / "data" / "output" / "schedule_list.csv"
DEFAULT_OUTPUT_JSON = ROOT_DIR / "data" / "output" / "schedule_list.json"
DEFAULT_PAGES_JSON = ROOT_DIR / "docs" / "data" / "schedule_list.json"
NON_ALNUM_RE = re.compile(r"[^0-9a-zA-Z\u3040-\u30ff\u3400-\u9fff]+")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a schedule planning list from filtered theater events")
    parser.add_argument("--events-csv", default=str(DEFAULT_EVENTS_CSV), help="filtered events CSV のパス")
    parser.add_argument(
        "--organization-master-csv",
        default=str(DEFAULT_ORGANIZATION_MASTER_CSV),
        help="劇団マスターCSVのパス",
    )
    parser.add_argument(
        "--venue-master-csv",
        default=str(DEFAULT_VENUE_MASTER_CSV),
        help="劇場マスターCSVのパス",
    )
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV), help="スケジュール一覧CSVの保存先")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON), help="スケジュール一覧JSONの保存先")
    parser.add_argument(
        "--pages-json",
        default=str(DEFAULT_PAGES_JSON),
        help="GitHub Pages 用 JSON の保存先",
    )
    return parser.parse_args()


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if path.name == "organization_master.csv":
        for row in rows:
            normalized_name = (row.get("organization_name_normalized") or "").strip()
            if not normalized_name and (row.get("organization_name") or "").strip():
                row["organization_name_normalized"] = (row.get("organization_name") or "").strip()
    return rows


def index_master(rows: list[dict[str, str]], key_field: str) -> dict[str, dict[str, str]]:
    indexed: dict[str, dict[str, str]] = {}
    for row in rows:
        key = (row.get(key_field) or "").strip()
        if key:
            indexed[key] = row
    return indexed


def choose_reference_url(
    event_row: dict[str, str],
    organization_row: dict[str, str] | None,
    venue_row: dict[str, str] | None,
) -> tuple[str, str]:
    if organization_row:
        official_website = (organization_row.get("official_website") or "").strip()
        if official_website:
            return official_website, "organization_official_website"

        official_x = (organization_row.get("official_x") or "").strip()
        if official_x:
            return normalize_x_url(official_x), "organization_official_x"

    if venue_row:
        official_website = (venue_row.get("official_website") or "").strip()
        if official_website:
            return official_website, "venue_official_website"

    author_username = (event_row.get("author_username") or "").strip()
    if author_username:
        return f"https://x.com/{author_username}", "source_author_x_candidate"

    return "", ""


def normalize_x_url(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        return cleaned
    if cleaned.startswith("@"):
        cleaned = cleaned[1:]
    return f"https://x.com/{cleaned}"


def compact_text(value: str) -> str:
    return NON_ALNUM_RE.sub("", value.strip().lower())


def build_schedule_identity_key(row: dict[str, str]) -> tuple[str, str, str, str, str, str]:
    event_name = compact_text((row.get("event_name") or row.get("normalized_event_name") or "").strip())
    organization_name = compact_text((row.get("organization") or "").strip())
    venue_name = compact_text((row.get("normalized_venue_name") or row.get("venue_name") or "").strip())
    start_date = (row.get("start_date") or "").strip()
    end_date = (row.get("end_date") or "").strip()
    category = (row.get("category") or "").strip()
    return (event_name, organization_name, venue_name, start_date, end_date, category)


def schedule_row_priority(event_row: dict[str, str], reference_url: str, performance_schedule: str) -> tuple[int, int, int, int, int, str]:
    has_reference_url = int(bool(reference_url))
    has_start_time = int(bool((event_row.get("start_time") or "").strip()))
    source_tweet_count = int(str(event_row.get("source_tweet_count") or "0") or "0")
    event_name_length = len((event_row.get("event_name") or "").strip())
    created_at = (event_row.get("created_at") or "").strip()
    return (has_reference_url, has_start_time, source_tweet_count, len(performance_schedule), event_name_length, created_at)


def build_schedule_rows(
    event_rows: list[dict[str, str]],
    organization_index: dict[str, dict[str, str]],
    venue_index: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    candidate_rows: list[dict[str, str]] = []

    for event_row in event_rows:
        if str(event_row.get("is_noise") or "").lower() == "true":
            continue

        organization_name = (event_row.get("organization") or "").strip()
        venue_name = (event_row.get("normalized_venue_name") or event_row.get("venue_name") or "").strip()
        start_date = (event_row.get("start_date") or "").strip()
        end_date = (event_row.get("end_date") or "").strip()

        if not is_current_or_upcoming_event(start_date, end_date):
            continue

        date_range = build_date_range(event_row)
        event_name = (event_row.get("event_name") or "").strip()

        if not is_schedule_candidate(event_name, organization_name, venue_name, date_range, event_row):
            continue

        candidate_rows.append(event_row)

    candidate_rows = suppress_preview_like_duplicates(candidate_rows)

    schedule_by_key: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}

    for event_row in candidate_rows:
        organization_name = (event_row.get("organization") or "").strip()
        venue_name = (event_row.get("normalized_venue_name") or event_row.get("venue_name") or "").strip()
        start_date = (event_row.get("start_date") or "").strip()
        end_date = (event_row.get("end_date") or "").strip()
        date_range = build_date_range(event_row)
        event_name = (event_row.get("event_name") or "").strip()

        dedupe_key = build_schedule_identity_key(event_row)

        organization_row = organization_index.get(organization_name)
        venue_row = venue_index.get(venue_name)
        reference_url, reference_source = choose_reference_url(event_row, organization_row, venue_row)

        candidate_row = {
            "event_name": event_name,
            "organization_id": (organization_row.get("organization_id") or "").strip() if organization_row else "",
            "organization_name": organization_name,
            "venue_name": venue_name,
            "performance_schedule": date_range,
            "official_reference_url": reference_url,
            "official_reference_type": reference_source,
            "normalized_location": (event_row.get("normalized_location") or "").strip(),
            "source_tweet_url": (event_row.get("tweet_url") or "").strip(),
            "_priority": schedule_row_priority(event_row, reference_url, date_range),
        }

        existing_row = schedule_by_key.get(dedupe_key)
        if existing_row is None or candidate_row["_priority"] > existing_row["_priority"]:
            if existing_row and not candidate_row["official_reference_url"]:
                candidate_row["official_reference_url"] = existing_row["official_reference_url"]
                candidate_row["official_reference_type"] = existing_row["official_reference_type"]
            schedule_by_key[dedupe_key] = candidate_row
            continue

        if not existing_row["official_reference_url"] and reference_url:
            existing_row["official_reference_url"] = reference_url
            existing_row["official_reference_type"] = reference_source

    rows = []
    for row in schedule_by_key.values():
        row.pop("_priority", None)
        rows.append(row)
    rows.sort(key=lambda row: (row["performance_schedule"], row["organization_name"], row["venue_name"], row["event_name"]))
    return rows


def is_schedule_candidate(event_name: str, organization_name: str, venue_name: str, date_range: str, event_row: dict[str, str]) -> bool:
    return is_schedule_eligible_event(event_row)


def suppress_preview_like_duplicates(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    grouped_rows: dict[str, list[dict[str, str]]] = {}
    passthrough_rows: list[dict[str, str]] = []

    for row in rows:
        group_key = build_preview_group_key(row)
        if not group_key:
            passthrough_rows.append(row)
            continue
        grouped_rows.setdefault(group_key, []).append(row)

    filtered_rows = list(passthrough_rows)
    for group in grouped_rows.values():
        kept_rows: list[dict[str, str]] = []
        for row in sorted(group, key=preview_row_priority, reverse=True):
            if any(is_subsumed_preview_row(row, kept_row) for kept_row in kept_rows):
                continue
            kept_rows.append(row)
        filtered_rows.extend(kept_rows)

    return filtered_rows


def build_preview_group_key(row: dict[str, str]) -> str:
    event_name = (row.get("normalized_event_name") or row.get("event_name") or "").strip()
    if not event_name:
        return ""

    start_date = (row.get("start_date") or "").strip()
    month_bucket = start_date[:7] if len(start_date) >= 7 else ""
    organization_name = (row.get("organization") or "").strip()
    venue_name = (row.get("normalized_venue_name") or row.get("venue_name") or "").strip()

    if organization_name:
        return "|".join([event_name, organization_name, month_bucket])
    if venue_name:
        return "|".join([event_name, venue_name, month_bucket])
    return ""


def preview_row_priority(row: dict[str, str]) -> tuple[int, int, int, int, str]:
    venue_name = (row.get("normalized_venue_name") or row.get("venue_name") or "").strip()
    start_date = (row.get("start_date") or "").strip()
    end_date = (row.get("end_date") or "").strip()
    start_time = (row.get("start_time") or "").strip()
    source_tweet_count = int(str(row.get("source_tweet_count") or "0") or "0")
    has_multi_day_range = int(bool(start_date and end_date and start_date != end_date))
    has_venue = int(bool(venue_name))
    has_start_time = int(bool(start_time))
    return (has_venue, has_multi_day_range, has_start_time, source_tweet_count, start_date)


def is_subsumed_preview_row(candidate: dict[str, str], canonical: dict[str, str]) -> bool:
    candidate_venue = (candidate.get("normalized_venue_name") or candidate.get("venue_name") or "").strip()
    canonical_venue = (canonical.get("normalized_venue_name") or canonical.get("venue_name") or "").strip()

    if not candidate_venue and canonical_venue:
        return True
    if candidate_venue and canonical_venue and candidate_venue != canonical_venue:
        return False

    candidate_start = parse_iso_date((candidate.get("start_date") or "").strip())
    candidate_end = parse_iso_date((candidate.get("end_date") or "").strip()) or candidate_start
    canonical_start = parse_iso_date((canonical.get("start_date") or "").strip())
    canonical_end = parse_iso_date((canonical.get("end_date") or "").strip()) or canonical_start
    if not candidate_start or not candidate_end or not canonical_start or not canonical_end:
        return False

    if canonical_start <= candidate_start and canonical_end >= candidate_end:
        return preview_row_priority(canonical) > preview_row_priority(candidate)

    return False


def parse_iso_date(value: str) -> date | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        return None


def is_current_or_upcoming_event(start_date: str, end_date: str) -> bool:
    effective_end_date = parse_iso_date(end_date) or parse_iso_date(start_date)
    if effective_end_date is None:
        return True
    return effective_end_date >= date.today()


def write_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "event_name",
        "organization_id",
        "organization_name",
        "venue_name",
        "performance_schedule",
        "official_reference_url",
        "official_reference_type",
        "normalized_location",
        "source_tweet_url",
    ]
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(rows: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "count": len(rows),
        "items": rows,
    }
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def main() -> int:
    args = parse_args()
    event_rows = load_csv_rows(Path(args.events_csv))
    organization_rows = load_csv_rows(Path(args.organization_master_csv))
    venue_rows = load_csv_rows(Path(args.venue_master_csv))

    organization_index = index_master(organization_rows, "organization_name_normalized")
    venue_index = index_master(venue_rows, "venue_name_normalized")
    schedule_rows = build_schedule_rows(event_rows, organization_index, venue_index)
    write_csv(schedule_rows, Path(args.output_csv))
    write_json(schedule_rows, Path(args.output_json))
    write_json(schedule_rows, Path(args.pages_json))

    print(f"saved schedule list: {args.output_csv}")
    print(f"saved schedule json: {args.output_json}")
    print(f"saved pages json: {args.pages_json}")
    print(f"rows: {len(schedule_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())