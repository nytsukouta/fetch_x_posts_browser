from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_CSV = ROOT_DIR / "data" / "output" / "structured_events_filtered_cumulative.csv"
DEFAULT_OUTPUT_CSV = ROOT_DIR / "data" / "output" / "event_cumulative.csv"
NON_ALNUM_RE = re.compile(r"[^0-9a-zA-Z\u3040-\u30ff\u3400-\u9fff]+")

MERGE_FIELDS = [
    "event_name",
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build event-level cumulative records from filtered cumulative tweet records")
    parser.add_argument("--input-csv", default=str(DEFAULT_INPUT_CSV), help="filtered cumulative CSV のパス")
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV), help="イベント累積CSVの保存先")
    return parser.parse_args()


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def compact_text(value: str) -> str:
    cleaned = NON_ALNUM_RE.sub("", value.strip().lower())
    return cleaned


def build_event_key(row: dict[str, str]) -> str:
    event_name = compact_text(row.get("event_name") or "")
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
        organization = (best_row.get("organization") or "").strip()
        venue_name = (best_row.get("normalized_venue_name") or best_row.get("venue_name") or "").strip()
        id_seed = event_name or organization or venue_name or bucket["event_key"]

        records.append(
            {
                "event_id": f"event-{slugify(id_seed, 'event', index)}",
                "event_key": bucket["event_key"],
                "tweet_url": sorted(bucket["source_tweet_urls"])[0] if bucket["source_tweet_urls"] else "",
                "created_at": bucket["last_seen_created_at"],
                "author_name": (best_row.get("author_name") or "").strip(),
                "author_username": (best_row.get("author_username") or "").strip(),
                "event_name": event_name,
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
    write_csv(records, Path(args.output_csv))

    print(f"saved event cumulative: {args.output_csv}")
    print(f"rows: {len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())