import extract_events_github_models as extractor

from extract_events_github_models import (
    build_user_content,
    build_user_prompt,
    should_skip_images,
)


def _row_with_freepaper() -> dict[str, str]:
    return {
        "text": "📣6月号発行しました！ 石川県の演劇情報フリーペーパー 「観劇しまっし！」",
        "quoted_text": "",
        "media_image_urls": "https://pbs.twimg.com/media/foo.jpg",
        "quoted_media_image_urls": "",
    }


def _row_with_normal_announcement() -> dict[str, str]:
    return {
        "text": "次回公演のお知らせ",
        "quoted_text": "",
        "media_image_urls": "https://pbs.twimg.com/media/bar.jpg",
        "quoted_media_image_urls": "",
    }


def test_should_skip_images_for_freepaper_text() -> None:
    assert should_skip_images(_row_with_freepaper()) is True


def test_should_skip_images_for_quoted_freepaper() -> None:
    row = {"text": "応援してます", "quoted_text": "観劇しまっし！7月号"}
    assert should_skip_images(row) is True


def test_should_not_skip_images_for_normal_row() -> None:
    assert should_skip_images(_row_with_normal_announcement()) is False


def test_build_user_content_drops_images_for_freepaper() -> None:
    content = build_user_content(_row_with_freepaper(), include_images=True)
    assert all(part.get("type") != "image_url" for part in content)


def test_build_user_prompt_drops_image_urls_for_freepaper() -> None:
    prompt = build_user_prompt(_row_with_freepaper(), include_images=True)
    assert '"media_image_urls": []' in prompt
    assert "foo.jpg" not in prompt


def test_build_user_content_keeps_images_for_normal_row() -> None:
    content = build_user_content(_row_with_normal_announcement(), include_images=True)
    assert any(part.get("type") == "image_url" for part in content)


def test_extract_row_skips_site_update_notification_before_model(monkeypatch) -> None:
    row = {
        "tweet_url": "https://x.com/jokya_official/status/2089840433610588356",
        "created_at": "2026-08-18T22:22:41.000Z",
        "author_name": "Coffeeジョキャニーニャ【公式】",
        "author_username": "jokya_official",
        "text": "新しい公演が追加されましたジョキャ！ 『花札伝綺』 詳しくはこちら↓ https://t.co/ebFdXpfkUK",
    }

    def fail_if_called(*args, **kwargs):
        raise AssertionError("site update notifications must not call the model")

    monkeypatch.setattr(extractor, "call_github_models", fail_if_called)

    record = extractor.extract_row(
        1,
        1,
        row,
        "api-key",
        "",
        "v1",
        "model",
        False,
        {},
        {},
    )

    assert record["is_noise"] is True
    assert record["noise_reason"] == "site_update_notification"
