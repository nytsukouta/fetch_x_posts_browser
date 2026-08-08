from datetime import datetime, timezone

from review_query_effectiveness import build_review_rows


def test_build_review_rows_marks_low_effect_queries_for_review() -> None:
    rows = build_review_rows(
        [
            {
                "collected_at": "2026-08-01T00:00:00+00:00",
                "query_label": "劇団 A 公式X",
                "status": "collected",
                "result_count": "0",
            },
            {
                "collected_at": "2026-08-02T00:00:00+00:00",
                "query_label": "劇団 A 公式X",
                "status": "collected",
                "result_count": "1",
            },
            {
                "collected_at": "2026-08-03T00:00:00+00:00",
                "query_label": "劇団 A 公式X",
                "status": "collected",
                "result_count": "0",
            },
        ],
        [{"label": "劇団 A 公式X", "source_type": "organization", "collection_interval_days": 1}],
        datetime(2026, 8, 8, tzinfo=timezone.utc),
        minimum_collected_runs=3,
        low_effect_average_results=1.0,
    )

    assert rows[0]["collected_runs"] == 3
    assert rows[0]["returned_tweet_count"] == 1
    assert rows[0]["recommendation"] == "review"


def test_build_review_rows_keeps_new_queries_in_observe_state() -> None:
    rows = build_review_rows(
        [],
        [{"label": "新規クエリ", "collection_interval_days": 3}],
        datetime(2026, 8, 8, tzinfo=timezone.utc),
    )

    assert rows[0]["collected_runs"] == 0
    assert rows[0]["recommendation"] == "observe"