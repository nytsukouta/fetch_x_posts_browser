from event_candidate_rules import (
    build_date_range,
    has_postable_event_details,
    is_schedule_eligible_event,
    parse_iso_date,
    source_text_mentions_exact_start_date,
)


def make_row(**overrides):
    base = {
        "event_name": "公演A",
        "organization": "劇団テスト",
        "venue_name": "石川県立音楽堂",
        "normalized_venue_name": "石川県立音楽堂",
        "start_date": "2026-06-10",
        "end_date": "2026-06-10",
        "start_time": "19:00",
        "category": "公演",
        "source_text": "2026年6月10日 19:00開演 劇団テスト公演A",
        "is_event_announcement": "True",
        "has_actionable_schedule_info": "True",
        "posting_recommendation": "post",
    }
    base.update(overrides)
    return base


class TestParseIsoDate:
    def test_valid(self):
        assert parse_iso_date("2026-06-10").isoformat() == "2026-06-10"

    def test_blank(self):
        assert parse_iso_date("") is None
        assert parse_iso_date(None) is None  # type: ignore[arg-type]

    def test_invalid(self):
        assert parse_iso_date("2026/06/10") is None


class TestBuildDateRange:
    def test_single_day_with_time(self):
        row = make_row(end_date="2026-06-10")
        assert build_date_range(row) == "2026-06-10 19:00"

    def test_multi_day(self):
        row = make_row(start_date="2026-06-10", end_date="2026-06-12", start_time="")
        assert build_date_range(row) == "2026-06-10 - 2026-06-12"

    def test_no_date(self):
        row = make_row(start_date="", end_date="", start_time="")
        assert build_date_range(row) == ""


class TestSourceTextMentionsExactStartDate:
    def test_matches_iso(self):
        row = make_row(source_text="開催日: 2026-06-10", start_date="2026-06-10")
        assert source_text_mentions_exact_start_date(row) is True

    def test_matches_japanese(self):
        row = make_row(source_text="6月10日に開演します", start_date="2026-06-10")
        assert source_text_mentions_exact_start_date(row) is True

    def test_no_match(self):
        row = make_row(source_text="近日公開", start_date="2026-06-10")
        assert source_text_mentions_exact_start_date(row) is False

    def test_no_date(self):
        row = make_row(source_text="6月10日", start_date="")
        assert source_text_mentions_exact_start_date(row) is False


class TestHasPostableEventDetails:
    def test_recommendation_post_wins(self):
        row = make_row(posting_recommendation="post", is_event_announcement="False")
        assert has_postable_event_details(row) is True

    def test_recommendation_skip_loses(self):
        row = make_row(posting_recommendation="skip")
        assert has_postable_event_details(row) is False

    def test_announcement_false_blocks(self):
        row = make_row(posting_recommendation="", is_event_announcement="False")
        assert has_postable_event_details(row) is False

    def test_actionable_schedule_allows(self):
        row = make_row(posting_recommendation="", has_actionable_schedule_info="True")
        assert has_postable_event_details(row) is True

    def test_fallback_requires_exact_date_and_venue_or_org(self):
        row = make_row(
            posting_recommendation="",
            has_actionable_schedule_info="False",
            source_text="6月10日 劇団テスト公演",
            organization="劇団テスト",
            venue_name="",
            normalized_venue_name="",
        )
        assert has_postable_event_details(row) is True

    def test_fallback_without_exact_date_rejected(self):
        row = make_row(
            posting_recommendation="",
            has_actionable_schedule_info="False",
            source_text="近日公演します",
        )
        assert has_postable_event_details(row) is False


class TestIsScheduleEligibleEvent:
    def test_basic_pass(self):
        assert is_schedule_eligible_event(make_row()) is True

    def test_excluded_venue(self):
        row = make_row(venue_name="金沢おぐら座", normalized_venue_name="金沢おぐら座")
        assert is_schedule_eligible_event(row) is False

    def test_non_theater_keyword_without_signal(self):
        row = make_row(
            event_name="アイドルライブ",
            organization="アイドルグループ",
            category="その他",
            source_text="ライブ コンサート 6月10日",
        )
        assert is_schedule_eligible_event(row) is False

    def test_non_theater_keyword_but_theater_signal(self):
        row = make_row(
            event_name="演劇 × ライブ",
            organization="劇団テスト",
            category="公演",
            source_text="演劇ライブ公演 6月10日",
        )
        assert is_schedule_eligible_event(row) is True

    def test_missing_date_rejected(self):
        row = make_row(start_date="", end_date="", start_time="")
        assert is_schedule_eligible_event(row) is False

    def test_missing_venue_and_org_rejected(self):
        row = make_row(venue_name="", normalized_venue_name="", organization="")
        assert is_schedule_eligible_event(row) is False
