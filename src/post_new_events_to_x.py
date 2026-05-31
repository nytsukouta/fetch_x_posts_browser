from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from event_candidate_rules import is_schedule_eligible_event, parse_iso_date
from github_models_client import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = ROOT_DIR / ".env"
DEFAULT_EVENTS_CSV = ROOT_DIR / "data" / "output" / "event_cumulative.csv"
DEFAULT_POSTED_LOG_CSV = ROOT_DIR / "data" / "output" / "posted_events.csv"
CREATE_TWEET_URL = "https://api.x.com/2/tweets"
DEFAULT_HASHTAG = "石川演劇"
DEFAULT_HEADER = "新しい公演が追加されましたジョキャ！"
URL_LENGTH = 23
MAX_TWEET_LENGTH = 280


class DuplicateTweetContentError(RuntimeError):
    def __init__(self, details: str):
        super().__init__(details)
        self.details = details


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post newly discovered theater events to X")
    parser.add_argument("--events-csv", default=str(DEFAULT_EVENTS_CSV), help="event_cumulative.csv のパス")
    parser.add_argument("--posted-log-csv", default=str(DEFAULT_POSTED_LOG_CSV), help="投稿済みイベント記録CSVのパス")
    parser.add_argument("--dry-run", action="store_true", help="投稿せず、作成されるポスト本文だけを表示する")
    parser.add_argument("--limit", type=int, default=None, help="投稿または dry-run 表示する件数上限")
    parser.add_argument("--hashtag", default=DEFAULT_HASHTAG, help="末尾に付けるハッシュタグ。空文字で無効化")
    parser.add_argument("--header", default=DEFAULT_HEADER, help="投稿1行目の文言")
    parser.add_argument("--site-url", default="", help="公開中の schedule ページ URL。未指定時は GitHub Pages URL を推定")
    parser.add_argument(
        "--allowed-event-ids-csv",
        default="",
        help="投稿候補をこの CSV の event_id 集合だけに限定し重複を防ぐ (例: schedule_list.csv)。空ならフィルターしない",
    )
    return parser.parse_args()


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_posted_event_ids(path: Path) -> set[str]:
    posted_ids: set[str] = set()
    for row in load_csv_rows(path):
        event_id = (row.get("event_id") or "").strip()
        if event_id:
            posted_ids.add(event_id)
    return posted_ids


def load_allowed_event_ids(path: Path) -> set[str]:
    allowed_ids: set[str] = set()
    for row in load_csv_rows(path):
        event_id = (row.get("event_id") or "").strip()
        if event_id:
            allowed_ids.add(event_id)
    return allowed_ids


def is_current_or_upcoming_event(row: dict[str, str]) -> bool:
    effective_end_date = parse_iso_date(row.get("end_date") or "") or parse_iso_date(row.get("start_date") or "")
    if effective_end_date is None:
        return True
    return effective_end_date >= date.today()


def build_date_range(row: dict[str, str]) -> str:
    start_date = (row.get("start_date") or "").strip()
    end_date = (row.get("end_date") or "").strip()
    start_time = (row.get("start_time") or "").strip()
    if start_date and end_date and start_date != end_date:
        if start_time:
            return f"{start_date} - {end_date} {start_time}"
        return f"{start_date} - {end_date}"
    if start_date:
        if start_time:
            return f"{start_date} {start_time}"
        return start_date
    return ""


def choose_event_url(row: dict[str, str]) -> str:
    primary = (row.get("tweet_url") or "").strip()
    if primary:
        return primary
    for candidate in str(row.get("source_tweet_urls") or "").split(" | "):
        cleaned = candidate.strip()
        if cleaned:
            return cleaned
    return ""


def parse_github_remote(value: str) -> tuple[str, str] | None:
    cleaned = value.strip()
    https_match = re.match(r"https://github\.com/([^/]+)/([^/]+?)(?:\.git)?$", cleaned)
    if https_match:
        return https_match.group(1), https_match.group(2)

    ssh_match = re.match(r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$", cleaned)
    if ssh_match:
        return ssh_match.group(1), ssh_match.group(2)

    return None


def infer_public_site_url() -> str:
    git_config_path = ROOT_DIR / ".git" / "config"
    if not git_config_path.exists():
        return ""

    remote_url = ""
    in_origin = False
    for raw_line in git_config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("["):
            in_origin = line == '[remote "origin"]'
            continue
        if in_origin and line.startswith("url ="):
            remote_url = line.split("=", 1)[1].strip()
            break

    parsed_remote = parse_github_remote(remote_url)
    if parsed_remote is None:
        return ""

    owner, repo = parsed_remote
    if repo.lower() == f"{owner.lower()}.github.io":
        return f"https://{repo}/"
    return f"https://{owner}.github.io/{repo}/"


def resolve_public_site_url(explicit_value: str) -> str:
    candidate = explicit_value.strip()
    if not candidate:
        candidate = os.getenv("PUBLIC_SITE_URL", "").strip() or os.getenv("SITE_URL", "").strip()
    if not candidate:
        candidate = infer_public_site_url()
    return candidate


def build_schedule_page_url(site_url: str, row: dict[str, str]) -> str:
    base_url = site_url.strip()
    if not base_url:
        return choose_event_url(row)

    event_id = (row.get("event_id") or "").strip()
    if not event_id:
        return base_url

    parsed = parse.urlsplit(base_url)
    query_pairs = parse.parse_qsl(parsed.query, keep_blank_values=True)
    query_pairs = [(key, value) for key, value in query_pairs if key != "event"]
    query_pairs.append(("event", event_id))
    new_query = parse.urlencode(query_pairs)
    return parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment))


def count_tweet_length(text: str) -> int:
    total = 0
    position = 0
    for match in parse_re_urls(text):
        total += len(text[position:match.start()])
        total += URL_LENGTH
        position = match.end()
    total += len(text[position:])
    return total


def parse_re_urls(text: str):
    import re

    return re.finditer(r"https?://\S+", text)


def truncate_text(value: str, max_length: int) -> str:
    cleaned = value.strip()
    if max_length <= 0:
        return ""
    if count_tweet_length(cleaned) <= max_length:
        return cleaned
    if max_length == 1:
        return "…"
    trimmed = cleaned
    while trimmed and count_tweet_length(trimmed + "…") > max_length:
        trimmed = trimmed[:-1]
    return (trimmed + "…") if trimmed else cleaned[:max_length]


def build_post_text(row: dict[str, str], hashtag: str, header_label: str, site_url: str) -> str:
    header = (header_label or DEFAULT_HEADER).strip() or DEFAULT_HEADER
    event_url = build_schedule_page_url(site_url, row)
    lines = [header]
    if event_url:
        lines.extend(["詳しくはこちら", event_url])

    hashtag = hashtag.strip().lstrip("#")
    if hashtag:
        lines.append(f"#{hashtag}")

    text = "\n".join(lines)
    if count_tweet_length(text) <= MAX_TWEET_LENGTH:
        return text

    fixed_lines = [header]
    if hashtag:
        fixed_lines.append(f"#{hashtag}")
    return "\n".join(fixed_lines)


def sort_key(row: dict[str, str]) -> tuple[date, str, str]:
    start_date = parse_iso_date(row.get("start_date") or "") or date.max
    created_at = (row.get("created_at") or "").strip()
    event_id = (row.get("event_id") or "").strip()
    return start_date, created_at, event_id


def select_candidate_rows(rows: list[dict[str, str]], posted_ids: set[str], limit: int | None) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for row in rows:
        event_id = (row.get("event_id") or "").strip()
        if not event_id or event_id in posted_ids:
            continue
        if not is_current_or_upcoming_event(row):
            continue
        if not is_schedule_eligible_event(row):
            continue
        candidates.append(row)

    candidates.sort(key=sort_key)
    if limit is not None:
        candidates = candidates[:limit]
    return candidates


def get_required_env(name: str, *fallback_names: str) -> str:
    for key in (name, *fallback_names):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""


def percent_encode(value: str) -> str:
    return parse.quote(value, safe="~-._")


def build_oauth1_header(consumer_key: str, consumer_secret: str, access_token: str, access_token_secret: str, method: str, url: str) -> str:
    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }

    encoded_items = [(percent_encode(key), percent_encode(value)) for key, value in oauth_params.items()]
    encoded_items.sort()
    normalized = "&".join(f"{key}={value}" for key, value in encoded_items)
    base_string = "&".join([
        method.upper(),
        percent_encode(url),
        percent_encode(normalized),
    ])
    signing_key = f"{percent_encode(consumer_secret)}&{percent_encode(access_token_secret)}"
    signature = base64.b64encode(
        hmac.new(signing_key.encode("utf-8"), base_string.encode("utf-8"), hashlib.sha1).digest()
    ).decode("ascii")
    oauth_params["oauth_signature"] = signature

    header_parts = ", ".join(
        f'{percent_encode(key)}="{percent_encode(value)}"' for key, value in sorted(oauth_params.items())
    )
    return f"OAuth {header_parts}"


def is_duplicate_content_response(details: str) -> bool:
    normalized = str(details or "").lower()
    return "duplicate content" in normalized


def post_tweet(text: str) -> str:
    consumer_key = get_required_env("X_API_KEY", "X_CONSUMER_KEY")
    consumer_secret = get_required_env("X_API_SECRET", "X_CONSUMER_SECRET")
    access_token = get_required_env("X_ACCESS_TOKEN")
    access_token_secret = get_required_env("X_ACCESS_TOKEN_SECRET")

    missing = [
        name
        for name, value in [
            ("X_API_KEY", consumer_key),
            ("X_API_SECRET", consumer_secret),
            ("X_ACCESS_TOKEN", access_token),
            ("X_ACCESS_TOKEN_SECRET", access_token_secret),
        ]
        if not value
    ]
    if missing:
        raise RuntimeError(f"投稿に必要な環境変数が不足しています: {', '.join(missing)}")

    payload = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    api_request = request.Request(
        CREATE_TWEET_URL,
        data=payload,
        headers={
            "Authorization": build_oauth1_header(
                consumer_key,
                consumer_secret,
                access_token,
                access_token_secret,
                "POST",
                CREATE_TWEET_URL,
            ),
            "Content-Type": "application/json",
            "User-Agent": "hokuriku-theater-poster",
        },
        method="POST",
    )

    try:
        with request.urlopen(api_request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        if exc.code == 403 and is_duplicate_content_response(details):
            raise DuplicateTweetContentError(details) from exc
        raise RuntimeError(f"X post API error {exc.code}: {details}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"X post API へ接続できません: {exc}") from exc

    tweet_id = str(payload.get("data", {}).get("id") or "").strip()
    if not tweet_id:
        raise RuntimeError(f"X post API の応答から tweet id を取得できませんでした: {payload}")
    return tweet_id


def append_post_log(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "event_id",
        "event_name",
        "organization",
        "venue_name",
        "performance_schedule",
        "posted_at",
        "posted_tweet_id",
        "source_tweet_url",
    ]
    file_exists = path.exists()
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def run_dry(candidates: list[dict[str, str]], hashtag: str, header_label: str, site_url: str) -> int:
    if not candidates:
        print("dry-run: 投稿対象の新規公演はありません")
        return 0
    for index, row in enumerate(candidates, start=1):
        text = build_post_text(row, hashtag, header_label, site_url)
        print(f"dry-run {index}/{len(candidates)}: {(row.get('event_id') or '').strip()}")
        print(text)
        if index != len(candidates):
            print("-" * 40)
    print(f"dry-run candidates: {len(candidates)}")
    return 0


def main() -> int:
    args = parse_args()
    load_dotenv(DEFAULT_ENV_FILE)

    event_rows = load_csv_rows(Path(args.events_csv))
    posted_ids = load_posted_event_ids(Path(args.posted_log_csv))
    allowed_ids = load_allowed_event_ids(Path(args.allowed_event_ids_csv)) if args.allowed_event_ids_csv else None
    if allowed_ids is not None:
        before = len(event_rows)
        event_rows = [row for row in event_rows if (row.get("event_id") or "").strip() in allowed_ids]
        print(f"allowed-event-ids filter: {before} -> {len(event_rows)} rows")
    candidates = select_candidate_rows(event_rows, posted_ids, args.limit)
    site_url = resolve_public_site_url(args.site_url)

    if args.dry_run:
        return run_dry(candidates, args.hashtag, args.header, site_url)

    if not candidates:
        print("投稿対象の新規公演はありません")
        return 0

    posted_rows: list[dict[str, str]] = []
    posted_count = 0
    duplicate_count = 0
    for index, row in enumerate(candidates, start=1):
        event_id = (row.get("event_id") or "").strip()
        text = build_post_text(row, args.hashtag, args.header, site_url)
        print(f"posting {index}/{len(candidates)}: {event_id}")
        tweet_id = ""
        try:
            tweet_id = post_tweet(text)
            posted_count += 1
        except DuplicateTweetContentError as exc:
            duplicate_count += 1
            print(f"skipping duplicate content: {event_id}")
        posted_rows.append(
            {
                "event_id": event_id,
                "event_name": (row.get("event_name") or "").strip(),
                "organization": (row.get("organization") or "").strip(),
                "venue_name": (row.get("normalized_venue_name") or row.get("venue_name") or "").strip(),
                "performance_schedule": build_date_range(row),
                "posted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "posted_tweet_id": tweet_id,
                "source_tweet_url": choose_event_url(row),
            }
        )

    append_post_log(Path(args.posted_log_csv), posted_rows)
    print(f"posted events: {posted_count}")
    print(f"duplicate content skipped: {duplicate_count}")
    print(f"logged events: {len(posted_rows)}")
    print(f"posted log: {args.posted_log_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())