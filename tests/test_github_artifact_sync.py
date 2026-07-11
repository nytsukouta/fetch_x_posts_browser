import csv
import json
import subprocess
import zipfile

import pytest

from github_artifact_sync import ArtifactSyncError, find_latest_successful_run, restore_snapshot


def _runner(stdout, returncode=0):
    def run(arguments, **kwargs):
        return subprocess.CompletedProcess(arguments, returncode, stdout=stdout, stderr="")
    return run


def _csv_bytes(header="event_id,event_name\n", row="event-a,公演A\n"):
    return (header + row).encode("utf-8-sig")


def _snapshot(path, *, include_base=True, extra=None):
    files = {
        "data/output/structured_events_cumulative.csv": _csv_bytes("tweet_url,event_name\n", "https://x.com/a,公演A\n"),
        "data/output/structured_events_filtered_cumulative.csv": _csv_bytes("tweet_url,event_name\n", "https://x.com/a,公演A\n"),
        "data/output/event_cumulative.csv": _csv_bytes(),
    }
    if include_base:
        files["data/output/event_cumulative_base.csv"] = _csv_bytes()
    if extra:
        files[extra] = b"x"
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def test_finds_latest_successful_run(tmp_path):
    payload = [{"databaseId": 123, "headSha": "abc", "url": "https://example.test/run/123"}]
    run = find_latest_successful_run(root_dir=tmp_path, runner=_runner(json.dumps(payload)))
    assert run["databaseId"] == 123


def test_no_successful_run_is_error(tmp_path):
    with pytest.raises(ArtifactSyncError, match="見つかりません"):
        find_latest_successful_run(root_dir=tmp_path, runner=_runner("[]"))


def test_restore_snapshot_and_old_artifact_fallback(tmp_path):
    snapshot = tmp_path / "snapshot.zip"
    _snapshot(snapshot, include_base=False)
    result = restore_snapshot(snapshot, root_dir=tmp_path)
    assert (tmp_path / "data/output/event_cumulative.csv").exists()
    assert (tmp_path / "data/output/event_cumulative_base.csv").exists()
    assert result["warnings"]
    with (tmp_path / "data/output/event_cumulative_base.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        assert next(csv.DictReader(handle))["event_id"] == "event-a"


def test_restore_rejects_path_traversal(tmp_path):
    snapshot = tmp_path / "snapshot.zip"
    _snapshot(snapshot, extra="../escape.csv")
    with pytest.raises(ArtifactSyncError, match="危険なパス"):
        restore_snapshot(snapshot, root_dir=tmp_path)
    assert not (tmp_path.parent / "escape.csv").exists()


def test_restore_rejects_unexpected_file(tmp_path):
    snapshot = tmp_path / "snapshot.zip"
    _snapshot(snapshot, extra="data/output/secret.txt")
    with pytest.raises(ArtifactSyncError, match="想定外"):
        restore_snapshot(snapshot, root_dir=tmp_path)
