from build_priority_queries_from_masters import build_queries


def test_build_queries_assigns_collection_intervals_by_source_and_official_x() -> None:
    queries = build_queries(
        [
            {
                "organization_id": "org-daily",
                "organization_name": "劇団 日次",
                "official_x": "https://x.com/daily_theater",
            },
            {
                "organization_id": "org-low",
                "organization_name": "劇団 低頻度",
                "official_x": "",
            },
        ],
        [
            {
                "venue_id": "venue-official",
                "venue_name": "公式劇場",
                "official_x": "https://x.com/official_venue",
            },
            {
                "venue_id": "venue-slow",
                "venue_name": "低頻度劇場",
                "official_x": "",
            },
        ],
    )

    by_source_id = {query["source_id"]: query for query in queries}

    assert by_source_id["org-daily"]["collection_interval_days"] == 1
    assert by_source_id["org-daily"]["collection_tier"] == "daily"
    assert by_source_id["org-low"]["collection_interval_days"] == 3
    assert by_source_id["venue-official"]["collection_interval_days"] == 3
    assert "venue-slow" not in by_source_id


def test_build_queries_only_uses_official_x_for_venues() -> None:
    queries = build_queries(
        [],
        [
            {
                "venue_id": "venue-official",
                "venue_name": "公式劇場",
                "official_x": "https://x.com/official_venue",
            },
            {
                "venue_id": "venue-name-only",
                "venue_name": "会場名検索劇場",
                "official_x": "",
                "query_include": "1",
            },
        ],
    )

    assert [query["source_id"] for query in queries] == ["venue-official"]
    assert queries[0]["query"].startswith("from:official_venue ")


def test_build_queries_applies_collection_policy_override() -> None:
    queries = build_queries(
        [{"organization_id": "org-paused", "organization_name": "劇団 休止", "official_x": "@paused"}],
        [],
        {
            "organization": {"official_x_interval_days": 1},
            "overrides": {"org-paused": {"interval_days": 6}},
        },
    )

    assert queries[0]["collection_interval_days"] == 6
    assert queries[0]["collection_tier"] == "low_frequency"