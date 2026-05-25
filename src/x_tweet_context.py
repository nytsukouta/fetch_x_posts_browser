from __future__ import annotations

from typing import Any


COMMON_TWEET_FIELDS = "created_at,lang,public_metrics,attachments,referenced_tweets"
COMMON_EXPANSIONS = "author_id,attachments.media_keys,referenced_tweets.id,referenced_tweets.id.author_id,referenced_tweets.id.attachments.media_keys"
COMMON_USER_FIELDS = "name,username,location"
COMMON_MEDIA_FIELDS = "type,url,preview_image_url"


def normalize_text(text: str) -> str:
    return " ".join(str(text or "").split())


def build_tweet_url(username: str, tweet_id: str) -> str:
    if not username or not tweet_id:
        return ""
    return f"https://x.com/{username}/status/{tweet_id}"


def build_context_maps(payload: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    includes = payload.get("includes", {})
    users_by_id = {
        user["id"]: user
        for user in includes.get("users", [])
        if isinstance(user, dict) and "id" in user
    }
    tweets_by_id = {
        tweet["id"]: tweet
        for tweet in includes.get("tweets", [])
        if isinstance(tweet, dict) and "id" in tweet
    }
    media_by_key = {
        media["media_key"]: media
        for media in includes.get("media", [])
        if isinstance(media, dict) and "media_key" in media
    }
    return users_by_id, tweets_by_id, media_by_key


def media_image_url(media: dict[str, Any]) -> str:
    media_type = str(media.get("type") or "").strip().lower()
    if media_type == "photo":
        return str(media.get("url") or "").strip()
    if media_type in {"video", "animated_gif"}:
        return str(media.get("preview_image_url") or "").strip()
    return ""


def collect_image_urls(tweet: dict[str, Any], media_by_key: dict[str, dict[str, Any]]) -> list[str]:
    attachments = tweet.get("attachments") or {}
    media_keys = attachments.get("media_keys") or []
    urls: list[str] = []
    for media_key in media_keys:
        media = media_by_key.get(str(media_key), {})
        image_url = media_image_url(media)
        if image_url and image_url not in urls:
            urls.append(image_url)
    return urls


def resolve_quoted_tweet(tweet: dict[str, Any], tweets_by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for reference in tweet.get("referenced_tweets", []) or []:
        if str(reference.get("type") or "") != "quoted":
            continue
        quoted_tweet = tweets_by_id.get(str(reference.get("id") or ""))
        if quoted_tweet:
            return quoted_tweet
    return None


def extract_enriched_fields(
    tweet: dict[str, Any],
    users_by_id: dict[str, dict[str, Any]],
    tweets_by_id: dict[str, dict[str, Any]],
    media_by_key: dict[str, dict[str, Any]],
) -> dict[str, str]:
    quoted_tweet = resolve_quoted_tweet(tweet, tweets_by_id)
    quoted_user = users_by_id.get(str((quoted_tweet or {}).get("author_id") or ""), {}) if quoted_tweet else {}

    media_image_urls = collect_image_urls(tweet, media_by_key)
    quoted_media_image_urls = collect_image_urls(quoted_tweet or {}, media_by_key) if quoted_tweet else []

    return {
        "text": normalize_text(tweet.get("text", "")),
        "media_image_urls": " | ".join(media_image_urls),
        "quoted_tweet_url": build_tweet_url(str(quoted_user.get("username") or ""), str((quoted_tweet or {}).get("id") or "")),
        "quoted_text": normalize_text((quoted_tweet or {}).get("text", "")),
        "quoted_author_name": str(quoted_user.get("name") or ""),
        "quoted_author_username": str(quoted_user.get("username") or ""),
        "quoted_media_image_urls": " | ".join(quoted_media_image_urls),
    }