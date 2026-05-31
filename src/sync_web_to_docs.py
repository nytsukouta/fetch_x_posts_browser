"""web/ をソースとして docs/ を生成する（GitHub Pages 用に DATA_URL を書き換え）。"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from atomic_io import atomic_write_text


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DIR = ROOT_DIR / "web"
DEFAULT_DEST_DIR = ROOT_DIR / "docs"

# web/ では data/output を直接参照するが、docs/ では同梱の data/ を参照する
APP_JS_REWRITES = [
    (
        'const DATA_URL = "../data/output/schedule_list.json";',
        'const DATA_URL = "./data/schedule_list.json";',
    ),
    (
        "HTTP サーバー経由で開いているか確認してください。",
        "schedule_list.json が生成されているか確認してください。",
    ),
]


def sync_file(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix == ".js" and source.name == "app.js":
        text = source.read_text(encoding="utf-8")
        for old, new in APP_JS_REWRITES:
            text = text.replace(old, new)
        atomic_write_text(dest, text)
        return
    if source.suffix in {".html", ".css", ".js"}:
        atomic_write_text(dest, source.read_text(encoding="utf-8"))
        return
    shutil.copy2(source, dest)


def sync_static_assets(source_dir: Path, dest_dir: Path) -> list[Path]:
    synced: list[Path] = []
    for source in source_dir.iterdir():
        if source.is_dir():
            continue
        if source.name.startswith("."):
            continue
        dest = dest_dir / source.name
        sync_file(source, dest)
        synced.append(dest)
    return synced


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="web/ から docs/ を生成する")
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR), help="ソース静的ファイル ディレクトリ")
    parser.add_argument("--dest-dir", default=str(DEFAULT_DEST_DIR), help="出力先 ディレクトリ")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_dir = Path(args.source_dir)
    dest_dir = Path(args.dest_dir)
    if not source_dir.is_dir():
        raise FileNotFoundError(f"source dir not found: {source_dir}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    synced = sync_static_assets(source_dir, dest_dir)
    for path in synced:
        print(f"synced: {path}")
    print(f"files: {len(synced)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
