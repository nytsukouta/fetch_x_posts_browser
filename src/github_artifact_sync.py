"""GitHub Actionsの最新成功runから永続履歴artifactを安全に同期する。"""
from __future__ import annotations

import csv
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
from typing import Any, Callable
import zipfile

from atomic_io import atomic_open, atomic_write_text


ROOT_DIR = Path(__file__).resolve().parent.parent
WORKFLOW_FILE = "daily-pipeline.yml"
ARTIFACT_NAME = "pipeline-history-main"
ALLOWED_MEMBERS = frozenset(
    {
        "data/output/posted_events.csv",
        "data/output/structured_events_cumulative.csv",
        "data/output/structured_events_filtered_cumulative.csv",
        "data/output/event_cumulative_base.csv",
        "data/output/event_cumulative.csv",
    }
)
REQUIRED_MEMBERS = frozenset(
    {
        "data/output/structured_events_cumulative.csv",
        "data/output/structured_events_filtered_cumulative.csv",
        "data/output/event_cumulative.csv",
    }
)


class ArtifactSyncError(RuntimeError):
    """artifactの取得または検証に失敗した。"""


def _run(
    arguments: list[str],
    *,
    root_dir: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = runner(
            arguments,
            cwd=root_dir,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise ArtifactSyncError("GitHub CLI (gh) が見つかりません") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        raise ArtifactSyncError(f"GitHub CLIの実行に失敗しました{suffix}")
    return completed


def check_gh(*, root_dir: Path = ROOT_DIR, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> dict[str, bool]:
    _run(["gh", "--version"], root_dir=root_dir, runner=runner)
    _run(["gh", "auth", "status"], root_dir=root_dir, runner=runner)
    return {"available": True, "authenticated": True}


def find_latest_successful_run(
    *, root_dir: Path = ROOT_DIR, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run
) -> dict[str, Any]:
    completed = _run(
        [
            "gh",
            "run",
            "list",
            "--workflow",
            WORKFLOW_FILE,
            "--branch",
            "main",
            "--status",
            "success",
            "--limit",
            "1",
            "--json",
            "databaseId,createdAt,updatedAt,headSha,url",
        ],
        root_dir=root_dir,
        runner=runner,
    )
    try:
        runs = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ArtifactSyncError("GitHub Actions run一覧の応答を解釈できません") from exc
    if not isinstance(runs, list) or not runs:
        raise ArtifactSyncError("成功したGitHub Actions runが見つかりません")
    run = runs[0]
    if not isinstance(run, dict) or not run.get("databaseId"):
        raise ArtifactSyncError("GitHub Actions runの情報が不完全です")
    return run


def _validate_member_name(name: str) -> str:
    normalized = name.replace("\\", "/").rstrip("/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise ArtifactSyncError("artifactに危険なパスが含まれています")
    if normalized not in ALLOWED_MEMBERS:
        raise ArtifactSyncError(f"artifactに想定外のファイルが含まれています: {normalized}")
    return normalized


def _validate_csv(path: Path) -> None:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ArtifactSyncError("artifact内のCSVを読み込めません") from exc
    if not header or not any(str(value).strip() for value in header):
        raise ArtifactSyncError("artifact内のCSVにヘッダーがありません")


def _atomic_copy(source: Path, destination: Path) -> None:
    with source.open("rb") as input_handle:
        with atomic_open(destination, "wb") as output_handle:
            shutil.copyfileobj(input_handle, output_handle)


def restore_snapshot(snapshot_zip: Path, *, root_dir: Path = ROOT_DIR) -> dict[str, Any]:
    if not snapshot_zip.is_file():
        raise ArtifactSyncError("pipeline_history_snapshot.zip が見つかりません")

    warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix="maintenance-restore-") as temporary:
        extracted_root = Path(temporary)
        try:
            with zipfile.ZipFile(snapshot_zip) as archive:
                members: dict[str, zipfile.ZipInfo] = {}
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    normalized = _validate_member_name(info.filename)
                    members[normalized] = info
                missing = REQUIRED_MEMBERS - set(members)
                if missing:
                    raise ArtifactSyncError(f"artifactに必要なファイルがありません: {', '.join(sorted(missing))}")
                for normalized, info in members.items():
                    destination = extracted_root / PurePosixPath(normalized)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, destination.open("wb") as output:
                        shutil.copyfileobj(source, output)
        except zipfile.BadZipFile as exc:
            raise ArtifactSyncError("履歴snapshotが壊れています") from exc

        base_member = "data/output/event_cumulative_base.csv"
        if base_member not in members:
            source = extracted_root / "data/output/event_cumulative.csv"
            destination = extracted_root / base_member
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            members[base_member] = zipfile.ZipInfo(base_member)
            warnings.append("旧artifactのためeffectiveデータをbaseとして使用しました。補正解除時は元値を確認してください。")

        for normalized in members:
            _validate_csv(extracted_root / normalized)
        for normalized in sorted(members):
            _atomic_copy(extracted_root / normalized, root_dir / normalized)

    return {"restored": sorted(members), "warnings": warnings}


def sync_latest_artifact(
    *,
    root_dir: Path = ROOT_DIR,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    check_gh(root_dir=root_dir, runner=runner)
    run = find_latest_successful_run(root_dir=root_dir, runner=runner)
    with tempfile.TemporaryDirectory(prefix="maintenance-download-") as temporary:
        download_dir = Path(temporary)
        _run(
            [
                "gh",
                "run",
                "download",
                str(run["databaseId"]),
                "--name",
                ARTIFACT_NAME,
                "--dir",
                str(download_dir),
            ],
            root_dir=root_dir,
            runner=runner,
        )
        candidates = list(download_dir.rglob("pipeline_history_snapshot.zip"))
        if len(candidates) != 1:
            raise ArtifactSyncError("ダウンロードしたartifact内に履歴snapshotが1件だけ存在しません")
        restored = restore_snapshot(candidates[0], root_dir=root_dir)

    state = {
        "run_id": run["databaseId"],
        "head_sha": run.get("headSha", ""),
        "created_at": run.get("createdAt", ""),
        "updated_at": run.get("updatedAt", ""),
        "url": run.get("url", ""),
        "warnings": restored["warnings"],
    }
    state_path = root_dir / "data/output/_tmp/maintenance_sync_state.json"
    atomic_write_text(state_path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    return {**state, "restored": restored["restored"]}
