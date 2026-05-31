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
