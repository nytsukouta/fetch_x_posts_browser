"""分割後の event_cumulative_core / llm モジュールが期待どおり import できることを担保する。"""
import event_cumulative_core as core
import event_cumulative_llm as llm
import build_event_cumulative as facade


def test_core_pure_functions_exported():
    assert core.compact_text("Hello!") == "hello"
    assert core.build_event_key({"event_name": "X", "start_date": "2026-06-01"})


def test_llm_module_exposes_dedupe():
    assert callable(llm.secondary_dedupe)
    assert llm.SECONDARY_DEDUPE_SYSTEM_PROMPT.startswith("あなた")


def test_facade_reexports_for_backward_compat():
    # 既存 import パスが壊れていないこと
    assert facade.compact_text is core.compact_text
    assert facade.secondary_dedupe is llm.secondary_dedupe
    assert facade.SECONDARY_DEDUPE_SYSTEM_PROMPT == llm.SECONDARY_DEDUPE_SYSTEM_PROMPT


def test_secondary_dedupe_uses_cache_for_same_input(tmp_path, monkeypatch):
    records = [
        {
            "event_name": "春公演",
            "normalized_event_name": "春公演",
            "organization": "劇団A",
            "venue_name": "会場A",
            "normalized_venue_name": "会場A",
            "start_date": "2026-05-01",
            "end_date": "2026-05-01",
            "category": "演劇",
            "source_text": "春公演の案内",
        },
        {
            "event_name": "春公演 in 金沢",
            "normalized_event_name": "春公演 in 金沢",
            "organization": "劇団A",
            "venue_name": "会場A",
            "normalized_venue_name": "会場A",
            "start_date": "2026-05-01",
            "end_date": "2026-05-01",
            "category": "演劇",
            "source_text": "春公演 in 金沢の案内",
        },
    ]
    calls = []

    monkeypatch.setattr(llm, "get_github_models_token", lambda: "token")

    def fake_call(*args, **kwargs):
        calls.append(1)
        return {"choices": [{"message": {"content": '{"decisions":[{"member_ids":["1","2"],"canonical_name":"春公演"}]}'}}]}

    monkeypatch.setattr(llm, "call_dedupe_model", fake_call)
    cache_path = tmp_path / "dedupe-cache.json"

    first = llm.secondary_dedupe(records, "test-model", cache_path=cache_path)
    second = llm.secondary_dedupe(records, "test-model", cache_path=cache_path)

    assert len(calls) == 1
    assert first == second
    assert cache_path.exists()
