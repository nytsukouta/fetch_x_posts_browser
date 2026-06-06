from pathlib import Path

from fetch_x_posts import (
    load_since_id_state,
    newest_tweet_id,
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
