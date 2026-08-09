import subprocess
import sys

import pytest

import run_pipeline


def test_parse_args_supports_rebuild_only_and_skip_query_rebuild(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_pipeline.py", "--rebuild-only", "--skip-query-rebuild"])

    args = run_pipeline.parse_args()

    assert args.rebuild_only is True
    assert args.skip_query_rebuild is True


def test_rebuild_only_rejects_posting(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_pipeline.py", "--rebuild-only", "--post-new-events"])

    with pytest.raises(ValueError, match="--rebuild-only と --post-new-events"):
        run_pipeline.main()


def test_merge_cumulative_outputs_uses_existing_data_when_extraction_is_empty(tmp_path, monkeypatch):
    structured_path = tmp_path / "structured_events.csv"
    cumulative_filtered_path = tmp_path / "structured_events_filtered_cumulative.csv"
    structured_path.write_text("tweet_url,event_name\n", encoding="utf-8-sig")
    cumulative_filtered_path.write_text(
        "tweet_url,event_name\nhttps://x.test/1,公演\n",
        encoding="utf-8-sig",
    )

    monkeypatch.setattr(run_pipeline, "DEFAULT_STRUCTURED_CSV", structured_path)
    monkeypatch.setattr(run_pipeline, "DEFAULT_CUMULATIVE_FILTERED_CSV", cumulative_filtered_path)

    assert run_pipeline.merge_cumulative_outputs() == cumulative_filtered_path


def test_run_command_reports_stderr_on_success(monkeypatch, capsys):
    completed = subprocess.CompletedProcess(["child"], 0, stdout="ok\n", stderr="warning\n")
    monkeypatch.setattr(run_pipeline.subprocess, "run", lambda *args, **kwargs: completed)

    assert run_pipeline.run_command(["child"]) is completed

    captured = capsys.readouterr()
    assert "ok" in captured.out
    assert "warning" in captured.err
