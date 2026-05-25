from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from x_tweet_context import (
    COMMON_EXPANSIONS,
    COMMON_MEDIA_FIELDS,
    COMMON_TWEET_FIELDS,
    COMMON_USER_FIELDS,
    build_context_maps,
    build_tweet_url,
    extract_enriched_fields,
)


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_QUERY_FILE = ROOT_DIR / "config" / "priority_queries.json"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "data" / "output"
DEFAULT_ENV_FILE = ROOT_DIR / ".env"
SEARCH_URL = "https://api.x.com/2/tweets/search/recent"


def load_dotenv(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def load_queries(query_file: Path) -> tuple[list[dict[str, str]], int]:
    payload = json.loads(query_file.read_text(encoding="utf-8"))
    queries = payload.get("queries", [])
    if not queries:
        raise ValueError("priority_queries.json に queries がありません。")

    max_results = int(payload.get("max_results_per_query", 10))
    return queries, max_results


def fetch_recent_tweets(bearer_token: str, query: str, max_results: int) -> dict[str, Any]:
    params = {
        "query": query,
        "max_results": str(max(10, min(max_results, 100))),
        "tweet.fields": COMMON_TWEET_FIELDS,
        "expansions": COMMON_EXPANSIONS,
        "user.fields": COMMON_USER_FIELDS,
        "media.fields": COMMON_MEDIA_FIELDS,
    }
    url = f"{SEARCH_URL}?{parse.urlencode(params)}"
    api_request = request.Request(
        url,
        headers={
            "Authorization": f"Bearer {bearer_token}",
            "User-Agent": "hokuriku-theater-collector",
        },
        method="GET",
    )

    try:
        with request.urlopen(api_request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"X API error {exc.code}: {details}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"X API へ接続できません: {exc}") from exc


def flatten_rows(query_label: str, query_text: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    users_by_id, tweets_by_id, media_by_key = build_context_maps(payload)

    rows: list[dict[str, Any]] = []
    collected_at = datetime.now(timezone.utc).isoformat()

    for tweet in payload.get("data", []):
        user = users_by_id.get(tweet.get("author_id", ""), {})
        enriched = extract_enriched_fields(tweet, users_by_id, tweets_by_id, media_by_key)
        rows.append(
            {
                "query_label": query_label,
                "query": query_text,
                "tweet_id": tweet.get("id", ""),
                "tweet_url": build_tweet_url(user.get("username", ""), tweet.get("id", "")),
                "created_at": tweet.get("created_at", ""),
                "text": enriched["text"],
                "lang": tweet.get("lang", ""),
                "author_name": user.get("name", ""),
                "author_username": user.get("username", ""),
                "author_location": user.get("location", ""),
                "media_image_urls": enriched["media_image_urls"],
                "quoted_tweet_url": enriched["quoted_tweet_url"],
                "quoted_text": enriched["quoted_text"],
                "quoted_author_name": enriched["quoted_author_name"],
                "quoted_author_username": enriched["quoted_author_username"],
                "quoted_media_image_urls": enriched["quoted_media_image_urls"],
                "retweet_count": tweet.get("public_metrics", {}).get("retweet_count", 0),
                "reply_count": tweet.get("public_metrics", {}).get("reply_count", 0),
                "like_count": tweet.get("public_metrics", {}).get("like_count", 0),
                "quote_count": tweet.get("public_metrics", {}).get("quote_count", 0),
                "collected_at": collected_at,
            }
        )

    return rows
def write_csv(rows: list[dict[str, Any]], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"x_recent_search_{timestamp}.csv"
    fieldnames = [
        "query_label",
        "query",
        "tweet_id",
        "tweet_url",
        "created_at",
        "text",
        "lang",
        "author_name",
        "author_username",
        "author_location",
        "media_image_urls",
        "quoted_tweet_url",
        "quoted_text",
        "quoted_author_name",
        "quoted_author_username",
        "quoted_media_image_urls",
        "retweet_count",
        "reply_count",
        "like_count",
        "quote_count",
        "collected_at",
    ]

    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="X recent search for Ishikawa theater queries")
    parser.add_argument(
        "--query-file",
        default=str(DEFAULT_QUERY_FILE),
        help="priority_queries.json のパス",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="CSV 保存先ディレクトリ",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=None,
        help="各クエリの取得件数。未指定なら設定ファイルの値を使用",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(DEFAULT_ENV_FILE)

    bearer_token = os.getenv("X_BEARER_TOKEN", "").strip()
    if not bearer_token:
        print("X_BEARER_TOKEN が見つかりません。.env を作成してください。", file=sys.stderr)
        return 1

    query_file = Path(args.query_file)
    output_dir = Path(args.output_dir)
    queries, configured_max_results = load_queries(query_file)
    max_results = args.max_results or configured_max_results

    all_rows: list[dict[str, Any]] = []
    try:
        for item in queries:
            query_label = item["label"]
            query_text = item["query"]
            print(f"searching: {query_label}")
            payload = fetch_recent_tweets(bearer_token, query_text, max_results)
            all_rows.extend(flatten_rows(query_label, query_text, payload))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        if "client-not-enrolled" in str(exc):
            print(
                "Developer Portal で App が Project に紐づいているか、対象 Project に API Access が付与されているか確認してください。",
                file=sys.stderr,
            )
        return 1

    if not all_rows:
        print("投稿を取得できませんでした。クエリ条件かAPI権限を確認してください。")
        return 0

    output_path = write_csv(all_rows, output_dir)
    print(f"saved: {output_path}")
    print(f"rows: {len(all_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
