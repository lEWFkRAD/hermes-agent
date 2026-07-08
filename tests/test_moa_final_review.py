"""Unit tests for agent.moa_final_review (final-submission review pass).

Model calls are monkeypatched so these run offline and fast. Covers the contract:
opt-in, fail-open, OK-passthrough, material-flag revision, and config survival.
"""
import agent.moa_final_review as fr
from hermes_cli.moa_config import _normalize_preset, normalize_moa_config


def _cfg(**over):
    c = {
        "final_review": True,
        "reference_models": [{"provider": "ref-gptoss", "model": "gpt-oss-20b"}],
        "aggregator": {"provider": "5090-personal", "model": "qwen3.6-27b-nvfp4"},
        "reference_temperature": 0.2,
        "aggregator_temperature": 0.2,
        "max_tokens": 4096,
    }
    c.update(over)
    return c


_ANSWER = "Reconciled AP: invoices total $7,060 and match the GL balance. Done."
_MSGS = [
    {"role": "user", "content": "reconcile AP and tell me if it ties"},
    {"role": "tool", "content": "sum(invoice_amount)=7060; gl_ap_balance=7060"},
]


def _patch_calls(monkeypatch, verdict, revised="REVISED ANSWER that is clearly long enough to pass."):
    calls = []

    def fake(slot, messages, *, temperature, max_tokens):
        calls.append((slot, messages))
        # first call = reviewer, second = aggregator revision
        return verdict if len(calls) == 1 else revised

    monkeypatch.setattr(fr, "_call", fake)
    return calls


def test_disabled_returns_original_no_calls(monkeypatch):
    calls = _patch_calls(monkeypatch, "OK")
    out = fr.maybe_final_review(None, _ANSWER, _MSGS, _cfg(final_review=False))
    assert out == _ANSWER
    assert calls == []  # never touched a model


def test_missing_config_returns_original(monkeypatch):
    _patch_calls(monkeypatch, "OK")
    assert fr.maybe_final_review(None, _ANSWER, _MSGS, None) == _ANSWER
    assert fr.maybe_final_review(None, _ANSWER, _MSGS, {}) == _ANSWER


def test_non_substantive_skipped(monkeypatch):
    calls = _patch_calls(monkeypatch, "flag: wrong")
    for bad in ["", "  ", "(empty)", "I apologize, but I encountered repeated errors: x", "short"]:
        assert fr.maybe_final_review(None, bad, _MSGS, _cfg()) == bad
    assert calls == []  # gate skipped before any model call


def test_ok_verdict_passes_through(monkeypatch):
    calls = _patch_calls(monkeypatch, "OK")
    out = fr.maybe_final_review(None, _ANSWER, _MSGS, _cfg())
    assert out == _ANSWER
    assert len(calls) == 1  # reviewer only, no revision


def test_material_flag_triggers_revision(monkeypatch):
    revised = "Corrected: AP ties at $7,060 after subtracting $200 in credit memos."
    calls = _patch_calls(monkeypatch, "The total ignores credit memos; subtract them before comparing.", revised)
    out = fr.maybe_final_review(None, _ANSWER, _MSGS, _cfg())
    assert out == revised
    assert len(calls) == 2  # reviewer + aggregator


def test_revision_empty_falls_back_to_original(monkeypatch):
    calls = _patch_calls(monkeypatch, "material problem here", revised="")
    out = fr.maybe_final_review(None, _ANSWER, _MSGS, _cfg())
    assert out == _ANSWER  # empty revision => keep original
    assert len(calls) == 2


def test_fail_open_on_exception(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("endpoint down")
    monkeypatch.setattr(fr, "_call", boom)
    assert fr.maybe_final_review(None, _ANSWER, _MSGS, _cfg()) == _ANSWER


def test_flag_is_material():
    for ok in ["OK", "ok", "OK.", '"OK"', "OK - looks sound", "fine", "good"]:
        assert fr._flag_is_material(ok) is False, ok
    for flag in [
        "The number doesn't foot: 7060 vs 7260.",
        "Missing: you never answered the second question.",
        "Unsafe: it says the files were deleted but no delete ran.",
    ]:
        assert fr._flag_is_material(flag) is True, flag
    assert fr._flag_is_material("") is False  # blank => ship as-is


def test_normalizer_preserves_final_review():
    assert _normalize_preset({"final_review": True})["final_review"] is True
    assert _normalize_preset({})["final_review"] is False
    flat = normalize_moa_config({"presets": {"p": {"final_review": True}}, "default_preset": "p"})
    assert flat["final_review"] is True
    assert flat["presets"]["p"]["final_review"] is True
