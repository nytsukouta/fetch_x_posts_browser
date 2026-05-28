from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = ROOT_DIR / "data" / "output"
DEFAULT_EXISTING_INPUT_CSV = ROOT_DIR / "data" / "output" / "x_recent_search_20260509_173241.csv"
DEFAULT_QUERY_FILE = ROOT_DIR / "config" / "priority_queries.json"
DEFAULT_PAGES_JSON = ROOT_DIR / "docs" / "data" / "schedule_list.json"
DEFAULT_MASTER_PAGES_JSON = ROOT_DIR / "docs" / "data" / "master_data.json"
DEFAULT_MASTER_WEB_JSON = ROOT_DIR / "web" / "data" / "master_data.json"
DEFAULT_STRUCTURED_CSV = ROOT_DIR / "data" / "output" / "structured_events.csv"
DEFAULT_FILTERED_CSV = ROOT_DIR / "data" / "output" / "structured_events_filtered.csv"
DEFAULT_CUMULATIVE_STRUCTURED_CSV = ROOT_DIR / "data" / "output" / "structured_events_cumulative.csv"
DEFAULT_CUMULATIVE_FILTERED_CSV = ROOT_DIR / "data" / "output" / "structured_events_filtered_cumulative.csv"
DEFAULT_EVENT_CUMULATIVE_CSV = ROOT_DIR / "data" / "output" / "event_cumulative.csv"
DEFAULT_POSTED_EVENTS_CSV = ROOT_DIR / "data" / "output" / "posted_events.csv"
DEFAULT_LOCAL_PREVIEW_DIR = DEFAULT_OUTPUT_DIR / "_local_preview"
DEFAULT_PENDING_EXTRACT_INPUT_CSV = ROOT_DIR / "data" / "output" / "_tmp_extract_pending.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run collection and data shaping pipeline in one command")
    parser.add_argument("--skip-collect", action="store_true", help="情報収集を飛ばして既存CSVから続行する")
    parser.add_argument("--input-csv", default=str(DEFAULT_EXISTING_INPUT_CSV), help="--skip-collect 時に使う収集済みCSV")
    parser.add_argument("--query-file", default=str(DEFAULT_QUERY_FILE), help="収集に使うクエリJSON")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="収集CSVの出力先")
    parser.add_argument("--max-results", type=int, default=None, help="各クエリの取得件数")
    parser.add_argument("--extract-limit", type=int, default=None, help="構造化抽出の件数上限")
    parser.add_argument("--model", default=None, help="GitHub Models のモデルIDを上書きする")
    parser.add_argument("--no-images", action="store_true", help="構造化抽出で添付画像を GitHub Models に渡さない")
    parser.add_argument("--debug-outputs", action="store_true", help="抽出段階の JSONL などデバッグ用中間生成物も保存する")
    parser.add_argument("--post-new-events", action="store_true", help="新規公演を X に投稿する")
    parser.add_argument("--post-dry-run", action="store_true", help="新規公演の投稿文だけを表示し、実際には投稿しない")
    parser.add_argument("--post-limit", type=int, default=None, help="投稿または dry-run 表示する件数上限")
    parser.add_argument("--post-hashtag", default="石川演劇", help="投稿末尾に付けるハッシュタグ。空文字で無効化")
    parser.add_argument(
        "--local-preview-dir",
        nargs="?",
        const=str(DEFAULT_LOCAL_PREVIEW_DIR),
        default=None,
        help="ローカル確認用の生成物を別ディレクトリへ保存し、config/docs/web の tracked ファイルを更新しない",
    )
    parser.add_argument("--publish", action="store_true", help="生成後に Pages 用 JSON を commit と push する")
    parser.add_argument("--commit-message", default=None, help="--publish 時のコミットメッセージ")
    return parser.parse_args()


def resolve_runtime_paths(args: argparse.Namespace) -> dict[str, Path]:
    query_file = Path(args.query_file)
    schedule_pages_json = DEFAULT_PAGES_JSON
    master_pages_json = DEFAULT_MASTER_PAGES_JSON
    master_web_json = DEFAULT_MASTER_WEB_JSON

    if args.local_preview_dir:
        preview_dir = Path(args.local_preview_dir)
        if query_file == DEFAULT_QUERY_FILE:
            query_file = preview_dir / "config" / "priority_queries.json"
        schedule_pages_json = preview_dir / "docs" / "data" / "schedule_list.json"
        master_pages_json = preview_dir / "docs" / "data" / "master_data.json"
        master_web_json = preview_dir / "web" / "data" / "master_data.json"

    return {
        "query_file": query_file,
        "schedule_pages_json": schedule_pages_json,
        "master_pages_json": master_pages_json,
        "master_web_json": master_web_json,
    }


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


def rebuild_query_configuration(query_file: Path) -> None:
    run_command([
        sys.executable,
        str(ROOT_DIR / "src" / "build_priority_queries_from_masters.py"),
        "--output-json",
        str(query_file),
    ])


def collect_posts(args: argparse.Namespace, query_file: Path) -> Path:
    command = [sys.executable, str(ROOT_DIR / "src" / "fetch_x_posts.py")]
    command.extend(["--query-file", str(query_file)])
    command.extend(["--output-dir", args.output_dir])
    if args.max_results is not None:
        command.extend(["--max-results", str(args.max_results)])

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
    if args.no_images:
        command.append("--no-images")
    if args.debug_outputs:
        command.append("--debug-outputs")
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


def tweet_identity_key(row: dict[str, str]) -> str:
    tweet_url = str(row.get("tweet_url") or "").strip()
    if tweet_url:
        return tweet_url
    return str(row.get("tweet_id") or "").strip()


def dedupe_tweet_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], int]:
    deduped_by_key: dict[str, dict[str, str]] = {}
    unique_rows_without_key: list[dict[str, str]] = []
    duplicate_count = 0

    for row in rows:
        key = tweet_identity_key(row)
        if not key:
            unique_rows_without_key.append(row)
            continue
        if key in deduped_by_key:
            duplicate_count += 1
            continue
        deduped_by_key[key] = row

    return [*deduped_by_key.values(), *unique_rows_without_key], duplicate_count


def load_known_tweet_keys(path: Path) -> set[str]:
    rows, _ = load_csv_rows(path)
    return {key for row in rows if (key := tweet_identity_key(row))}


def filter_known_tweet_rows(rows: list[dict[str, str]], known_keys: set[str]) -> tuple[list[dict[str, str]], int]:
    filtered_rows: list[dict[str, str]] = []
    skipped_count = 0
    for row in rows:
        key = tweet_identity_key(row)
        if key and key in known_keys:
            skipped_count += 1
            continue
        filtered_rows.append(row)
    return filtered_rows, skipped_count


def prepare_extraction_rows(input_csv: Path) -> tuple[list[dict[str, str]], list[str], dict[str, int]]:
    input_rows, fieldnames = load_csv_rows(input_csv)
    if not input_rows or not fieldnames:
        return [], fieldnames, {"input_rows": 0, "deduped_duplicates": 0, "known_skipped": 0, "pending_rows": 0}

    deduped_rows, duplicate_count = dedupe_tweet_rows(input_rows)
    known_keys = load_known_tweet_keys(DEFAULT_CUMULATIVE_STRUCTURED_CSV)
    pending_rows, skipped_count = filter_known_tweet_rows(deduped_rows, known_keys)
    return pending_rows, fieldnames, {
        "input_rows": len(input_rows),
        "deduped_duplicates": duplicate_count,
        "known_skipped": skipped_count,
        "pending_rows": len(pending_rows),
    }


def prepare_extraction_input(input_csv: Path) -> Path | None:
    pending_rows, fieldnames, stats = prepare_extraction_rows(input_csv)
    print(
        "prepare extraction input:",
        f"input_rows={stats['input_rows']}",
        f"deduped_duplicates={stats['deduped_duplicates']}",
        f"known_skipped={stats['known_skipped']}",
        f"pending_rows={stats['pending_rows']}",
    )
    if not pending_rows or not fieldnames:
        return None

    write_csv_rows(DEFAULT_PENDING_EXTRACT_INPUT_CSV, pending_rows, fieldnames)
    return DEFAULT_PENDING_EXTRACT_INPUT_CSV


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


def build_schedule(input_csv: Path, pages_json: Path) -> None:
    run_command([
        sys.executable,
        str(ROOT_DIR / "src" / "build_schedule_list.py"),
        "--events-csv",
        str(input_csv),
        "--pages-json",
        str(pages_json),
    ])


def build_master_pages_data(pages_json: Path, web_json: Path) -> None:
    run_command([
        sys.executable,
        str(ROOT_DIR / "src" / "build_master_pages_data.py"),
        "--pages-json",
        str(pages_json),
        "--web-json",
        str(web_json),
    ])


def post_new_events(input_csv: Path, args: argparse.Namespace) -> None:
    command = [
        sys.executable,
        str(ROOT_DIR / "src" / "post_new_events_to_x.py"),
        "--events-csv",
        str(input_csv),
        "--posted-log-csv",
        str(DEFAULT_POSTED_EVENTS_CSV),
        "--hashtag",
        args.post_hashtag,
    ]
    if args.post_dry_run:
        command.append("--dry-run")
    if args.post_limit is not None:
        command.extend(["--limit", str(args.post_limit)])
    run_command(command)


def run_git(command: list[str]) -> subprocess.CompletedProcess[str]:
    return run_command(["git", *command])


def publish_pages_data(args: argparse.Namespace) -> None:
    pages_files = [
        ROOT_DIR / "docs" / "data" / "schedule_list.json",
        ROOT_DIR / "docs" / "data" / "master_data.json",
    ]
    for pages_file in pages_files:
        if not pages_file.exists():
            raise FileNotFoundError(f"pages json not found: {pages_file}")

    run_git(["add", *(str(path) for path in pages_files)])
    diff_result = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", *(str(path) for path in pages_files)],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
    )
    if diff_result.returncode == 0:
        print("publish skipped: docs/data の公開JSONに差分がありません")
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
    if args.publish and args.local_preview_dir:
        raise ValueError("--publish と --local-preview-dir は同時に使えません。")
    if args.post_dry_run and not args.post_new_events:
        raise ValueError("--post-dry-run を使う場合は --post-new-events も指定してください。")

    runtime_paths = resolve_runtime_paths(args)
    rebuild_query_configuration(runtime_paths["query_file"])
    if args.skip_collect:
        input_csv = Path(args.input_csv)
        if not input_csv.exists():
            raise FileNotFoundError(f"input csv not found: {input_csv}")
    else:
        input_csv = collect_posts(args, runtime_paths["query_file"])

    extraction_input_csv = prepare_extraction_input(input_csv)
    if extraction_input_csv is None:
        print("extract skipped: 新規 tweet がありません")
        if not DEFAULT_CUMULATIVE_FILTERED_CSV.exists():
            raise FileNotFoundError("新規 tweet がなく、structured_events_filtered_cumulative.csv も見つかりません。")
        cumulative_filtered_csv = DEFAULT_CUMULATIVE_FILTERED_CSV
    else:
        extract_events(extraction_input_csv, args)
        cumulative_filtered_csv = merge_cumulative_outputs()
    event_cumulative_csv = build_event_cumulative(cumulative_filtered_csv)
    print("master update skipped: 劇団マスターと劇場マスターは既存ファイルを保持します")
    if args.post_new_events:
        post_new_events(event_cumulative_csv, args)
    build_schedule(event_cumulative_csv, runtime_paths["schedule_pages_json"])
    build_master_pages_data(runtime_paths["master_pages_json"], runtime_paths["master_web_json"])
    if args.publish:
        publish_pages_data(args)
    print("pipeline completed")
    print(f"input_csv: {input_csv}")
    print(f"cumulative_structured_csv: {DEFAULT_CUMULATIVE_STRUCTURED_CSV}")
    print(f"cumulative_filtered_csv: {DEFAULT_CUMULATIVE_FILTERED_CSV}")
    print(f"event_cumulative_csv: {DEFAULT_EVENT_CUMULATIVE_CSV}")
    print(f"schedule_csv: {ROOT_DIR / 'data' / 'output' / 'schedule_list.csv'}")
    print(f"pages_json: {runtime_paths['schedule_pages_json']}")
    if args.local_preview_dir:
        print(f"local_preview_dir: {Path(args.local_preview_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())