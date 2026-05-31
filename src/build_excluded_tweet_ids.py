"""累積CSVの is_noise=true から excluded_tweet_ids.csv を派生する。"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from atomic_io import atomic_open


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_CSV = ROOT_DIR / "data" / "output" / "structured_events_cumulative.csv"
DEFAULT_OUTPUT_CSV = ROOT_DIR / "data" / "output" / "excluded_tweet_ids.csv"

TWEET_ID_FROM_URL_RE = re.compile(r"/status/(\d+)")


def extract_tweet_id_from_url(tweet_url: str) -> str:
    match = TWEET_ID_FROM_URL_RE.search(tweet_url)
    return match.group(1) if match else ""


def collect_noise_rows(input_csv: Path) -> list[dict[str, str]]:
    if not input_csv.exists():
        return []
    rows: list[dict[str, str]] = []
    with input_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if str(row.get("is_noise") or "").lower() != "true":
                continue
            tweet_id = str(row.get("tweet_id") or "").strip()
            tweet_url = str(row.get("tweet_url") or "").strip()
            if not tweet_id and tweet_url:
                tweet_id = extract_tweet_id_from_url(tweet_url)
            if not tweet_id and not tweet_url:
                continue
            rows.append(
                {
                    "tweet_id": tweet_id,
                    "tweet_url": tweet_url,
                    "noise_reason": str(row.get("reasoning") or "").strip()[:200],
                    "first_seen_created_at": str(row.get("created_at") or "").strip(),
                }
            )
    return rows


def merge_existing(existing_csv: Path, new_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    keyed: dict[str, dict[str, str]] = {}
    if existing_csv.exists():
        with existing_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                key = (row.get("tweet_url") or row.get("tweet_id") or "").strip()
                if not key:
                    continue
                if not (row.get("tweet_id") or "").strip() and (row.get("tweet_url") or "").strip():
                    row["tweet_id"] = extract_tweet_id_from_url(row["tweet_url"])
                keyed[key] = row
    for row in new_rows:
        key = (row.get("tweet_url") or row.get("tweet_id") or "").strip()
        if not key:
            continue
        # 既存があれば first_seen_created_at を残しつつ noise_reason を更新
        if key in keyed:
            kept = keyed[key]
            kept["noise_reason"] = row.get("noise_reason") or kept.get("noise_reason", "")
        else:
            keyed[key] = row
    return sorted(keyed.values(), key=lambda r: r.get("first_seen_created_at") or "", reverse=True)


def write_csv(rows: list[dict[str, str]], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["tweet_id", "tweet_url", "noise_reason", "first_seen_created_at"]
    with atomic_open(output_csv, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="累積CSVのノイズ tweet を excluded_tweet_ids.csv に集約する")
    parser.add_argument("--input-csv", default=str(DEFAULT_INPUT_CSV), help="累積 structured CSV のパス")
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV), help="出力 CSV のパス")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    new_rows = collect_noise_rows(Path(args.input_csv))
    merged = merge_existing(Path(args.output_csv), new_rows)
    write_csv(merged, Path(args.output_csv))
    print(f"saved: {args.output_csv}")
    print(f"rows: {len(merged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
