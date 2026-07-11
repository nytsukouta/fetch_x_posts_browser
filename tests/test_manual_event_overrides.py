import json

import pytest

from manual_event_overrides import (
    ManualOverrideError,
    apply_manual_event_overrides,
    delete_manual_event_override,
    empty_override_payload,
    load_manual_event_overrides,
    upsert_manual_event_override,
    write_manual_event_overrides,
)


def _override(event_id="event-a", **set_values):
    return {
        "target_event_id": event_id,
        "target_source_tweet_urls": ["https://x.com/test/status/1"],
        "set": set_values,
        "note": "公式情報で確認",
        "updated_at": "2026-07-11T10:00:00+09:00",
    }


def _record(event_id="event-a", **values):
    row = {
        "event_id": event_id,
        "event_name": "抽出名",
        "organization": "劇団A",
        "start_date": "2026-08-01",
        "tweet_url": "https://x.com/test/status/1",
        "source_tweet_urls": "https://x.com/test/status/1",
    }
    row.update(values)
    return row


def test_applies_only_specified_fields_and_keeps_event_id():
    records, stats = apply_manual_event_overrides([_record()], [_override(event_name="正式名")])
    assert records[0]["event_id"] == "event-a"
    assert records[0]["event_name"] == "正式名"
    assert records[0]["organization"] == "劇団A"
    assert stats == {"applied": 1, "orphan": [], "ambiguous": []}


def test_explicit_blank_clears_value():
    records, _ = apply_manual_event_overrides([_record(organization="劇団A")], [_override(organization="")])
    assert records[0]["organization"] == ""


def test_falls_back_to_source_tweet_url():
    records, stats = apply_manual_event_overrides([_record(event_id="event-new")], [_override(event_name="正式名")])
    assert records[0]["event_name"] == "正式名"
    assert stats["applied"] == 1


def test_orphan_and_ambiguous_are_not_applied():
    orphaned, orphan_stats = apply_manual_event_overrides([_record()], [_override("event-missing", event_name="x") | {"target_source_tweet_urls": []}])
    assert orphaned[0]["event_name"] == "抽出名"
    assert orphan_stats["orphan"] == ["event-missing"]

    rows = [_record("event-x"), _record("event-y")]
    ambiguous, ambiguous_stats = apply_manual_event_overrides(rows, [_override("event-missing", event_name="x")])
    assert all(row["event_name"] == "抽出名" for row in ambiguous)
    assert ambiguous_stats["ambiguous"] == ["event-missing"]


@pytest.mark.parametrize(
    "set_values",
    [
        {"unknown": "x"},
        {"start_date": "2026/08/01"},
        {"start_time": "25:00"},
        {"manual_reference_url": "javascript:alert(1)"},
        {"manual_publish_status": "maybe"},
        {"posting_recommendation": "publish"},
        {"is_event_announcement": "maybe"},
        {"start_date": "2026-08-02", "end_date": "2026-08-01"},
    ],
)
def test_rejects_invalid_override(set_values):
    with pytest.raises(ManualOverrideError):
        upsert_manual_event_override(empty_override_payload(), _override(**set_values))


def test_write_load_delete_roundtrip_uses_readable_japanese(tmp_path):
    path = tmp_path / "manual_event_overrides.json"
    payload = upsert_manual_event_override(empty_override_payload(), _override(event_name="正式な公演名"))
    write_manual_event_overrides(path, payload)
    text = path.read_text(encoding="utf-8")
    assert "正式な公演名" in text
    assert text.endswith("\n")
    assert load_manual_event_overrides(path) == payload
    assert delete_manual_event_override(payload, "event-a") == empty_override_payload()


def test_duplicate_target_id_is_rejected(tmp_path):
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps({"version": 1, "overrides": [_override(), _override()]}), encoding="utf-8")
    with pytest.raises(ManualOverrideError):
        load_manual_event_overrides(path)
