import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fetch_x_posts

from fetch_x_posts import (
    append_collection_metrics,
    is_query_due,
    load_since_id_state,
    load_collection_state,
    newest_tweet_id,
    save_collection_state,
    save_since_id_state,
)


def test_load_since_id_state_missing_returns_empty(tmp_path: Path) -> None:
    assert load_since_id_state(tmp_path / "missing.json") == {}


def test_save_and_load_since_id_state_roundtrip(tmp_path: Path) -> None:
    state_path = tmp_path / "state" / "ids.json"
    state = {"劇団 A 公式X": "1234567890", "劇団 B 公式X": "9876543210"}
    save_since_id_state(state_path, state)
    assert load_since_id_state(state_path) == state


def test_load_since_id_state_ignores_invalid_json(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("not-json", encoding="utf-8")
    assert load_since_id_state(bad_path) == {}


def test_load_since_id_state_ignores_non_dict(tmp_path: Path) -> None:
    bad_path = tmp_path / "list.json"
    bad_path.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_since_id_state(bad_path) == {}


def test_load_since_id_state_skips_empty_values(tmp_path: Path) -> None:
    path = tmp_path / "ids.json"
    path.write_text('{"a": "111", "b": ""}', encoding="utf-8")
    assert load_since_id_state(path) == {"a": "111"}


def test_main_retries_without_stale_since_id(tmp_path: Path, monkeypatch, capsys) -> None:
    query_file = tmp_path / "queries.json"
    query_file.write_text(
        json.dumps(
            {
                "max_results_per_query": 10,
                "queries": [{"label": "劇団 A", "query": "from:theater_a"}],
            }
        ),
        encoding="utf-8",
    )
    state_path = tmp_path / "since.json"
    save_since_id_state(state_path, {"劇団 A": "2084238304132952065"})
    calls: list[str | None] = []

    def fake_fetch_recent_tweets(*args, **kwargs):
        since_id = kwargs.get("since_id")
        calls.append(since_id)
        if since_id:
            raise RuntimeError(
                "X API error 400: {'message': \"'since_id' must be a tweet id created after 2026-08-04\"}"
            )
        return {"meta": {"newest_id": "2085000000000000000"}}

    monkeypatch.setenv("X_BEARER_TOKEN", "test-token")
    monkeypatch.setattr(fetch_x_posts, "fetch_recent_tweets", fake_fetch_recent_tweets)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fetch_x_posts.py",
            "--query-file",
            str(query_file),
            "--output-dir",
            str(tmp_path / "output"),
            "--state-file",
            str(state_path),
            "--collection-state-file",
            str(tmp_path / "collection_state.json"),
            "--metrics-file",
            str(tmp_path / "metrics.csv"),
            "--excluded-ids-csv",
            str(tmp_path / "excluded.csv"),
        ],
    )

    assert fetch_x_posts.main() == 0
    assert calls == ["2084238304132952065", None]
    assert load_since_id_state(state_path) == {"劇団 A": "2085000000000000000"}
    assert "stale since_id detected" in capsys.readouterr().out


def test_collection_state_roundtrip(tmp_path: Path) -> None:
    state_path = tmp_path / "state" / "collections.json"
    state = {"query A": "2026-08-08T00:00:00+00:00"}

    save_collection_state(state_path, state)

    assert load_collection_state(state_path) == state


def test_collection_state_accepts_object_values(tmp_path: Path) -> None:
    state_path = tmp_path / "collections.json"
    state_path.write_text(
        json.dumps({"query A": {"last_collected_at": "2026-08-08T00:00:00+00:00"}}),
        encoding="utf-8",
    )

    assert load_collection_state(state_path) == {"query A": "2026-08-08T00:00:00+00:00"}


def test_is_query_due_respects_collection_interval() -> None:
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)
    query = {"label": "query A", "collection_interval_days": 3}

    assert is_query_due(query, {"query A": (now - timedelta(days=2)).isoformat()}, now) is False
    assert is_query_due(query, {"query A": (now - timedelta(days=3)).isoformat()}, now) is True
    assert is_query_due(query, {}, now) is True


def test_append_collection_metrics_replaces_existing_file_atomically(tmp_path: Path) -> None:
    metrics_path = tmp_path / "query_collection_metrics.csv"
    append_collection_metrics(metrics_path, [{"query_label": "query A", "result_count": 2}])
    append_collection_metrics(metrics_path, [{"query_label": "query B", "result_count": 0}])

    with metrics_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert [(row["query_label"], row["result_count"]) for row in rows] == [("query A", "2"), ("query B", "0")]


def test_main_skips_query_before_interval_without_calling_api(tmp_path: Path, monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    query_file = tmp_path / "queries.json"
    query_file.write_text(
        json.dumps(
            {
                "max_results_per_query": 10,
                "queries": [
                    {
                        "label": "劇団 低頻度",
                        "query": "from:low_frequency",
                        "collection_interval_days": 3,
                        "collection_tier": "low_frequency",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    collection_state_path = tmp_path / "collection_state.json"
    save_collection_state(collection_state_path, {"劇団 低頻度": (now - timedelta(days=1)).isoformat()})
    output_dir = tmp_path / "output"
    metrics_path = tmp_path / "metrics.csv"

    def fail_if_called(*args, **kwargs):
        raise AssertionError("API must not be called before the collection interval elapses")

    monkeypatch.setenv("X_BEARER_TOKEN", "test-token")
    monkeypatch.setattr(fetch_x_posts, "fetch_recent_tweets", fail_if_called)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fetch_x_posts.py",
            "--query-file",
            str(query_file),
            "--output-dir",
            str(output_dir),
            "--state-file",
            str(tmp_path / "since.json"),
            "--collection-state-file",
            str(collection_state_path),
            "--metrics-file",
            str(metrics_path),
            "--excluded-ids-csv",
            str(tmp_path / "excluded.csv"),
        ],
    )

    assert fetch_x_posts.main() == 0
    assert list(output_dir.glob("x_recent_search_*.csv"))
    with metrics_path.open("r", encoding="utf-8-sig", newline="") as handle:
        metrics = list(csv.DictReader(handle))
    assert metrics[0]["status"] == "skipped"


def test_newest_tweet_id_prefers_meta_newest_id() -> None:
    payload = {"meta": {"newest_id": "555"}, "data": [{"id": "100"}, {"id": "200"}]}
    assert newest_tweet_id(payload) == "555"


def test_newest_tweet_id_falls_back_to_max_data_id() -> None:
    payload = {"data": [{"id": "100"}, {"id": "9999"}, {"id": "300"}]}
    assert newest_tweet_id(payload) == "9999"


def test_newest_tweet_id_handles_longer_id_as_newer() -> None:
    payload = {"data": [{"id": "999"}, {"id": "1000"}]}
    assert newest_tweet_id(payload) == "1000"


def test_newest_tweet_id_empty_payload() -> None:
    assert newest_tweet_id({}) == ""
    assert newest_tweet_id({"data": []}) == ""
