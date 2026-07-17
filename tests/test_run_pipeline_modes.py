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
