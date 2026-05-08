from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from playwright.sync_api import Browser, BrowserContext, Error, Page, TimeoutError, sync_playwright


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_QUERY_FILE = ROOT_DIR / "config" / "priority_queries.json"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "data" / "output"
DEFAULT_ENV_FILE = ROOT_DIR / ".env"
DEFAULT_STATE_FILE = ROOT_DIR / "data" / "session" / "x_storage_state.json"
DEFAULT_BROWSER_CHANNEL = os.getenv("PLAYWRIGHT_BROWSER_CHANNEL", "msedge")
STATUS_PATH_RE = re.compile(r"^/(?P<username>[^/]+)/status/(?P<tweet_id>\d+)$")


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="X browser-based recent search for Ishikawa theater queries")
    parser.add_argument("--query-file", default=str(DEFAULT_QUERY_FILE), help="priority_queries.json のパス")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="CSV 保存先ディレクトリ")
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_FILE), help="ログイン状態を保存する JSON ファイル")
    parser.add_argument("--max-results", type=int, default=None, help="各クエリの取得件数")
    parser.add_argument("--headless", action="store_true", help="ヘッドレスで実行する")
    parser.add_argument("--browser-channel", default=DEFAULT_BROWSER_CHANNEL, help="Playwright で使う実ブラウザチャンネル。既定は msedge")
    parser.add_argument("--manual-login-timeout", type=int, default=600, help="手動ログイン待機秒数。既定は 600 秒")
    return parser.parse_args()


def get_env_value(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def ensure_logged_in(context: BrowserContext, state_file: Path, manual_login_timeout_seconds: int) -> Page:
    page = context.new_page()
    page.goto("https://x.com/home", wait_until="domcontentloaded")

    if is_logged_in(page):
        save_storage_state(context, state_file)
        return page

    wait_for_manual_login(page, state_file, context, manual_login_timeout_seconds)
    return page


def wait_for_manual_login(page: Page, state_file: Path, context: BrowserContext, manual_login_timeout_seconds: int) -> None:
    print("X のログイン画面を開きました。ブラウザ上で手動ログインしてください。ログイン完了後は自動で続行します。")
    page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded")
    deadline_ms = max(60, manual_login_timeout_seconds) * 1000
    start = datetime.now(timezone.utc)

    while (datetime.now(timezone.utc) - start).total_seconds() * 1000 < deadline_ms:
        active_page = get_active_page(context, page)
        if active_page is None:
            raise RuntimeError("ログイン待機中にブラウザページが閉じられました。再実行してもう一度ログインしてください。")

        if is_logged_in(active_page):
            save_storage_state(context, state_file)
            return
        active_url = get_page_url(active_page)
        if active_url.startswith("https://x.com/home") or "/search?" in active_url:
            save_storage_state(context, state_file)
            return
        time.sleep(2)

    raise RuntimeError("手動ログイン待機がタイムアウトしました。ログイン完了後に再実行してください。")


def get_active_page(context: BrowserContext, fallback_page: Page) -> Page | None:
    for current_page in context.pages:
        try:
            if not current_page.is_closed():
                return current_page
        except Error:
            continue
    try:
        if not fallback_page.is_closed():
            return fallback_page
    except Error:
        return None
    return None


def is_logged_in(page: Page) -> bool:
    try:
        return page.locator('a[href="/home"], a[href$="/compose/post"], button[data-testid="SideNav_AccountSwitcher_Button"]').count() > 0
    except Error:
        return False


def get_page_url(page: Page) -> str:
    try:
        return page.url
    except Error:
        return ""


def save_storage_state(context: BrowserContext, state_file: Path) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(state_file))


def open_context(playwright: Any, state_file: Path, headless: bool, browser_channel: str) -> tuple[Browser, BrowserContext]:
    launch_options: dict[str, Any] = {
        "headless": headless,
        "args": ["--disable-blink-features=AutomationControlled"],
        "ignore_default_args": ["--enable-automation"],
    }
    if browser_channel:
        launch_options["channel"] = browser_channel

    browser = playwright.chromium.launch(**launch_options)
    if state_file.exists():
        return browser, browser.new_context(storage_state=str(state_file), locale="ja-JP", timezone_id="Asia/Tokyo")
    return browser, browser.new_context(locale="ja-JP", timezone_id="Asia/Tokyo")


def build_search_url(query: str) -> str:
    return f"https://x.com/search?q={quote_plus(query)}&src=typed_query&f=live"


def collect_query_rows(page: Page, query_label: str, query_text: str, limit: int) -> list[dict[str, Any]]:
    page.goto(build_search_url(query_text), wait_until="domcontentloaded")
    wait_for_search_results(page)

    rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    idle_rounds = 0

    while len(rows) < limit and idle_rounds < 4:
        articles = page.locator("article")
        article_count = articles.count()
        before = len(rows)

        for index in range(article_count):
            article = articles.nth(index)
            row = extract_tweet_row(article, query_label, query_text)
            if not row:
                continue
            if row["tweet_url"] in seen_urls:
                continue
            seen_urls.add(row["tweet_url"])
            rows.append(row)
            if len(rows) >= limit:
                break

        if len(rows) == before:
            idle_rounds += 1
        else:
            idle_rounds = 0

        page.mouse.wheel(0, 5000)
        page.wait_for_timeout(1500)

    return rows[:limit]


def wait_for_search_results(page: Page) -> None:
    article_locator = page.locator("article")
    try:
        article_locator.first.wait_for(timeout=15000)
        return
    except TimeoutError:
        retry_button = page.locator('button:has-text("やりなおす"), button:has-text("Try again")')
        if retry_button.count() > 0:
            retry_button.first.click()
            page.wait_for_timeout(3000)
            article_locator.first.wait_for(timeout=15000)
            return
    page.wait_for_timeout(3000)
    article_locator.first.wait_for(timeout=15000)


def extract_tweet_row(article: Any, query_label: str, query_text: str) -> dict[str, Any] | None:
    status_link = find_status_url(article)
    if not status_link:
        return None

    match = STATUS_PATH_RE.match(status_link)
    if not match:
        return None

    tweet_url = f"https://x.com{status_link}"
    username = match.group("username")
    tweet_id = match.group("tweet_id")
    text = extract_text(article)
    created_at = ""
    if article.locator("time").count() > 0:
        created_at = article.locator("time").first.get_attribute("datetime") or ""

    author_name = extract_author_name(article, username)
    collected_at = datetime.now(timezone.utc).isoformat()

    return {
        "query_label": query_label,
        "query": query_text,
        "tweet_id": tweet_id,
        "tweet_url": tweet_url,
        "created_at": created_at,
        "text": text,
        "author_name": author_name,
        "author_username": username,
        "collected_at": collected_at,
    }


def find_status_url(article: Any) -> str:
    links = article.locator('a[href*="/status/"]')
    for index in range(links.count()):
        href = links.nth(index).get_attribute("href") or ""
        status_path = normalize_status_path(href)
        if status_path:
            return status_path
    return ""


def normalize_status_path(href: str) -> str:
    if not href:
        return ""
    candidate = href.split("?", 1)[0]
    parts = candidate.split("/")
    if len(parts) < 4:
        return ""
    if parts[2] != "status":
        return ""
    return f"/{parts[1]}/status/{parts[3]}"


def extract_text(article: Any) -> str:
    if article.locator('[data-testid="tweetText"]').count() > 0:
        return normalize_text(article.locator('[data-testid="tweetText"]').first.inner_text())

    text = normalize_text(article.inner_text())
    return text[:1000]


def extract_author_name(article: Any, username: str) -> str:
    candidate_selectors = [
        'div[data-testid="User-Name"] span',
        'a[href="/' + username + '"] span',
    ]
    for selector in candidate_selectors:
        locator = article.locator(selector)
        if locator.count() > 0:
            value = normalize_text(locator.first.inner_text())
            if value and not value.startswith("@"):
                return value
    return username


def normalize_text(text: str) -> str:
    return " ".join(text.split())


def write_csv(rows: list[dict[str, Any]], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"x_browser_search_{timestamp}.csv"
    fieldnames = [
        "query_label",
        "query",
        "tweet_id",
        "tweet_url",
        "created_at",
        "text",
        "author_name",
        "author_username",
        "collected_at",
    ]

    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return output_path


def main() -> int:
    args = parse_args()
    load_dotenv(DEFAULT_ENV_FILE)

    query_file = Path(args.query_file)
    output_dir = Path(args.output_dir)
    state_file = Path(args.state_file)
    queries, configured_max_results = load_queries(query_file)
    max_results = args.max_results or configured_max_results

    with sync_playwright() as playwright:
        browser, context = open_context(playwright, state_file, args.headless, args.browser_channel)
        try:
            page = ensure_logged_in(context, state_file, args.manual_login_timeout)
            all_rows: list[dict[str, Any]] = []
            for item in queries:
                print(f"searching: {item['label']}")
                rows = collect_query_rows(page, item["label"], item["query"], max_results)
                all_rows.extend(rows)

            if not all_rows:
                print("投稿を取得できませんでした。検索結果画面かログイン状態を確認してください。")
                return 0

            output_path = write_csv(all_rows, output_dir)
            print(f"saved: {output_path}")
            print(f"rows: {len(all_rows)}")
            return 0
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
