from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_CSV = ROOT_DIR / "data" / "output" / "structured_events_filtered.csv"
DEFAULT_ORGANIZATION_MASTER_CSV = ROOT_DIR / "data" / "output" / "organization_master.csv"
DEFAULT_VENUE_MASTER_CSV = ROOT_DIR / "data" / "output" / "venue_master.csv"
NON_ALNUM_RE = re.compile(r"[^0-9a-zA-Z\u3040-\u30ff\u3400-\u9fff]+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build organization and venue master files from filtered event records")
    parser.add_argument("--input-csv", default=str(DEFAULT_INPUT_CSV), help="filtered events CSV のパス")
    parser.add_argument(
        "--organization-output",
        default=str(DEFAULT_ORGANIZATION_MASTER_CSV),
        help="劇団マスターCSVの保存先",
    )
    parser.add_argument(
        "--venue-output",
        default=str(DEFAULT_VENUE_MASTER_CSV),
        help="劇場マスターCSVの保存先",
    )
    return parser.parse_args()


def load_rows(input_csv: Path) -> list[dict[str, str]]:
    with input_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def slugify(value: str, fallback_prefix: str, fallback_number: int) -> str:
    cleaned = NON_ALNUM_RE.sub("-", value.strip().lower()).strip("-")
    if cleaned:
        return cleaned
    return f"{fallback_prefix}-{fallback_number:04d}"


def build_organization_master(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}

    for row in rows:
        canonical_name = (row.get("organization") or "").strip()
        if not canonical_name:
            continue

        key = canonical_name
        bucket = buckets.setdefault(
            key,
            {
                "organization_name": canonical_name,
                "organization_name_normalized": canonical_name,
                "aliases": set(),
                "base_locations": set(),
                "event_count": 0,
                "source_urls": set(),
            },
        )
        bucket["event_count"] += 1
        bucket["source_urls"].add((row.get("tweet_url") or "").strip())

        author_name = (row.get("author_name") or "").strip()
        if author_name and author_name != canonical_name:
            bucket["aliases"].add(author_name)

        location = (row.get("normalized_location") or row.get("location") or "").strip()
        if location:
            bucket["base_locations"].add(location)

    records: list[dict[str, Any]] = []
    for index, bucket in enumerate(sorted(buckets.values(), key=lambda item: item["organization_name"]), start=1):
        records.append(
            {
                "organization_id": f"org-{slugify(bucket['organization_name'], 'org', index)}",
                "organization_name": bucket["organization_name"],
                "organization_name_normalized": bucket["organization_name_normalized"],
                "aliases": " | ".join(sorted(bucket["aliases"])),
                "base_location": " | ".join(sorted(bucket["base_locations"])),
                "official_x": "",
                "official_website": "",
                "event_count": bucket["event_count"],
                "sample_source_url": sorted(url for url in bucket["source_urls"] if url)[:1][0] if any(bucket["source_urls"]) else "",
                "notes": "",
            }
        )
    return records


def build_venue_master(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}

    for row in rows:
        canonical_name = (row.get("normalized_venue_name") or row.get("venue_name") or "").strip()
        if not canonical_name:
            continue

        key = canonical_name
        bucket = buckets.setdefault(
            key,
            {
                "venue_name": canonical_name,
                "venue_name_normalized": canonical_name,
                "aliases": set(),
                "locations": set(),
                "event_count": 0,
                "source_urls": set(),
            },
        )
        bucket["event_count"] += 1
        bucket["source_urls"].add((row.get("tweet_url") or "").strip())

        raw_venue_name = (row.get("venue_name") or "").strip()
        if raw_venue_name and raw_venue_name != canonical_name:
            bucket["aliases"].add(raw_venue_name)

        location = (row.get("normalized_location") or row.get("location") or "").strip()
        if location:
            bucket["locations"].add(location)

    records: list[dict[str, Any]] = []
    for index, bucket in enumerate(sorted(buckets.values(), key=lambda item: item["venue_name"]), start=1):
        records.append(
            {
                "venue_id": f"venue-{slugify(bucket['venue_name'], 'venue', index)}",
                "venue_name": bucket["venue_name"],
                "venue_name_normalized": bucket["venue_name_normalized"],
                "aliases": " | ".join(sorted(bucket["aliases"])),
                "location": " | ".join(sorted(bucket["locations"])),
                "address": "",
                "official_website": "",
                "event_count": bucket["event_count"],
                "sample_source_url": sorted(url for url in bucket["source_urls"] if url)[:1][0] if any(bucket["source_urls"]) else "",
                "notes": "",
            }
        )
    return records


def write_csv(records: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        output_path.write_text("", encoding="utf-8")
        return

    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)


def main() -> int:
    args = parse_args()
    rows = load_rows(Path(args.input_csv))
    organization_records = build_organization_master(rows)
    venue_records = build_venue_master(rows)

    write_csv(organization_records, Path(args.organization_output))
    write_csv(venue_records, Path(args.venue_output))

    print(f"saved organization master: {args.organization_output}")
    print(f"saved venue master: {args.venue_output}")
    print(f"organization_rows: {len(organization_records)}")
    print(f"venue_rows: {len(venue_records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())