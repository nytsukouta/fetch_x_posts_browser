import csv
import json

import pytest

from maintenance_server import ApiError, MaintenanceService


def _write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def service(tmp_path):
    fields = [
        "event_id", "event_key", "tweet_url", "source_tweet_urls", "event_name",
        "normalized_event_name", "organization", "venue_name", "normalized_venue_name",
        "location", "normalized_location", "start_date", "end_date", "start_time",
        "category", "source_text", "posting_recommendation", "is_event_announcement",
        "has_actionable_schedule_info",
    ]
    row = {field: "" for field in fields}
    row.update(
        {
            "event_id": "event-a",
            "event_name": "抽出名",
            "normalized_event_name": "抽出名",
            "organization": "劇団A",
            "venue_name": "会場A",
            "normalized_venue_name": "会場A",
            "start_date": "2026-08-01",
            "end_date": "2026-08-01",
            "category": "公演",
            "source_text": "劇団A 演劇公演 8月1日",
            "posting_recommendation": "post",
            "is_event_announcement": "true",
            "has_actionable_schedule_info": "true",
            "tweet_url": "https://x.com/test/status/1",
            "source_tweet_urls": "https://x.com/test/status/1",
        }
    )
    _write_csv(tmp_path / "data/output/event_cumulative_base.csv", fields, [row])
    _write_csv(tmp_path / "data/output/event_cumulative.csv", fields, [row])
    _write_csv(tmp_path / "data/output/organization_master.csv", ["organization_name_normalized"], [])
    _write_csv(tmp_path / "data/output/venue_master.csv", ["venue_name_normalized"], [])
    overrides = tmp_path / "config/manual_event_overrides.json"
    overrides.parent.mkdir(parents=True)
    overrides.write_text('{"version":1,"overrides":[]}\n', encoding="utf-8")
    return MaintenanceService(tmp_path)


def test_list_save_and_delete_override(service):
    listing = service.events({})
    assert listing["count"] == 1
    revision = listing["revision"]

    saved = service.save_override(
        "event-a",
        {"revision": revision, "set": {"event_name": "正式名"}, "note": "確認済み"},
    )
    assert saved["event"]["effective"]["event_name"] == "正式名"
    assert saved["event"]["schedule"]["event_name"] == "正式名"

    new_revision = saved["event"]["revision"]
    deleted = service.delete_override("event-a", {"revision": new_revision})
    assert deleted["event"]["effective"]["event_name"] == "抽出名"


def test_stale_revision_is_rejected(service):
    with pytest.raises(ApiError) as exc_info:
        service.save_override("event-a", {"revision": "stale", "set": {"event_name": "x"}})
    assert exc_info.value.status == 409


def test_unknown_event_is_404(service):
    with pytest.raises(ApiError) as exc_info:
        service.event("event-missing")
    assert exc_info.value.status == 404
