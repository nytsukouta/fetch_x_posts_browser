"""ファイルの atomic write ユーティリティ。

同一ディレクトリ内に一時ファイルを作って書き終わってから os.replace で差し替える。
途中で落ちても元ファイルが壊れた状態にならない。
"""
from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Iterator


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def atomic_open(path: Path, mode: str, *, encoding: str | None = None, newline: str | None = None) -> Iterator[IO]:
    """書き込み先と同じディレクトリに tmp を作って書き、終わったら os.replace する。"""
    if "w" not in mode:
        raise ValueError("atomic_open は書き込みモード専用です")

    _ensure_parent(path)
    binary = "b" in mode
    suffix = ".tmp"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=suffix, dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        if binary:
            handle: IO = os.fdopen(fd, "wb")
        else:
            handle = os.fdopen(fd, "w", encoding=encoding, newline=newline)
        try:
            yield handle
        finally:
            handle.close()
        os.replace(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    with atomic_open(path, "w", encoding=encoding, newline="") as handle:
        handle.write(text)
