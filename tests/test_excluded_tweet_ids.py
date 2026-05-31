import csv

import pytest

import build_excluded_tweet_ids
import fetch_x_posts


def _write_csv(path, rows, fieldnames):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_collect_noise_rows_filters_is_noise(tmp_path):
    input_csv = tmp_path / "in.csv"
    _write_csv(
        input_csv,
        [
            {"tweet_id": "1", "tweet_url": "https://x.com/u/status/1", "is_noise": "True", "reasoning": "spam"},
            {"tweet_id": "2", "tweet_url": "https://x.com/u/status/2", "is_noise": "False", "reasoning": ""},
            {"tweet_id": "3", "tweet_url": "", "is_noise": "TRUE", "reasoning": "ng"},
            {"tweet_id": "", "tweet_url": "", "is_noise": "true", "reasoning": "no id"},
        ],
        ["tweet_id", "tweet_url", "is_noise", "reasoning"],
    )
    rows = build_excluded_tweet_ids.collect_noise_rows(input_csv)
    assert {r["tweet_id"] for r in rows} == {"1", "3"}


def test_merge_existing_preserves_keys_and_dedupes(tmp_path):
    existing = tmp_path / "existing.csv"
    _write_csv(
        existing,
        [
            {
                "tweet_id": "1",
                "tweet_url": "https://x.com/u/status/1",
                "noise_reason": "old reason",
                "first_seen_created_at": "2026-01-01T00:00:00Z",
            }
        ],
        ["tweet_id", "tweet_url", "noise_reason", "first_seen_created_at"],
    )
    merged = build_excluded_tweet_ids.merge_existing(
        existing,
        [
            {
                "tweet_id": "1",
                "tweet_url": "https://x.com/u/status/1",
                "noise_reason": "new reason",
                "first_seen_created_at": "2026-05-01T00:00:00Z",
            },
            {
                "tweet_id": "2",
                "tweet_url": "https://x.com/u/status/2",
                "noise_reason": "another",
                "first_seen_created_at": "2026-03-01T00:00:00Z",
            },
        ],
    )
    assert len(merged) == 2
    by_id = {r.get("tweet_id"): r for r in merged}
    # existing first_seen は保持、noise_reason は更新
    assert by_id["1"]["first_seen_created_at"] == "2026-01-01T00:00:00Z"
    assert by_id["1"]["noise_reason"] == "new reason"


def test_filter_excluded_rows_by_id_or_url():
    rows = [
        {"tweet_id": "1", "tweet_url": "https://x.com/u/status/1"},
        {"tweet_id": "2", "tweet_url": "https://x.com/u/status/2"},
        {"tweet_id": "3", "tweet_url": "https://x.com/u/status/3"},
    ]
    kept, skipped = fetch_x_posts.filter_excluded_rows(rows, {"1", "https://x.com/u/status/3"})
    assert skipped == 2
    assert [r["tweet_id"] for r in kept] == ["2"]


def test_filter_excluded_rows_empty_set_passthrough():
    rows = [{"tweet_id": "1", "tweet_url": "https://x.com/u/status/1"}]
    kept, skipped = fetch_x_posts.filter_excluded_rows(rows, set())
    assert skipped == 0
    assert kept == rows


def test_load_excluded_tweet_keys_missing_file(tmp_path):
    assert fetch_x_posts.load_excluded_tweet_keys(tmp_path / "missing.csv") == set()
