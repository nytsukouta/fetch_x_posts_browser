from build_schedule_list import build_schedule_rows, choose_reference_url


def _event(**overrides):
    row = {
        "event_id": "event-a",
        "event_name": "公演A",
        "organization": "劇団A",
        "venue_name": "会場A",
        "normalized_venue_name": "会場A",
        "normalized_location": "石川県金沢市 / 石川県",
        "start_date": "2026-08-01",
        "end_date": "2026-08-01",
        "start_time": "19:00",
        "category": "公演",
        "source_text": "劇団A 演劇公演 8月1日",
        "posting_recommendation": "post",
        "is_event_announcement": "true",
        "has_actionable_schedule_info": "true",
        "tweet_url": "https://x.com/test/status/1",
    }
    row.update(overrides)
    return row


def test_manual_reference_url_has_highest_priority():
    url, source = choose_reference_url(
        _event(manual_reference_url="https://example.com/event"),
        {"official_website": "https://example.com/org"},
        {"official_website": "https://example.com/venue"},
    )
    assert url == "https://example.com/event"
    assert source == "manual_reference_url"


def test_manual_excluded_is_not_in_schedule():
    rows = build_schedule_rows([_event(manual_publish_status="excluded")], {}, {})
    assert rows == []


def test_manual_published_is_in_schedule_without_auto_signal():
    event = _event(
        event_name="地域イベント",
        organization="主催者",
        category="その他",
        source_text="",
        posting_recommendation="skip",
        manual_publish_status="published",
    )
    rows = build_schedule_rows([event], {}, {})
    assert len(rows) == 1
