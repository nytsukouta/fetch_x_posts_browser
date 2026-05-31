from build_event_cumulative import (
    build_event_key,
    compact_text,
    merge_date_range,
    normalize_venue_group_key,
    parse_created_at_date,
    parse_iso_date,
    titles_are_similar,
)


class TestCompactText:
    def test_strips_symbols_and_case(self):
        assert compact_text("  Hello, World!  ") == "helloworld"

    def test_keeps_japanese(self):
        assert compact_text("劇団テスト  公演") == "劇団テスト公演"


class TestNormalizeVenueGroupKey:
    def test_alias_collapsed(self):
        assert normalize_venue_group_key("團十郎芸術劇場うらら 大ホール") == compact_text("小松市團十郎芸術劇場うらら")

    def test_unknown_passthrough(self):
        assert normalize_venue_group_key("石川県立音楽堂") == compact_text("石川県立音楽堂")


class TestTitlesAreSimilar:
    def test_identical(self):
        assert titles_are_similar("テスト公演", "テスト公演") is True

    def test_subtitle_difference(self):
        assert titles_are_similar("LIVE TOUR 2026", "LIVE TOUR 2026 DANCE ON AIR") is True

    def test_different(self):
        assert titles_are_similar("公演A", "全然違う作品") is False

    def test_blank(self):
        assert titles_are_similar("", "公演A") is False


class TestBuildEventKey:
    def test_includes_event_name_when_present(self):
        key = build_event_key(
            {
                "normalized_event_name": "公演A",
                "organization": "劇団",
                "normalized_venue_name": "会場",
                "start_date": "2026-06-10",
                "end_date": "2026-06-10",
                "start_time": "19:00",
            }
        )
        assert "公演a" in key
        assert "2026-06-10" in key

    def test_falls_back_to_org_when_no_name(self):
        key = build_event_key(
            {
                "organization": "劇団",
                "normalized_venue_name": "会場",
                "start_date": "2026-06-10",
                "category": "公演",
            }
        )
        assert key.startswith("劇団") or "劇団" in key


class TestMergeDateRange:
    def test_picks_min_max(self):
        records = [
            {"start_date": "2026-06-10", "end_date": "2026-06-10"},
            {"start_date": "2026-06-09", "end_date": "2026-06-12"},
            {"start_date": "", "end_date": ""},
        ]
        assert merge_date_range(records) == ("2026-06-09", "2026-06-12")

    def test_fills_missing_end(self):
        assert merge_date_range([{"start_date": "2026-06-10", "end_date": ""}]) == ("2026-06-10", "2026-06-10")

    def test_empty(self):
        assert merge_date_range([{"start_date": "", "end_date": ""}]) == ("", "")


class TestParseCreatedAtDate:
    def test_iso_with_time(self):
        assert parse_created_at_date("2026-06-10T12:34:56Z").isoformat() == "2026-06-10"

    def test_short(self):
        assert parse_created_at_date("2026-06") is None

    def test_invalid(self):
        assert parse_iso_date("not a date") is None
