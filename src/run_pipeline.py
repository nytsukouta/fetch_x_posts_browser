from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = ROOT_DIR / "data" / "output"
DEFAULT_EXISTING_INPUT_CSV = ROOT_DIR / "data" / "output" / "x_browser_search_20260508_124323.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run collection and data shaping pipeline in one command")
    parser.add_argument("--skip-collect", action="store_true", help="情報収集を飛ばして既存CSVから続行する")
    parser.add_argument("--input-csv", default=str(DEFAULT_EXISTING_INPUT_CSV), help="--skip-collect 時に使う収集済みCSV")
    parser.add_argument("--query-file", default=str(ROOT_DIR / "config" / "priority_queries.json"), help="収集に使うクエリJSON")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="収集CSVの出力先")
    parser.add_argument("--state-file", default=str(ROOT_DIR / "data" / "session" / "x_storage_state.json"), help="Xログイン状態JSON")
    parser.add_argument("--max-results", type=int, default=None, help="各クエリの取得件数")
    parser.add_argument("--headless", action="store_true", help="収集をヘッドレスで実行する")
    parser.add_argument("--browser-channel", default="msedge", help="Playwright の browser channel")
    parser.add_argument("--manual-login-timeout", type=int, default=600, help="手動ログイン待機秒数")
    parser.add_argument("--extract-limit", type=int, default=None, help="構造化抽出の件数上限")
    parser.add_argument("--model", default=None, help="GitHub Models のモデルIDを上書きする")
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
    command = [sys.executable, str(ROOT_DIR / "src" / "fetch_x_posts_browser.py")]
    command.extend(["--query-file", args.query_file])
    command.extend(["--output-dir", args.output_dir])
    command.extend(["--state-file", args.state_file])
    command.extend(["--browser-channel", args.browser_channel])
    command.extend(["--manual-login-timeout", str(args.manual_login_timeout)])
    if args.max_results is not None:
        command.extend(["--max-results", str(args.max_results)])
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


def build_masters() -> None:
    run_command([sys.executable, str(ROOT_DIR / "src" / "build_entity_masters.py")])


def build_schedule() -> None:
    run_command([sys.executable, str(ROOT_DIR / "src" / "build_schedule_list.py")])


def main() -> int:
    args = parse_args()
    if args.skip_collect:
        input_csv = Path(args.input_csv)
        if not input_csv.exists():
            raise FileNotFoundError(f"input csv not found: {input_csv}")
    else:
        input_csv = collect_posts(args)

    extract_events(input_csv, args)
    build_masters()
    build_schedule()
    print("pipeline completed")
    print(f"input_csv: {input_csv}")
    print(f"schedule_csv: {ROOT_DIR / 'data' / 'output' / 'schedule_list.csv'}")
    print(f"pages_json: {ROOT_DIR / 'docs' / 'data' / 'schedule_list.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())