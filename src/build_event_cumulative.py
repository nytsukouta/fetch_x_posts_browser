"""filtered_cumulative CSV からイベント単位の累積 CSV を組み立てる CLI。

純粋ロジックは event_cumulative_core.py、LLM 二次統合は event_cumulative_llm.py に分離。
ここでは I/O と CLI のみを扱う。
"""
from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
from typing import Any

from atomic_io import atomic_open

# 後方互換: 既存の import 元 (tests など) のため core を再エクスポート
from event_cumulative_core import (  # noqa: F401
    MERGE_FIELDS,
    NON_ALNUM_RE,
    TITLE_SIMILARITY_THRESHOLD,
    VENUE_GROUP_ALIASES,
    bool_to_csv,
    build_event_key,
    build_event_records,
    build_preview_group_key,
    build_similarity_clusters,
    choose_canonical_name,
    choose_group_posting_recommendation,
    choose_value,
    compact_text,
    is_preview_subsumed,
    merge_date_range,
    merge_event_group,
    normalize_venue_group_key,
    parse_bool,
    parse_created_at_date,
    parse_iso_date,
    preview_record_priority,
    recommendation_rank,
    renumber_records,
    row_quality,
    secondary_group_key,
    slugify,
    suppress_preview_like_records,
    title_similarity,
    titles_are_similar,
)
from event_cumulative_llm import (  # noqa: F401
    DEFAULT_MODEL,
    SECONDARY_DEDUPE_SYSTEM_PROMPT,
    build_dedupe_prompt,
    call_dedupe_model,
    extract_json_content,
    secondary_dedupe,
)


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_CSV = ROOT_DIR / "data" / "output" / "structured_events_filtered_cumulative.csv"
DEFAULT_OUTPUT_CSV = ROOT_DIR / "data" / "output" / "event_cumulative.csv"

OUTPUT_FIELDS = [
    "event_id",
    "event_key",
    "tweet_url",
    "created_at",
    "author_name",
    "author_username",
    "event_name",
    "normalized_event_name",
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
    "is_event_announcement",
    "is_impression_or_review",
    "is_past_event_reference",
    "has_actionable_schedule_info",
    "requires_link_or_image_context",
    "posting_recommendation",
    "posting_reason",
    "confidence",
    "reasoning",
    "source_text",
    "source_tweet_count",
    "source_tweet_urls",
    "source_author_usernames",
    "first_seen_created_at",
    "last_seen_created_at",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build event-level cumulative records from filtered cumulative tweet records")
    parser.add_argument("--input-csv", default=str(DEFAULT_INPUT_CSV), help="filtered cumulative CSV のパス")
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV), help="イベント累積CSVの保存先")
    parser.add_argument("--model", default=os.getenv("GITHUB_MODELS_MODEL", DEFAULT_MODEL), help="二次統合で使う GitHub Models のモデルID")
    return parser.parse_args()


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(records: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_open(output_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(records)


def main() -> int:
    args = parse_args()
    rows = load_rows(Path(args.input_csv))
    records = build_event_records(rows)
    records = secondary_dedupe(records, args.model)
    write_csv(records, Path(args.output_csv))

    print(f"saved event cumulative: {args.output_csv}")
    print(f"rows: {len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
