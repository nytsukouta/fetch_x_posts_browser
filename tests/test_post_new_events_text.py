import csv

from post_new_events_to_x import append_post_log, build_post_log_row, build_post_text, count_tweet_length


SITE_URL = "https://example.github.io/repo/"


def _row(**overrides):
    base = {
        "event_id": "event-彼方の空から",
        "event_name": "彼方の空から",
    }
    base.update(overrides)
    return base


def test_post_text_wraps_event_name_with_brackets_and_blank_lines():
    text = build_post_text(_row(), hashtag="石川演劇", header_label="新しい公演が追加されましたジョキャ！", site_url=SITE_URL)
    assert "『彼方の空から』" in text
    assert "新しい公演が追加されましたジョキャ！\n\n『彼方の空から』" in text
    assert "『彼方の空から』\n\n詳しくはこちら↓\n" in text
    assert text.rstrip().endswith("#石川演劇")


def test_post_text_within_max_length():
    text = build_post_text(_row(), hashtag="石川演劇", header_label="新しい公演が追加されましたジョキャ！", site_url=SITE_URL)
    assert count_tweet_length(text) <= 280


def test_post_text_truncates_long_event_name():
    long_name = "あ" * 400
    text = build_post_text(_row(event_name=long_name), hashtag="石川演劇", header_label="新しい公演が追加されましたジョキャ！", site_url=SITE_URL)
    assert count_tweet_length(text) <= 280
    assert "『" in text and "』" in text


def test_post_text_without_event_name():
    text = build_post_text(_row(event_name=""), hashtag="石川演劇", header_label="新しい公演が追加されましたジョキャ！", site_url=SITE_URL)
    # 公演名がない時は『』を出さない
    assert "『』" not in text
    assert "詳しくはこちら↓" in text


def test_post_text_skips_outer_brackets_when_name_already_quoted():
    # 既に 『』 を含むタイトルは外側にさらに括弧を付けない (二重括弧回避)
    text = build_post_text(
        _row(event_name="七尾東雲高校演劇科 第17回 定期公演 『ドン・キホーテは故郷に帰り』"),
        hashtag="石川演劇",
        header_label="新しい公演が追加されましたジョキャ！",
        site_url=SITE_URL,
    )
    assert "『七尾東雲高校演劇科" not in text
    assert "ドン・キホーテは故郷に帰り』" in text


def test_post_text_skips_outer_brackets_for_kakkokakko_style():
    text = build_post_text(
        _row(event_name="0ME presents 第二回定期公演 【誰が為に】"),
        hashtag="石川演劇",
        header_label="新しい公演が追加されましたジョキャ！",
        site_url=SITE_URL,
    )
    assert "『0ME" not in text
    assert "【誰が為に】" in text


def test_append_post_log_is_idempotent_and_keeps_utf8_bom(tmp_path):
    path = tmp_path / "posted_events.csv"
    row = _row(
        organization="劇団A",
        venue_name="会場A",
        start_date="2026-08-01",
        end_date="2026-08-01",
    )

    append_post_log(path, [build_post_log_row(row, "tweet-1")])
    append_post_log(path, [build_post_log_row(row, "tweet-2")])

    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["posted_tweet_id"] == "tweet-2"
