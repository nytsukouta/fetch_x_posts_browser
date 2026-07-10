import csv

from build_master_pages_data import build_organization_items, build_venue_items
from build_schedule_list import build_json_rows, write_csv


def test_schedule_json_rows_add_prefecture_without_changing_location():
    rows = [
        {
            "event_id": "event-test",
            "event_name": "テスト公演",
            "organization_id": "org-test",
            "organization_name": "テスト劇団",
            "venue_name": "テスト会場",
            "performance_schedule": "2026-08-01",
            "official_reference_url": "",
            "official_reference_type": "",
            "normalized_location": "石川県金沢市 / 石川県",
            "source_tweet_url": "https://x.com/example/status/1",
        }
    ]

    json_rows = build_json_rows(rows)

    assert json_rows[0]["prefecture"] == "石川県"
    assert json_rows[0]["normalized_location"] == "石川県金沢市 / 石川県"
    assert "prefecture" not in rows[0]


def test_schedule_csv_schema_does_not_gain_prefecture(tmp_path):
    rows = [
        {
            "event_id": "event-test",
            "event_name": "テスト公演",
            "organization_id": "org-test",
            "organization_name": "テスト劇団",
            "venue_name": "テスト会場",
            "performance_schedule": "2026-08-01",
            "official_reference_url": "",
            "official_reference_type": "",
            "normalized_location": "石川県金沢市",
            "source_tweet_url": "",
        }
    ]
    output = tmp_path / "schedule.csv"

    write_csv(rows, output)

    with output.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        assert "prefecture" not in (reader.fieldnames or [])
        assert list(reader)[0]["normalized_location"] == "石川県金沢市"


def test_master_items_add_prefecture_and_keep_original_location():
    organization = build_organization_items(
        [{"organization_id": "org-test", "organization_name": "劇団", "location": "北陸地方"}]
    )[0]
    venue = build_venue_items(
        [{"venue_id": "venue-test", "venue_name": "劇場", "location": "〒930-0000 富山県富山市"}]
    )[0]

    assert organization["location"] == "北陸地方"
    assert organization["prefecture"] == ""
    assert venue["location"] == "〒930-0000 富山県富山市"
    assert venue["prefecture"] == "富山県"
