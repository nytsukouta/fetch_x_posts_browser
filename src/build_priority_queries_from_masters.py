from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from atomic_io import atomic_write_text


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ORGANIZATION_MASTER_CSV = ROOT_DIR / "data" / "output" / "organization_master.csv"
DEFAULT_VENUE_MASTER_CSV = ROOT_DIR / "data" / "output" / "venue_master.csv"
DEFAULT_OUTPUT_JSON = ROOT_DIR / "config" / "priority_queries.json"
DEFAULT_COLLECTION_POLICY = ROOT_DIR / "config" / "collection_policy.json"
DEFAULT_EXCLUDE_TERMS = [
    "映画",
    "上映",
    "シネマ",
    "ライブ",
    "LIVE",
    "コンサート",
    "DJ",
    "フェス",
    "アイドル",
    "ダンス",
]
THEATER_ORGANIZATION_CONTEXT_TERMS = ["演劇", "舞台", "公演", "上演", "朗読劇", "芝居", "小劇場", "稽古", "戯曲"]
THEATER_VENUE_CONTEXT_TERMS = ["演劇", "劇団", "上演", "朗読劇", "歌舞伎", "芝居"]
THEATER_ORGANIZATION_INCLUDE_KEYWORDS = ["劇団", "演劇", "朗読", "鑑賞会", "表現集団", "theater", "show"]
THEATER_ORGANIZATION_EXCLUDE_KEYWORDS = ["アイドル", "アンサンブル", "オーケストラ", "楽団", "吹奏楽", "ダンス"]
THEATER_VENUE_INCLUDE_KEYWORDS = ["劇場", "演劇堂", "ドラマ工房", "芸術村", "文化ホール", "文化会館", "能楽堂", "カレード"]
THEATER_VENUE_EXCLUDE_KEYWORDS = ["音楽堂", "live", "hall", "tabby's", "tabbys"]
DEFAULT_COLLECTION_POLICY_DATA: dict[str, Any] = {
    "organization": {
        "official_x_interval_days": 1,
        "without_official_x_interval_days": 3,
    },
    "venue": {
        "official_x_interval_days": 3,
        "without_official_x_interval_days": 6,
    },
    "overrides": {},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build X search queries from organization and venue master CSVs")
    parser.add_argument("--organization-master-csv", default=str(DEFAULT_ORGANIZATION_MASTER_CSV))
    parser.add_argument("--venue-master-csv", default=str(DEFAULT_VENUE_MASTER_CSV))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--collection-policy", default=str(DEFAULT_COLLECTION_POLICY))
    parser.add_argument("--max-results-per-query", type=int, default=10)
    return parser.parse_args()


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        normalized_name = (row.get("organization_name_normalized") or "").strip()
        if not normalized_name and (row.get("organization_name") or "").strip():
            row["organization_name_normalized"] = (row.get("organization_name") or "").strip()
    return rows


def load_collection_policy(path: Path = DEFAULT_COLLECTION_POLICY) -> dict[str, Any]:
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_COLLECTION_POLICY_DATA))
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return json.loads(json.dumps(DEFAULT_COLLECTION_POLICY_DATA))
    if not isinstance(loaded, dict):
        return json.loads(json.dumps(DEFAULT_COLLECTION_POLICY_DATA))
    policy = json.loads(json.dumps(DEFAULT_COLLECTION_POLICY_DATA))
    for section_name in ("organization", "venue", "review"):
        section = loaded.get(section_name)
        if isinstance(section, dict):
            policy.setdefault(section_name, {}).update(section)
    overrides = loaded.get("overrides")
    if isinstance(overrides, dict):
        policy["overrides"] = overrides
    return policy


def build_exclusion_suffix() -> str:
    terms = " ".join(f'-"{term}"' for term in DEFAULT_EXCLUDE_TERMS if term)
    return f"{terms} -is:retweet".strip()


def build_context_suffix(terms: list[str]) -> str:
    return "(" + " OR ".join(f'"{term}"' for term in terms if term) + ")"


def normalize_handle(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        return ""
    if candidate.startswith("@"):
        return candidate[1:].strip().strip("/")

    parsed = urlparse(candidate)
    if parsed.scheme and parsed.netloc:
        if parsed.netloc.lower() not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}:
            return ""
        path_parts = [part for part in parsed.path.split("/") if part]
        if not path_parts:
            return ""
        if path_parts[0].lower() in {"home", "search", "intent", "share", "i"}:
            return ""
        return path_parts[0].lstrip("@").strip()

    return candidate.lstrip("@").strip().strip("/")


def is_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def is_theater_organization(name: str) -> bool:
    normalized = name.strip().lower()
    if not normalized:
        return False
    if any(keyword.lower() in normalized for keyword in THEATER_ORGANIZATION_EXCLUDE_KEYWORDS):
        return False
    return any(keyword.lower() in normalized for keyword in THEATER_ORGANIZATION_INCLUDE_KEYWORDS)


def is_theater_venue(name: str) -> bool:
    normalized = name.strip().lower()
    if not normalized:
        return False
    if any(keyword.lower() in normalized for keyword in THEATER_VENUE_EXCLUDE_KEYWORDS):
        return False
    return any(keyword.lower() in normalized for keyword in THEATER_VENUE_INCLUDE_KEYWORDS)


def add_query(
    queries: list[dict[str, Any]],
    seen: set[str],
    label: str,
    query: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    normalized_query = " ".join(query.split())
    if not label or not normalized_query or normalized_query in seen:
        return
    seen.add(normalized_query)
    item: dict[str, Any] = {"label": label, "query": normalized_query}
    if metadata:
        item.update(metadata)
    queries.append(item)


def collection_interval_days(
    policy: dict[str, Any],
    source_type: str,
    source_id: str,
    has_official_x: bool,
) -> int:
    section = policy.get(source_type) or {}
    key = "official_x_interval_days" if has_official_x else "without_official_x_interval_days"
    interval = section.get(key, 3)
    override = (policy.get("overrides") or {}).get(source_id)
    if isinstance(override, dict) and "interval_days" in override:
        interval = override["interval_days"]
    try:
        return max(1, min(int(interval), 6))
    except (TypeError, ValueError):
        return 1 if has_official_x and source_type == "organization" else 3


def query_metadata(
    policy: dict[str, Any],
    source_type: str,
    source_id: str,
    has_official_x: bool,
) -> dict[str, Any]:
    interval = collection_interval_days(policy, source_type, source_id, has_official_x)
    return {
        "source_type": source_type,
        "source_id": source_id,
        "collection_interval_days": interval,
        "collection_tier": "daily" if interval == 1 else "low_frequency",
    }


def build_queries(
    organization_rows: list[dict[str, str]],
    venue_rows: list[dict[str, str]],
    collection_policy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    seen: set[str] = set()
    policy = collection_policy or load_collection_policy()
    exclusion_suffix = build_exclusion_suffix()
    organization_context_suffix = build_context_suffix(THEATER_ORGANIZATION_CONTEXT_TERMS)
    venue_context_suffix = build_context_suffix(THEATER_VENUE_CONTEXT_TERMS)

    for row in organization_rows:
        name = (row.get("organization_name_normalized") or row.get("organization_name") or "").strip()
        if is_truthy(row.get("query_exclude") or ""):
            continue
        force_include = is_truthy(row.get("query_include") or row.get("query_enabled") or "")
        if not name or (not force_include and not is_theater_organization(name)):
            continue
        official_handle = normalize_handle(row.get("official_x") or "")
        metadata = query_metadata(
            policy,
            "organization",
            (row.get("organization_id") or name).strip(),
            bool(official_handle),
        )
        if official_handle:
            handle_query = f'from:{official_handle} {organization_context_suffix} {exclusion_suffix}'.strip()
            add_query(queries, seen, f"劇団 {name} 公式X", handle_query, metadata)
        else:
            query = f'"{name}" {organization_context_suffix} {exclusion_suffix}'.strip()
            add_query(queries, seen, f"劇団 {name}", query, metadata)

    for row in venue_rows:
        name = (row.get("venue_name_normalized") or row.get("venue_name") or "").strip()
        if is_truthy(row.get("query_exclude") or ""):
            continue
        force_include = is_truthy(row.get("query_include") or row.get("query_enabled") or "")
        if not name or (not force_include and not is_theater_venue(name)):
            continue
        if not force_include and any(term in name for term in DEFAULT_EXCLUDE_TERMS):
            continue
        official_handle = normalize_handle(row.get("official_x") or "")
        metadata = query_metadata(
            policy,
            "venue",
            (row.get("venue_id") or name).strip(),
            bool(official_handle),
        )
        if official_handle:
            handle_query = f'from:{official_handle} {venue_context_suffix} {exclusion_suffix}'.strip()
            add_query(queries, seen, f"劇場 {name} 公式X", handle_query, metadata)
        else:
            query = f'"{name}" {venue_context_suffix} {exclusion_suffix}'.strip()
            add_query(queries, seen, f"劇場 {name}", query, metadata)

    return queries


def main() -> int:
    args = parse_args()
    organization_rows = load_rows(Path(args.organization_master_csv))
    venue_rows = load_rows(Path(args.venue_master_csv))
    collection_policy = load_collection_policy(Path(args.collection_policy))
    queries = build_queries(organization_rows, venue_rows, collection_policy)

    output_payload = {
        "max_results_per_query": args.max_results_per_query,
        "queries": queries,
    }
    output_path = Path(args.output_json)
    atomic_write_text(output_path, json.dumps(output_payload, ensure_ascii=False, indent=2) + "\n")

    print(f"saved query config: {output_path}")
    print(f"queries: {len(queries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())