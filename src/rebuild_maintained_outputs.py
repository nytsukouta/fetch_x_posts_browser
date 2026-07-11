"""補正前イベントCSVへ手動補正を適用し、ローカル公開プレビューを再生成する。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_event_cumulative import (
    DEFAULT_BASE_OUTPUT_CSV,
    DEFAULT_MANUAL_OVERRIDES_JSON,
    DEFAULT_OUTPUT_CSV,
    load_rows,
    write_csv,
)
from build_schedule_list import (
    DEFAULT_ORGANIZATION_MASTER_CSV,
    DEFAULT_OUTPUT_CSV as DEFAULT_SCHEDULE_CSV,
    DEFAULT_OUTPUT_JSON as DEFAULT_SCHEDULE_JSON,
    DEFAULT_VENUE_MASTER_CSV,
    build_schedule_rows,
    index_master,
    load_csv_rows,
    write_csv as write_schedule_csv,
    write_json as write_schedule_json,
)
from manual_event_overrides import apply_manual_event_overrides, load_manual_event_overrides


def rebuild_maintained_outputs(
    *,
    base_csv: Path = DEFAULT_BASE_OUTPUT_CSV,
    overrides_json: Path = DEFAULT_MANUAL_OVERRIDES_JSON,
    effective_csv: Path = DEFAULT_OUTPUT_CSV,
    organization_master_csv: Path = DEFAULT_ORGANIZATION_MASTER_CSV,
    venue_master_csv: Path = DEFAULT_VENUE_MASTER_CSV,
    schedule_csv: Path = DEFAULT_SCHEDULE_CSV,
    schedule_json: Path = DEFAULT_SCHEDULE_JSON,
) -> dict[str, Any]:
    if not base_csv.exists():
        raise FileNotFoundError("手動補正前のイベントデータがありません。先にGitHubから同期してください。")

    base_records = load_rows(base_csv)
    override_payload = load_manual_event_overrides(overrides_json)
    effective_records, stats = apply_manual_event_overrides(base_records, override_payload["overrides"])
    write_csv(effective_records, effective_csv)

    organization_rows = load_csv_rows(organization_master_csv)
    venue_rows = load_csv_rows(venue_master_csv)
    organization_index = index_master(organization_rows, "organization_name_normalized")
    venue_index = index_master(venue_rows, "venue_name_normalized")
    schedule_rows = build_schedule_rows(effective_records, organization_index, venue_index)
    write_schedule_csv(schedule_rows, schedule_csv)
    write_schedule_json(schedule_rows, schedule_json)

    return {
        **stats,
        "base_count": len(base_records),
        "effective_count": len(effective_records),
        "schedule_count": len(schedule_rows),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="手動補正を適用してローカルの公演一覧を再生成する")
    parser.add_argument("--base-csv", default=str(DEFAULT_BASE_OUTPUT_CSV))
    parser.add_argument("--overrides-json", default=str(DEFAULT_MANUAL_OVERRIDES_JSON))
    parser.add_argument("--effective-csv", default=str(DEFAULT_OUTPUT_CSV))
    parser.add_argument("--schedule-csv", default=str(DEFAULT_SCHEDULE_CSV))
    parser.add_argument("--schedule-json", default=str(DEFAULT_SCHEDULE_JSON))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = rebuild_maintained_outputs(
        base_csv=Path(args.base_csv),
        overrides_json=Path(args.overrides_json),
        effective_csv=Path(args.effective_csv),
        schedule_csv=Path(args.schedule_csv),
        schedule_json=Path(args.schedule_json),
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
