from build_event_cumulative import (
    apply_organization_canonicalization,
    attach_event_updates,
    build_event_key,
    build_organization_lookup,
    canonicalize_organization,
    compact_text,
    event_update_match_score,
    is_event_update_record,
    is_placeholder_title,
    merge_date_range,
    merge_placeholder_records,
    merge_records_by_event_id,
    normalize_handle,
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


class TestNormalizeHandle:
    def test_strips_at(self):
        assert normalize_handle("@FooBar") == "foobar"

    def test_extracts_from_url(self):
        assert normalize_handle("https://x.com/FooBar/status/123") == "foobar"

    def test_blank(self):
        assert normalize_handle("") == ""


class TestCanonicalizeOrganization:
    def setup_method(self):
        master = [
            {
                "organization_name": "表現集団tone!tone!tone!",
                "official_x": "https://x.com/tonetoneto25403",
            },
            {
                "organization_name": "劇団さくらんぼ",
                "official_x": "",
            },
        ]
        self.name_lookup, self.handle_lookup = build_organization_lookup(master)

    def test_exact_name_match(self):
        row = {"organization": "表現集団tone!tone!tone!", "author_username": ""}
        assert canonicalize_organization(row, self.name_lookup, self.handle_lookup) == "表現集団tone!tone!tone!"

    def test_handle_overrides_when_prefix_matches(self):
        # LLM が「表現集団トントントン」と書いても、ハンドルが一致し先頭3文字が共通なので正規化
        row = {"organization": "表現集団トントントン", "author_username": "tonetoneto25403"}
        assert canonicalize_organization(row, self.name_lookup, self.handle_lookup) == "表現集団tone!tone!tone!"

    def test_handle_does_not_override_unrelated_org(self):
        # 案内アカウントから別団体の告知を流したケースを想定: 先頭が一致しないので変更しない
        row = {"organization": "全く違う団体名", "author_username": "tonetoneto25403"}
        assert canonicalize_organization(row, self.name_lookup, self.handle_lookup) == "全く違う団体名"

    def test_handle_does_not_fill_blank_org(self):
        # 投稿者ハンドルがマスターにあっても organization が空なら埋めない。
        # 紹介・告知投稿で投稿者そのものが主催者として循環アトリビューションされてしまう
        # ため、空のままにする。
        row = {"organization": "", "author_username": "tonetoneto25403"}
        assert canonicalize_organization(row, self.name_lookup, self.handle_lookup) == ""

    def test_apply_returns_new_rows_with_canonical_org(self):
        rows = [
            {"organization": "表現集団トントントン", "author_username": "tonetoneto25403"},
            {"organization": "全く違う団体名", "author_username": "tonetoneto25403"},
        ]
        canonicalized = apply_organization_canonicalization(rows, self.name_lookup, self.handle_lookup)
        assert canonicalized[0]["organization"] == "表現集団tone!tone!tone!"
        assert canonicalized[1]["organization"] == "全く違う団体名"


class TestMergeRecordsByEventId:
    def test_single_records_pass_through(self):
        records = [
            {"event_id": "event-foo", "normalized_event_name": "Foo"},
            {"event_id": "event-bar", "normalized_event_name": "Bar"},
        ]
        merged = merge_records_by_event_id(records)
        ids = [record["event_id"] for record in merged]
        assert ids == ["event-foo", "event-bar"]

    def test_merges_records_sharing_event_id(self):
        records = [
            {
                "event_id": "event-赤鬼",
                "normalized_event_name": "赤鬼",
                "event_name": "さよならキャンプ第5回公演「赤鬼」",
                "organization": "さよならキャンプ",
                "venue_name": "福井県産業情報センター",
                "normalized_venue_name": "福井県産業情報センター",
                "start_date": "2026-09-05",
                "end_date": "2026-09-06",
                "category": "公演",
                "confidence": "0.9",
                "source_tweet_urls": "https://x.com/sayonara_camp/status/1",
                "tweet_url": "https://x.com/sayonara_camp/status/1",
                "source_text": "x" * 200,
            },
            {
                "event_id": "event-赤鬼",
                "normalized_event_name": "赤鬼",
                "event_name": "赤鬼",
                "organization": "さよならキャンプ",
                "venue_name": "福井県産業情報センターマルチホール",
                "normalized_venue_name": "福井県産業情報センターマルチホール",
                "start_date": "2026-09-05",
                "end_date": "2026-09-06",
                "category": "公演",
                "confidence": "0.7",
                "source_tweet_urls": "https://x.com/sayonara_camp/status/2",
                "tweet_url": "https://x.com/sayonara_camp/status/2",
                "source_text": "y" * 100,
            },
        ]
        merged = merge_records_by_event_id(records)
        assert len(merged) == 1
        assert merged[0]["event_id"] == "event-赤鬼"
        # 引用 tweet URL がまとまる
        assert merged[0]["source_tweet_count"] == 2
        assert "status/1" in merged[0]["source_tweet_urls"]
        assert "status/2" in merged[0]["source_tweet_urls"]
        # 長い方の event_name を採用
        assert merged[0]["event_name"] == "さよならキャンプ第5回公演「赤鬼」"

    def test_keeps_records_without_event_id(self):
        records = [
            {"event_id": "", "normalized_event_name": "Foo"},
            {"event_id": "event-foo", "normalized_event_name": "Foo"},
        ]
        merged = merge_records_by_event_id(records)
        assert len(merged) == 2


class TestEventUpdateAttachment:
    def _record(self, **overrides):
        base = {
            "event_id": "event-街",
            "event_name": "街 くずれた日常 2026",
            "normalized_event_name": "街 くずれた日常 2026",
            "organization": "劇団新人類人猿",
            "venue_name": "金沢市民芸術村PIT2ドラマ工房",
            "normalized_venue_name": "金沢市民芸術村PIT2ドラマ工房",
            "start_date": "2026-07-11",
            "end_date": "2026-07-12",
            "start_time": "14:00",
            "category": "公演",
            "confidence": "0.9",
            "source_tweet_urls": "https://x.com/rui_jin_en/status/1",
            "source_author_usernames": "rui_jin_en",
            "tweet_url": "https://x.com/rui_jin_en/status/1",
            "author_username": "rui_jin_en",
            "source_text": "街 くずれた日常 2026 公演のお知らせ",
            "created_at": "2026-07-01T10:00:00Z",
        }
        base.update(overrides)
        return base

    def test_official_seat_update_attaches_to_existing_event(self):
        event = self._record()
        update = self._record(
            event_id="event-劇団新人類人猿",
            event_name="",
            normalized_event_name="",
            venue_name="",
            normalized_venue_name="",
            source_tweet_urls="https://x.com/rui_jin_en/status/2075106425639256295",
            tweet_url="https://x.com/rui_jin_en/status/2075106425639256295",
            source_text="11日14時公演、座席追加で8席の余裕があります。",
            created_at="2026-07-10T01:00:00Z",
        )
        merged = attach_event_updates([event, update], {"rui_jin_en": "劇団新人類人猿"})
        assert len(merged) == 1
        assert merged[0]["event_id"] == "event-街"
        assert merged[0]["event_name"] == "街 くずれた日常 2026"
        assert merged[0]["venue_name"] == "金沢市民芸術村PIT2ドラマ工房"
        assert "2075106425639256295" in merged[0]["source_tweet_urls"]
        assert merged[0]["source_tweet_count"] == 2

    def test_same_org_and_date_without_update_signal_does_not_attach(self):
        event = self._record()
        candidate = self._record(
            event_id="event-new",
            event_name="",
            normalized_event_name="",
            source_text="劇団新人類人猿の公演情報です。",
        )
        merged = attach_event_updates([event, candidate], {"rui_jin_en": "劇団新人類人猿"})
        assert len(merged) == 2

    def test_different_date_or_venue_does_not_attach(self):
        event = self._record()
        different_date = self._record(
            event_id="event-other-date",
            event_name="",
            normalized_event_name="",
            start_date="2026-08-01",
            end_date="2026-08-01",
            source_text="残席あります。",
        )
        different_venue = self._record(
            event_id="event-other-venue",
            event_name="",
            normalized_event_name="",
            venue_name="別会場",
            normalized_venue_name="別会場",
            source_text="残席あります。",
        )
        merged = attach_event_updates([event, different_date, different_venue], {"rui_jin_en": "劇団新人類人猿"})
        assert len(merged) == 3
        assert event_update_match_score(different_date, event, {"rui_jin_en": "劇団新人類人猿"}) < 8
        assert event_update_match_score(different_venue, event, {"rui_jin_en": "劇団新人類人猿"}) < 8

    def test_update_detection_requires_keyword(self):
        assert is_event_update_record(self._record(source_text="11日14時公演です。")) is False
        assert is_event_update_record(self._record(source_text="11日14時、残席あります。")) is True


class TestIsPlaceholderTitle:
    def test_date_placeholder(self):
        assert is_placeholder_title("6/27(土)の定期公演") is True
        assert is_placeholder_title("6/27（土）の定期公演") is True
        assert is_placeholder_title("6月27日の本公演") is True
        assert is_placeholder_title("6/27 の公演") is True

    def test_generic_placeholder(self):
        assert is_placeholder_title("次回公演") is True
        assert is_placeholder_title("次回の定期公演") is True
        assert is_placeholder_title("今月の本公演") is True
        assert is_placeholder_title("公演") is True

    def test_named_title_not_placeholder(self):
        assert is_placeholder_title("箱庭レコニング") is False
        assert is_placeholder_title("0ME presents 第三回定期公演 箱庭レコニング") is False
        assert is_placeholder_title("赤鬼") is False

    def test_blank(self):
        assert is_placeholder_title("") is False
        assert is_placeholder_title(None) is False


class TestMergePlaceholderRecords:
    def _record(self, **overrides):
        base = {
            "event_id": "",
            "normalized_event_name": "",
            "event_name": "",
            "organization": "",
            "venue_name": "",
            "normalized_venue_name": "",
            "start_date": "",
            "end_date": "",
            "category": "公演",
            "confidence": "0.8",
            "source_tweet_urls": "",
            "tweet_url": "",
            "source_text": "",
        }
        base.update(overrides)
        return base

    def test_merges_placeholder_into_named_same_day(self):
        placeholder = self._record(
            event_id="event-定期公演",
            normalized_event_name="6/27(土)の定期公演",
            event_name="6/27(土)の定期公演",
            organization="0ME｜ゼロミー",
            start_date="2026-06-27",
            end_date="2026-06-27",
            confidence="0.6",
            tweet_url="https://x.com/zeroMEOFFICIAL/status/1",
            source_tweet_urls="https://x.com/zeroMEOFFICIAL/status/1",
        )
        named = self._record(
            event_id="event-箱庭レコニング",
            normalized_event_name="箱庭レコニング",
            event_name="0ME presents 第三回定期公演 箱庭レコニング",
            organization="0ME｜ゼロミー",
            venue_name="香林坊TRILL",
            normalized_venue_name="香林坊TRILL",
            start_date="2026-06-27",
            end_date="2026-06-27",
            confidence="0.95",
            tweet_url="https://x.com/zeroMEOFFICIAL/status/2",
            source_tweet_urls="https://x.com/zeroMEOFFICIAL/status/2",
            source_text="x" * 200,
        )
        merged = merge_placeholder_records([placeholder, named])
        assert len(merged) == 1
        assert merged[0]["event_id"] == "event-箱庭レコニング"
        assert merged[0]["normalized_event_name"] == "箱庭レコニング"
        assert merged[0]["source_tweet_count"] == 2

    def test_does_not_merge_when_different_organization(self):
        placeholder = self._record(
            event_id="event-定期公演",
            normalized_event_name="6/27(土)の定期公演",
            organization="A団",
            start_date="2026-06-27",
        )
        named = self._record(
            event_id="event-別公演",
            normalized_event_name="別公演",
            organization="B団",
            venue_name="香林坊TRILL",
            normalized_venue_name="香林坊TRILL",
            start_date="2026-06-27",
        )
        merged = merge_placeholder_records([placeholder, named])
        assert len(merged) == 2

    def test_does_not_merge_when_dates_disjoint(self):
        placeholder = self._record(
            event_id="event-定期公演",
            normalized_event_name="6/27(土)の定期公演",
            organization="0ME",
            start_date="2026-06-27",
        )
        named = self._record(
            event_id="event-箱庭",
            normalized_event_name="箱庭レコニング",
            organization="0ME",
            start_date="2026-07-10",
        )
        merged = merge_placeholder_records([placeholder, named])
        assert len(merged) == 2

    def test_does_not_merge_when_venues_differ(self):
        placeholder = self._record(
            event_id="event-定期公演",
            normalized_event_name="6/27(土)の定期公演",
            organization="0ME",
            venue_name="A会場",
            normalized_venue_name="A会場",
            start_date="2026-06-27",
        )
        named = self._record(
            event_id="event-箱庭",
            normalized_event_name="箱庭レコニング",
            organization="0ME",
            venue_name="B会場",
            normalized_venue_name="B会場",
            start_date="2026-06-27",
        )
        merged = merge_placeholder_records([placeholder, named])
        assert len(merged) == 2

    def test_passthrough_when_no_placeholder(self):
        records = [
            self._record(event_id="event-foo", normalized_event_name="Foo公演", organization="A", start_date="2026-06-27"),
            self._record(event_id="event-bar", normalized_event_name="Bar公演", organization="A", start_date="2026-06-27"),
        ]
        merged = merge_placeholder_records(records)
        assert len(merged) == 2

