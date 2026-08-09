import sys

import extract_events_github_models


def test_main_fails_when_all_extractions_fail(tmp_path, monkeypatch, capsys):
    input_csv = tmp_path / "input.csv"
    input_csv.write_text("tweet_url\nhttps://x.test/1\n", encoding="utf-8-sig")
    output_csv = tmp_path / "structured.csv"
    filtered_output_csv = tmp_path / "filtered.csv"

    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-token")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "extract_events_github_models.py",
            "--input-csv",
            str(input_csv),
            "--output-csv",
            str(output_csv),
            "--filtered-output-csv",
            str(filtered_output_csv),
        ],
    )
    monkeypatch.setattr(extract_events_github_models, "enrich_source_row", lambda row, token: row)
    monkeypatch.setattr(
        extract_events_github_models,
        "call_github_models",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("API unavailable")),
    )

    assert extract_events_github_models.main() == 1
    assert "all extractions failed: 1/1" in capsys.readouterr().err
    assert not output_csv.exists()
    assert not filtered_output_csv.exists()