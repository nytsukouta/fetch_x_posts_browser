from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_VENUE_MASTER_CSV = ROOT_DIR / "data" / "output" / "venue_master.csv"
DEFAULT_STRUCTURED_CUMULATIVE_CSV = ROOT_DIR / "data" / "output" / "structured_events_filtered_cumulative.csv"
DEFAULT_EVENT_CUMULATIVE_CSV = ROOT_DIR / "data" / "output" / "event_cumulative.csv"
DEFAULT_WEB_CANDIDATE_CSV = ROOT_DIR / "data" / "output" / "ishikawa_venue_candidates_web.csv"
DEFAULT_OUTPUT_CSV = ROOT_DIR / "data" / "output" / "venue_master_candidates_template.csv"

ISHIKAWA_LOCATION_PATTERNS = [
    "石川県",
    "金沢",
    "七尾",
    "小松",
    "白山",
    "加賀",
    "野々市",
    "能美",
    "かほく",
    "羽咋",
    "珠洲",
    "輪島",
    "能登",
    "津幡",
    "内灘",
    "志賀",
    "中能登",
    "宝達志水",
    "穴水",
    "川北",
]

VENUE_EXCLUDE_PATTERNS = [
    "オンライン",
    "配信",
    "YouTube",
    "Zoom",
    "スペース",
    "Xスペース",
]

SPACE_RE = re.compile(r"[ \t\u3000]+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract unregistered venue candidates into a master-friendly review template")
    parser.add_argument("--venue-master-csv", default=str(DEFAULT_VENUE_MASTER_CSV))
    parser.add_argument("--structured-cumulative-csv", default=str(DEFAULT_STRUCTURED_CUMULATIVE_CSV))
    parser.add_argument("--event-cumulative-csv", default=str(DEFAULT_EVENT_CUMULATIVE_CSV))
    parser.add_argument("--web-candidate-csv", default=str(DEFAULT_WEB_CANDIDATE_CSV))
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV))
    return parser.parse_args()


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def normalize_name(value: str) -> str:
    cleaned = SPACE_RE.sub("", value.strip().lower())
    cleaned = cleaned.replace("（", "(").replace("）", ")")
    cleaned = re.sub(r"[()・/\-]", "", cleaned)
    return cleaned


def slugify_venue_id(name: str) -> str:
    cleaned = name.strip().replace("　", " ").replace("/", "-")
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = re.sub(r"[^0-9A-Za-z一-龯ぁ-んァ-ヶ\-]", "", cleaned)
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    return f"venue-{cleaned}" if cleaned else ""


def is_ishikawa_related(*values: str) -> bool:
    joined = " ".join(value for value in values if value)
    return any(pattern in joined for pattern in ISHIKAWA_LOCATION_PATTERNS)


def is_plausible_venue(name: str) -> bool:
    if not name:
        return False
    if any(pattern.lower() in name.lower() for pattern in VENUE_EXCLUDE_PATTERNS):
        return False
    return len(name.strip()) >= 2


def build_known_venues(rows: list[dict[str, str]]) -> set[str]:
    known: set[str] = set()
    for row in rows:
        for field in ["venue_name_normalized", "venue_name"]:
            value = (row.get(field) or "").strip()
            if value:
                known.add(normalize_name(value))
    return known


def upsert_candidate(candidates: dict[str, dict[str, str]], row: dict[str, str]) -> None:
    key = normalize_name(row["venue_name"])
    existing = candidates.get(key)
    if not existing:
        candidates[key] = row
        return

    existing_count = int(existing.get("observed_count") or 0)
    row_count = int(row.get("observed_count") or 0)
    if row_count > existing_count:
        preferred = row
        fallback = existing
    else:
        preferred = existing
        fallback = row

    merged_urls = unique_pipe_values(preferred.get("source_urls", ""), fallback.get("source_urls", ""))
    merged_notes = unique_pipe_values(preferred.get("notes", ""), fallback.get("notes", ""))
    preferred["source_urls"] = " | ".join(merged_urls)
    preferred["notes"] = " | ".join(merged_notes)
    preferred["observed_count"] = str(len(merged_urls) if merged_urls else existing_count + row_count)
    if not preferred.get("location"):
        preferred["location"] = fallback.get("location", "")
    if not preferred.get("official_website"):
        preferred["official_website"] = fallback.get("official_website", "")
    candidates[key] = preferred


def unique_pipe_values(*values: str) -> list[str]:
    items: list[str] = []
    for value in values:
        for part in value.split(" | "):
            cleaned = part.strip()
            if cleaned and cleaned not in items:
                items.append(cleaned)
    return items


def candidate_row(
    *,
    venue_name: str,
    location: str,
    official_website: str,
    source_type: str,
    source_urls: str,
    observed_count: int,
    notes: str,
) -> dict[str, str]:
    return {
        "include": "",
        "venue_id": slugify_venue_id(venue_name),
        "venue_name": venue_name,
        "location": location,
        "official_website": official_website,
        "source_type": source_type,
        "source_urls": source_urls,
        "observed_count": str(observed_count),
        "notes": notes,
    }


def extract_from_structured_rows(rows: list[dict[str, str]], known_venues: set[str]) -> dict[str, dict[str, str]]:
    candidates: dict[str, dict[str, str]] = {}
    for row in rows:
        venue_name = (row.get("normalized_venue_name") or row.get("venue_name") or "").strip()
        if not is_plausible_venue(venue_name):
            continue
        if normalize_name(venue_name) in known_venues:
            continue
        location = (row.get("normalized_location") or row.get("location") or "").strip()
        source_text = (row.get("source_text") or "").strip()
        if not is_ishikawa_related(venue_name, location, source_text):
            continue
        upsert_candidate(
            candidates,
            candidate_row(
                venue_name=venue_name,
                location=location,
                official_website="",
                source_type="structured_events_filtered_cumulative",
                source_urls=(row.get("tweet_url") or "").strip(),
                observed_count=1,
                notes=(row.get("event_name") or row.get("reasoning") or "").strip(),
            ),
        )
    return candidates


def extract_from_event_rows(rows: list[dict[str, str]], known_venues: set[str]) -> dict[str, dict[str, str]]:
    candidates: dict[str, dict[str, str]] = {}
    for row in rows:
        venue_name = (row.get("normalized_venue_name") or row.get("venue_name") or "").strip()
        if not is_plausible_venue(venue_name):
            continue
        if normalize_name(venue_name) in known_venues:
            continue
        location = (row.get("normalized_location") or row.get("location") or "").strip()
        source_text = (row.get("source_text") or "").strip()
        if not is_ishikawa_related(venue_name, location, source_text):
            continue
        upsert_candidate(
            candidates,
            candidate_row(
                venue_name=venue_name,
                location=location,
                official_website="",
                source_type="event_cumulative",
                source_urls=(row.get("source_tweet_urls") or row.get("tweet_url") or "").strip(),
                observed_count=int(row.get("source_tweet_count") or 1),
                notes=(row.get("event_name") or row.get("reasoning") or "").strip(),
            ),
        )
    return candidates


def extract_from_web_rows(rows: list[dict[str, str]], known_venues: set[str]) -> dict[str, dict[str, str]]:
    candidates: dict[str, dict[str, str]] = {}
    for row in rows:
        venue_name = (row.get("candidate_name") or "").strip()
        if not is_plausible_venue(venue_name):
            continue
        if normalize_name(venue_name) in known_venues:
            continue
        location = (row.get("location_hint") or "").strip()
        if location and not is_ishikawa_related(location):
            continue
        upsert_candidate(
            candidates,
            candidate_row(
                venue_name=venue_name,
                location=location,
                official_website=(row.get("official_website_candidate") or "").strip(),
                source_type="web_candidate",
                source_urls=(row.get("source_url") or "").strip(),
                observed_count=int(row.get("score") or 1),
                notes=(row.get("reason") or "").strip(),
            ),
        )
    return candidates


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "include",
        "venue_id",
        "venue_name",
        "location",
        "official_website",
        "source_type",
        "source_urls",
        "observed_count",
        "notes",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    known_venues = build_known_venues(load_csv_rows(Path(args.venue_master_csv)))
    candidates: dict[str, dict[str, str]] = {}

    for source_candidates in [
        extract_from_structured_rows(load_csv_rows(Path(args.structured_cumulative_csv)), known_venues),
        extract_from_event_rows(load_csv_rows(Path(args.event_cumulative_csv)), known_venues),
        extract_from_web_rows(load_csv_rows(Path(args.web_candidate_csv)), known_venues),
    ]:
        for row in source_candidates.values():
            upsert_candidate(candidates, row)

    rows = sorted(
        candidates.values(),
        key=lambda row: (-int(row.get("observed_count") or 0), row.get("venue_name") or ""),
    )
    write_csv(Path(args.output_csv), rows)
    print(f"saved venue template: {args.output_csv}")
    print(f"rows: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())