import extract_events_github_models as extractor


def test_system_prompt_excludes_booking_dates_from_event_dates() -> None:
    assert "予約開始日時" in extractor.SYSTEM_PROMPT
    assert "それらしか分からない場合は null" in extractor.SYSTEM_PROMPT
    assert "「ご予約開始」などの表現に付随する日時を公演日時として扱わない" in extractor.SYSTEM_PROMPT
