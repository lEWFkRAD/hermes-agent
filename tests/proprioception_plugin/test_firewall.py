"""Tests for the output-side honesty firewall.

The firewall is the control the adversary panel proved was missing: injection-side
rules are pleas to a weak model; this scans the OUTPUT and removes machine-state
narration before it reaches a user — but only on a turn where a self-signal fired,
and never at the cost of gutting a legitimate reply.
"""

from __future__ import annotations

import pytest

from plugins.proprioception import firewall
from plugins.proprioception.firewall import scrub, mark_signal_fired, _consume_signal


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    firewall._SIGNAL_FIRED.clear()
    # never write the firewall log during tests
    monkeypatch.setattr(firewall, "_log_activation", lambda *_a, **_k: None)
    yield
    firewall._SIGNAL_FIRED.clear()


# --- the clean case is sacred: normal replies must pass through untouched ---

def test_clean_reply_untouched():
    txt = "Your March deposits reconcile to the bank statement. Net difference is zero."
    cleaned, note = scrub(txt)
    assert cleaned is None
    assert note == "no leak"


def test_technical_reply_with_machine_words_but_no_self_narration():
    # "the server" about a CLIENT's server, not the model narrating itself
    txt = "The client's QuickBooks server exports a CSV; import that into the workpaper."
    cleaned, _ = scrub(txt)
    assert cleaned is None  # 'server' alone isn't a leak; only "my server" is


# --- the panel's exact scenario: surgical clause-level redaction ---

def test_panel_example_clause_salvage():
    txt = "You're welcome, Susan! Bit of a rough one on my end today but glad we got it sorted."
    cleaned, note = scrub(txt)
    assert cleaned is not None
    assert "on my end" not in cleaned.lower()
    assert "rough one" not in cleaned.lower()
    assert "glad we got it sorted" in cleaned.lower()  # legit content preserved
    assert "You're welcome, Susan!" in cleaned
    assert note.startswith("redacted")


def test_i_am_variant_caught_not_just_contraction():
    txt = "The reconciliation balances to the penny, but I am running slow on my end today."
    cleaned, _ = scrub(txt)
    assert cleaned is not None
    assert "running slow" not in cleaned.lower()
    assert "balances to the penny" in cleaned.lower()


def test_semicolon_clause_salvage():
    txt = "The trial balance ties out; my GPU is under load right now."
    cleaned, _ = scrub(txt)
    # first clause is clean, second is a leak → keep the first
    assert cleaned is not None
    assert "trial balance ties out" in cleaned.lower()
    assert "gpu" not in cleaned.lower()


# --- fail-open: a reply that is ENTIRELY leak must not be gutted/emptied ---

def test_whole_reply_leak_fails_open_not_emptied():
    txt = "My GPU is overloaded and I fell back to the cloud this turn."
    cleaned, note = scrub(txt)
    assert cleaned is None  # pass original through rather than send an empty reply
    assert "MAJOR LEAK" in note  # but flag it loudly


def test_redaction_never_returns_empty():
    txt = "On my end, feeling slow today."
    cleaned, note = scrub(txt)
    # nothing substantive would remain → do not send an empty string
    assert cleaned is None


# --- leak vocabulary coverage (the vectors the panel named) ---

@pytest.mark.parametrize("leak", [
    "I fell back to the cloud this turn, but your P&L is attached.",
    "Your return is ready; my operating regime is strained though.",
    "Done! My vision system is down but the numbers are in.",
    "The estimate is sent, though my context window is nearly full.",
])
def test_known_leak_vectors_are_caught(leak):
    cleaned, note = scrub(leak)
    # either surgically cleaned or flagged as major-leak; never silently "no leak"
    assert note != "no leak"


# --- the per-turn signal flag gate ---

def test_signal_flag_round_trip():
    mark_signal_fired("s1")
    assert _consume_signal("s1") is True
    assert _consume_signal("s1") is False  # consumed, cleared


def test_transform_only_acts_when_signal_fired(monkeypatch):
    import hermes_cli.config as config_mod
    monkeypatch.setattr(config_mod, "load_config_readonly",
                        lambda: {"proprioception": {"enabled": True}})
    from plugins.proprioception.firewall import transform_llm_output
    leaky = "You're welcome! Bit of a rough one on my end but done."
    # no signal fired this turn → firewall is inert even on leaky text
    assert transform_llm_output(response_text=leaky, session_id="s2", platform="telegram") is None
    # signal fired → firewall acts
    mark_signal_fired("s2")
    out = transform_llm_output(response_text=leaky, session_id="s2", platform="telegram")
    assert out is not None and "on my end" not in out.lower()


def test_disabled_plugin_firewall_inert(monkeypatch):
    import hermes_cli.config as config_mod
    monkeypatch.setattr(config_mod, "load_config_readonly", lambda: {})
    from plugins.proprioception.firewall import transform_llm_output
    mark_signal_fired("s3")
    assert transform_llm_output(response_text="rough one on my end", session_id="s3") is None
