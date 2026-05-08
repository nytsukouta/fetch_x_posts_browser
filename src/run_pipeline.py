from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = ROOT_DIR / "data" / "output"
DEFAULT_EXISTING_INPUT_CSV = ROOT_DIR / "data" / "output" / "x_browser_search_20260508_124323.csv"
DEFAULT_PAGES_JSON = ROOT_DIR / "docs" / "data" / "schedule_list.json"
DEFAULT_STRUCTURED_CSV = ROOT_DIR / "data" / "output" / "structured_events.csv"
DEFAULT_FILTERED_CSV = ROOT_DIR / "data" / "output" / "structured_events_filtered.csv"
DEFAULT_CUMULATIVE_STRUCTURED_CSV = ROOT_DIR / "data" / "output" / "structured_events_cumulative.csv"
DEFAULT_CUMULATIVE_FILTERED_CSV = ROOT_DIR / "data" / "output" / "structured_events_filtered_cumulative.csv"
DEFAULT_EVENT_CUMULATIVE_CSV = ROOT_DIR / "data" / "output" / "event_cumulative.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run collection and data shaping pipeline in one command")
    parser.add_argument("--skip-collect", action="store_true", help="情報収集を飛ばして既存CSVから続行する")
    parser.add_argument("--input-csv", default=str(DEFAULT_EXISTING_INPUT_CSV), help="--skip-collect 時に使う収集済みCSV")
    parser.add_argument("--query-file", default=str(ROOT_DIR / "config" / "priority_queries.json"), help="収集に使うクエリJSON")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="収集CSVの出力先")
    parser.add_argument("--collector", choices=["api", "browser"], default="api", help="情報収集の方式。既定は api")
    parser.add_argument("--state-file", default=str(ROOT_DIR / "data" / "session" / "x_storage_state.json"), help="Xログイン状態JSON")
    parser.add_argument("--max-results", type=int, default=None, help="各クエリの取得件数")
    parser.add_argument("--headless", action="store_true", help="収集をヘッドレスで実行する")
    parser.add_argument("--browser-channel", default="msedge", help="Playwright の browser channel")
    parser.add_argument("--manual-login-timeout", type=int, default=600, help="手動ログイン待機秒数")
    parser.add_argument("--extract-limit", type=int, default=None, help="構造化抽出の件数上限")
    parser.add_argument("--model", default=None, help="GitHub Models のモデルIDを上書きする")
    parser.add_argument("--publish", action="store_true", help="生成後に Pages 用 JSON を commit と push する")
    parser.add_argument("--commit-message", default=None, help="--publish 時のコミットメッセージ")
    return parser.parse_args()


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    print("running:", " ".join(command))
    completed = subprocess.run(command, cwd=ROOT_DIR, text=True, capture_output=True)
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.returncode != 0:
        if completed.stderr:
            print(completed.stderr, file=sys.stderr, end="" if completed.stderr.endswith("\n") else "\n")
        raise RuntimeError(f"command failed with exit code {completed.returncode}")
    return completed


def find_saved_csv(stdout: str) -> Path:
    for line in stdout.splitlines():
        if line.startswith("saved: "):
            return Path(line.removeprefix("saved: ").strip())
    raise RuntimeError("収集CSVの保存先を出力から判定できませんでした。")


def collect_posts(args: argparse.Namespace) -> Path:
    if args.collector == "api":
        command = [sys.executable, str(ROOT_DIR / "src" / "fetch_x_posts.py")]
    else:
        command = [sys.executable, str(ROOT_DIR / "src" / "fetch_x_posts_browser.py")]
    command.extend(["--query-file", args.query_file])
    command.extend(["--output-dir", args.output_dir])
    if args.max_results is not None:
        command.extend(["--max-results", str(args.max_results)])
    if args.collector == "browser":
        command.extend(["--state-file", args.state_file])
        command.extend(["--browser-channel", args.browser_channel])
        command.extend(["--manual-login-timeout", str(args.manual_login_timeout)])
        if args.headless:
            command.append("--headless")

    completed = run_command(command)
    return find_saved_csv(completed.stdout)


def extract_events(input_csv: Path, args: argparse.Namespace) -> None:
    command = [
        sys.executable,
        str(ROOT_DIR / "src" / "extract_events_github_models.py"),
        "--input-csv",
        str(input_csv),
    ]
    if args.extract_limit is not None:
        command.extend(["--limit", str(args.extract_limit)])
    if args.model:
        command.extend(["--model", args.model])
    run_command(command)


def load_csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        return rows, list(reader.fieldnames or [])


def write_csv_rows(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def merge_cumulative_outputs() -> Path:
    current_rows, current_fieldnames = load_csv_rows(DEFAULT_STRUCTURED_CSV)
    if not current_rows or not current_fieldnames:
        raise RuntimeError("structured_events.csv が見つからないため累積マージできません。")

    cumulative_rows, cumulative_fieldnames = load_csv_rows(DEFAULT_CUMULATIVE_STRUCTURED_CSV)
    fieldnames = list(cumulative_fieldnames or current_fieldnames)
    for fieldname in current_fieldnames:
        if fieldname not in fieldnames:
            fieldnames.append(fieldname)
    merged_by_tweet_url: dict[str, dict[str, str]] = {}

    for row in cumulative_rows:
        tweet_url = (row.get("tweet_url") or "").strip()
        if tweet_url:
            merged_by_tweet_url[tweet_url] = row

    existing_count = len(merged_by_tweet_url)
    for row in current_rows:
        tweet_url = (row.get("tweet_url") or "").strip()
        if not tweet_url:
            continue
        merged_by_tweet_url[tweet_url] = row

    merged_rows = sorted(
        merged_by_tweet_url.values(),
        key=lambda row: ((row.get("created_at") or ""), (row.get("tweet_url") or "")),
        reverse=True,
    )
    filtered_rows = [row for row in merged_rows if str(row.get("is_noise") or "").lower() != "true"]

    write_csv_rows(DEFAULT_CUMULATIVE_STRUCTURED_CSV, merged_rows, fieldnames)
    write_csv_rows(DEFAULT_CUMULATIVE_FILTERED_CSV, filtered_rows, fieldnames)

    new_count = len(merged_by_tweet_url) - existing_count
    print(f"merged cumulative structured rows: {len(merged_rows)}")
    print(f"new tweet rows: {max(new_count, 0)}")
    print(f"merged cumulative filtered rows: {len(filtered_rows)}")
    return DEFAULT_CUMULATIVE_FILTERED_CSV


def build_event_cumulative(input_csv: Path) -> Path:
    run_command([
        sys.executable,
        str(ROOT_DIR / "src" / "build_event_cumulative.py"),
        "--input-csv",
        str(input_csv),
        "--output-csv",
        str(DEFAULT_EVENT_CUMULATIVE_CSV),
    ])
    return DEFAULT_EVENT_CUMULATIVE_CSV


def build_schedule(input_csv: Path) -> None:
    run_command([
        sys.executable,
        str(ROOT_DIR / "src" / "build_schedule_list.py"),
        "--events-csv",
        str(input_csv),
    ])


def run_git(command: list[str]) -> subprocess.CompletedProcess[str]:
    return run_command(["git", *command])


def publish_pages_data(args: argparse.Namespace) -> None:
    pages_json = ROOT_DIR / "docs" / "data" / "schedule_list.json"
    if not pages_json.exists():
        raise FileNotFoundError(f"pages json not found: {pages_json}")

    run_git(["add", str(pages_json)])
    diff_result = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", str(pages_json)],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
    )
    if diff_result.returncode == 0:
        print("publish skipped: docs/data/schedule_list.json に差分がありません")
        return
    if diff_result.returncode != 1:
        raise RuntimeError("staged diff の確認に失敗しました。")

    commit_message = args.commit_message or default_commit_message()
    run_git(["commit", "-m", commit_message])
    run_git(["push"])


def default_commit_message() -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"Update published schedule data ({timestamp})"


def main() -> int:
    args = parse_args()
    if args.skip_collect:
        input_csv = Path(args.input_csv)
        if not input_csv.exists():
            raise FileNotFoundError(f"input csv not found: {input_csv}")
    else:
        input_csv = collect_posts(args)

    extract_events(input_csv, args)
    cumulative_filtered_csv = merge_cumulative_outputs()
    event_cumulative_csv = build_event_cumulative(cumulative_filtered_csv)
    print("master update skipped: 劇団マスターと劇場マスターは既存ファイルを保持します")
    build_schedule(event_cumulative_csv)
    if args.publish:
        publish_pages_data(args)
    print("pipeline completed")
    print(f"input_csv: {input_csv}")
    print(f"cumulative_structured_csv: {DEFAULT_CUMULATIVE_STRUCTURED_CSV}")
    print(f"cumulative_filtered_csv: {DEFAULT_CUMULATIVE_FILTERED_CSV}")
    print(f"event_cumulative_csv: {DEFAULT_EVENT_CUMULATIVE_CSV}")
    print(f"schedule_csv: {ROOT_DIR / 'data' / 'output' / 'schedule_list.csv'}")
    print(f"pages_json: {DEFAULT_PAGES_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())