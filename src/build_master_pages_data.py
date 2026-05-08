from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ORGANIZATION_MASTER_CSV = ROOT_DIR / "data" / "output" / "organization_master.csv"
DEFAULT_VENUE_MASTER_CSV = ROOT_DIR / "data" / "output" / "venue_master.csv"
DEFAULT_OUTPUT_JSON = ROOT_DIR / "data" / "output" / "master_data.json"
DEFAULT_PAGES_JSON = ROOT_DIR / "docs" / "data" / "master_data.json"
DEFAULT_WEB_JSON = ROOT_DIR / "web" / "data" / "master_data.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build published master data JSON for organizations and venues")
    parser.add_argument("--organization-master-csv", default=str(DEFAULT_ORGANIZATION_MASTER_CSV))
    parser.add_argument("--venue-master-csv", default=str(DEFAULT_VENUE_MASTER_CSV))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--pages-json", default=str(DEFAULT_PAGES_JSON))
    parser.add_argument("--web-json", default=str(DEFAULT_WEB_JSON))
    return parser.parse_args()


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def normalize_x_url(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        return cleaned
    if cleaned.startswith("@"):
        cleaned = cleaned[1:]
    return f"https://x.com/{cleaned}"


def is_truthy(value: str) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def build_organization_items(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        items.append(
            {
                "id": (row.get("organization_id") or "").strip(),
                "name": (row.get("organization_name") or "").strip(),
                "location": (row.get("location") or "").strip(),
                "official_website": (row.get("official_website") or "").strip(),
                "official_x": normalize_x_url(row.get("official_x") or ""),
                "query_include": is_truthy(row.get("query_include") or ""),
            }
        )
    return sorted(items, key=lambda item: (item["location"], item["name"]))


def build_venue_items(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        items.append(
            {
                "id": (row.get("venue_id") or "").strip(),
                "name": (row.get("venue_name") or "").strip(),
                "location": (row.get("location") or "").strip(),
                "official_website": (row.get("official_website") or "").strip(),
            }
        )
    return sorted(items, key=lambda item: (item["location"], item["name"]))


def build_payload(organization_rows: list[dict[str, str]], venue_rows: list[dict[str, str]]) -> dict[str, Any]:
    organizations = build_organization_items(organization_rows)
    venues = build_venue_items(venue_rows)
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "counts": {
            "organizations": len(organizations),
            "venues": len(venues),
        },
        "organizations": organizations,
        "venues": venues,
    }


def write_json(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def main() -> int:
    args = parse_args()
    organization_rows = load_csv_rows(Path(args.organization_master_csv))
    venue_rows = load_csv_rows(Path(args.venue_master_csv))
    payload = build_payload(organization_rows, venue_rows)

    write_json(payload, Path(args.output_json))
    write_json(payload, Path(args.pages_json))
    write_json(payload, Path(args.web_json))

    print(f"saved master json: {args.output_json}")
    print(f"saved pages master json: {args.pages_json}")
    print(f"saved web master json: {args.web_json}")
    print(f"organizations: {payload['counts']['organizations']}")
    print(f"venues: {payload['counts']['venues']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())