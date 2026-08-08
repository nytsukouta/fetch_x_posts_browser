from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from atomic_io import atomic_open
from build_priority_queries_from_masters import DEFAULT_COLLECTION_POLICY, load_collection_policy
from fetch_x_posts import DEFAULT_METRICS_FILE, load_queries, parse_timestamp


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_QUERY_FILE = ROOT_DIR / "config" / "priority_queries.json"
DEFAULT_OUTPUT_FILE = ROOT_DIR / "data" / "output" / "query_effectiveness_review.csv"

REVIEW_FIELDS = [
    "window_start",
    "window_end",
    "query_label",
    "source_type",
    "source_id",
    "collection_interval_days",
    "collected_runs",
    "returned_tweet_count",
    "average_results_per_run",
    "runs_with_results",
    "last_collected_at",
    "recommendation",
]


def load_metrics(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except (OSError, csv.Error):
        return []


def _integer(value: Any) -> int:
    try:
        return int(str(value or "0"))
    except ValueError:
        return 0


def _number(value: Any) -> float:
    try:
        return float(str(value or "0"))
    except ValueError:
        return 0.0


def _current_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def build_review_rows(
    metrics: list[dict[str, str]],
    queries: list[dict[str, Any]],
    as_of: datetime,
    window_days: int = 30,
    minimum_collected_runs: int = 3,
    low_effect_average_results: float = 1.0,
) -> list[dict[str, Any]]:
    current_time = _current_time(as_of)
    window_start = current_time - timedelta(days=max(1, window_days))
    query_by_label = {
        str(query.get("label") or ""): query
        for query in queries
        if str(query.get("label") or "")
    }
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for metric in metrics:
        if str(metric.get("status") or "") != "collected":
            continue
        collected_at = parse_timestamp(metric.get("collected_at", ""))
        if collected_at is None or collected_at < window_start or collected_at > current_time:
            continue
        label = str(metric.get("query_label") or "")
        if label:
            grouped[label].append(metric)

    labels = list(query_by_label)
    labels.extend(sorted(label for label in grouped if label not in query_by_label))
    review_rows: list[dict[str, Any]] = []
    for label in labels:
        query = query_by_label.get(label, {})
        observations = grouped.get(label, [])
        result_count = sum(_integer(row.get("result_count")) for row in observations)
        run_count = len(observations)
        runs_with_results = sum(1 for row in observations if _integer(row.get("result_count")) > 0)
        average_results = result_count / run_count if run_count else 0.0
        last_collected_at = max(
            (str(row.get("collected_at") or "") for row in observations),
            default="",
        )
        if run_count < minimum_collected_runs:
            recommendation = "observe"
        elif average_results < low_effect_average_results:
            recommendation = "review"
        else:
            recommendation = "keep"
        review_rows.append(
            {
                "window_start": window_start.isoformat(),
                "window_end": current_time.isoformat(),
                "query_label": label,
                "source_type": query.get("source_type", ""),
                "source_id": query.get("source_id", ""),
                "collection_interval_days": query.get("collection_interval_days", ""),
                "collected_runs": run_count,
                "returned_tweet_count": result_count,
                "average_results_per_run": round(average_results, 3),
                "runs_with_results": runs_with_results,
                "last_collected_at": last_collected_at,
                "recommendation": recommendation,
            }
        )
    return review_rows


def write_review(path: Path, rows: list[dict[str, Any]]) -> None:
    with atomic_open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(
            {fieldname: row.get(fieldname, "") for fieldname in REVIEW_FIELDS}
            for row in rows
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review X query collection effectiveness")
    parser.add_argument("--metrics-file", default=str(DEFAULT_METRICS_FILE))
    parser.add_argument("--query-file", default=str(DEFAULT_QUERY_FILE))
    parser.add_argument("--policy-file", default=str(DEFAULT_COLLECTION_POLICY))
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_FILE))
    parser.add_argument("--as-of", default=None, help="レビュー基準時刻 (ISO 8601)。省略時は現在時刻")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    queries, _ = load_queries(Path(args.query_file))
    policy = load_collection_policy(Path(args.policy_file))
    review_policy = policy.get("review") or {}
    as_of = parse_timestamp(args.as_of) if args.as_of else datetime.now(timezone.utc)
    if as_of is None:
        raise ValueError("--as-of はISO 8601形式で指定してください。")
    rows = build_review_rows(
        load_metrics(Path(args.metrics_file)),
        queries,
        as_of,
        window_days=_integer(review_policy.get("window_days")) or 30,
        minimum_collected_runs=_integer(review_policy.get("minimum_collected_runs")) or 3,
        low_effect_average_results=_number(review_policy.get("low_effect_average_results")) or 1.0,
    )
    output_path = Path(args.output_file)
    write_review(output_path, rows)
    candidates = sum(1 for row in rows if row["recommendation"] == "review")
    print(f"saved query effectiveness review: {output_path}")
    print(f"queries reviewed: {len(rows)}")
    print(f"low-effect candidates: {candidates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
