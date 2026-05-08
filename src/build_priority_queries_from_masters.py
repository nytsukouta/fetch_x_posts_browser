from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ORGANIZATION_MASTER_CSV = ROOT_DIR / "data" / "output" / "organization_master.csv"
DEFAULT_VENUE_MASTER_CSV = ROOT_DIR / "data" / "output" / "venue_master.csv"
DEFAULT_OUTPUT_JSON = ROOT_DIR / "config" / "priority_queries.json"
DEFAULT_EXCLUDE_TERMS = ["金沢おぐら座"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build X search queries from organization and venue master CSVs")
    parser.add_argument("--organization-master-csv", default=str(DEFAULT_ORGANIZATION_MASTER_CSV))
    parser.add_argument("--venue-master-csv", default=str(DEFAULT_VENUE_MASTER_CSV))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--max-results-per-query", type=int, default=10)
    return parser.parse_args()


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def normalize_handle(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    if cleaned.startswith("http://x.com/") or cleaned.startswith("https://x.com/"):
        cleaned = cleaned.rsplit("/", 1)[-1]
    if cleaned.startswith("@"):
        cleaned = cleaned[1:]
    return cleaned.strip()


def build_exclusion_suffix() -> str:
    return " ".join(f'-"{term}"' for term in DEFAULT_EXCLUDE_TERMS if term)


def add_query(queries: list[dict[str, str]], seen: set[str], label: str, query: str) -> None:
    normalized_query = " ".join(query.split())
    if not label or not normalized_query or normalized_query in seen:
        return
    seen.add(normalized_query)
    queries.append({"label": label, "query": normalized_query})


def build_queries(organization_rows: list[dict[str, str]], venue_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    queries: list[dict[str, str]] = []
    seen: set[str] = set()
    exclusion_suffix = build_exclusion_suffix()

    for row in organization_rows:
        name = (row.get("organization_name_normalized") or row.get("organization_name") or "").strip()
        if not name:
            continue
        official_x = normalize_handle(row.get("official_x") or "")
        if official_x:
            add_query(queries, seen, f"劇団公式 {name}", f"from:{official_x}")
        query = f'"{name}" {exclusion_suffix}'.strip()
        add_query(queries, seen, f"劇団 {name}", query)

    for row in venue_rows:
        name = (row.get("venue_name_normalized") or row.get("venue_name") or "").strip()
        if not name:
            continue
        if any(term in name for term in DEFAULT_EXCLUDE_TERMS):
            continue
        query = f'"{name}" {exclusion_suffix}'.strip()
        add_query(queries, seen, f"劇場 {name}", query)

    return queries


def main() -> int:
    args = parse_args()
    organization_rows = load_rows(Path(args.organization_master_csv))
    venue_rows = load_rows(Path(args.venue_master_csv))
    queries = build_queries(organization_rows, venue_rows)

    output_payload = {
        "max_results_per_query": args.max_results_per_query,
        "queries": queries,
    }
    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"saved query config: {output_path}")
    print(f"queries: {len(queries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())