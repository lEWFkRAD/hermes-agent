"""Tests for the proprioception plugin (settings, collector, heartbeat, tool).

Windows note: run this file in isolation (the full agent tree has known
cross-file order pollution on native Windows; these tests are self-contained).
"""

from __future__ import annotations

import time
from typing import Any, Dict

import pytest

from plugins.proprioception import collector, heartbeat
from plugins.proprioception.settings import DEFAULTS, get_settings
from plugins.proprioception.tools import handle_body_state


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------

def _settings(**overrides: Any) -> Dict[str, Any]:
    cfg = dict(DEFAULTS)
    cfg.update(
        enabled=True,
        cache_ttl_seconds=1,  # floor in sanitizer; raw dict here so any value works
        min_interval_seconds=0,
    )
    cfg.update(overrides)
    return cfg


def _dashboard_payload(states: Dict[str, str], needs=None) -> Dict[str, Any]:
    return {
        "verdict": "ok" if all(s in ("ok", "info") for s in states.values()) else "attention",
        "needs": needs or [],
        "systems": [
            {"id": sid, "state": state, "label": f"label-{sid}", "detail": "d", "cat": "AI models"}
            for sid, state in states.items()
        ],
        "count": len(states),
        "checked": "00:00:00",
    }


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    collector.reset_cache_for_tests()
    heartbeat.reset_for_tests()
    # Never let a test hit the real gateway state file or dashboard.
    monkeypatch.setattr(collector, "_fetch_gateway_status", lambda: {"state": "running"})
    yield
    collector.reset_cache_for_tests()
    heartbeat.reset_for_tests()


def _install_dashboard(monkeypatch, payload_or_exc):
    calls = {"n": 0}

    def fake_fetch(url, timeout):
        calls["n"] += 1
        if isinstance(payload_or_exc, Exception):
            raise payload_or_exc
        return payload_or_exc

    monkeypatch.setattr(collector, "_fetch_dashboard", fake_fetch)
    return calls


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------

def test_settings_default_disabled(monkeypatch):
    import hermes_cli.config as config_mod

    monkeypatch.setattr(config_mod, "load_config_readonly", lambda: {})
    cfg = get_settings()
    assert cfg["enabled"] is False
    assert cfg["heartbeat"] == "delta"


def test_settings_sanitizes_garbage(monkeypatch):
    import hermes_cli.config as config_mod

    monkeypatch.setattr(
        config_mod,
        "load_config_readonly",
        lambda: {
            "proprioception": {
                "enabled": 1,
                "heartbeat": "SCREAM",
                "min_interval_seconds": "not-a-number",
                "cache_ttl_seconds": -5,
                "max_chars": 3,
            }
        },
    )
    cfg = get_settings()
    assert cfg["enabled"] is True
    assert cfg["heartbeat"] == "delta"  # invalid mode falls back
    assert cfg["min_interval_seconds"] == DEFAULTS["min_interval_seconds"]
    assert cfg["cache_ttl_seconds"] == 1  # floored
    assert cfg["max_chars"] == 100  # floored


def test_settings_config_read_failure_is_disabled(monkeypatch):
    import hermes_cli.config as config_mod

    def boom():
        raise RuntimeError("config exploded")

    monkeypatch.setattr(config_mod, "load_config_readonly", boom)
    assert get_settings()["enabled"] is False


def test_settings_non_dict_block_ignored(monkeypatch):
    import hermes_cli.config as config_mod

    monkeypatch.setattr(
        config_mod, "load_config_readonly", lambda: {"proprioception": "yes please"}
    )
    assert get_settings()["enabled"] is False


# ---------------------------------------------------------------------------
# collector
# ---------------------------------------------------------------------------

def test_snapshot_caches_within_ttl(monkeypatch):
    calls = _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    cfg = _settings(cache_ttl_seconds=60)
    collector.get_snapshot(cfg)
    collector.get_snapshot(cfg)
    assert calls["n"] == 1


def test_snapshot_sensor_failure_is_data_not_exception(monkeypatch):
    _install_dashboard(monkeypatch, ConnectionError("refused"))
    snap = collector.get_snapshot(_settings())
    assert snap.dashboard is None
    assert "ConnectionError" in snap.dashboard_error
    assert "dashboard" in snap.sensors_down


def test_fingerprint_ignores_detail_noise(monkeypatch):
    a = collector.Snapshot(fetched_at=0, dashboard=_dashboard_payload({"gpu": "ok"}))
    b = collector.Snapshot(fetched_at=1, dashboard=_dashboard_payload({"gpu": "ok"}))
    b.dashboard["systems"][0]["detail"] = "38C, 2.1 GiB free"  # detail differs
    assert collector.fingerprint(a) == collector.fingerprint(b)


def test_fingerprint_catches_state_change():
    a = collector.Snapshot(fetched_at=0, dashboard=_dashboard_payload({"vision": "ok"}))
    b = collector.Snapshot(fetched_at=1, dashboard=_dashboard_payload({"vision": "down"}))
    assert collector.fingerprint(a) != collector.fingerprint(b)


def test_diff_systems_reports_transitions_and_absences():
    a = collector.Snapshot(
        fetched_at=0, dashboard=_dashboard_payload({"vision": "ok", "agg": "ok"})
    )
    b = collector.Snapshot(fetched_at=1, dashboard=_dashboard_payload({"vision": "down"}))
    transitions = collector.diff_systems(a, b)
    assert ("label-agg", "ok", "absent") in transitions
    assert ("label-vision", "ok", "down") in transitions
    assert collector.has_degradation(transitions)


# ---------------------------------------------------------------------------
# heartbeat
# ---------------------------------------------------------------------------

def _beat(session="s1", history=None, cfg=None):
    return heartbeat.build_heartbeat(
        session_id=session,
        is_first_turn=False,
        conversation_history=history,
        settings=cfg or _settings(),
    )


def test_baseline_fires_once_then_silence(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok", "vision": "ok"}))
    first = _beat()
    assert first is not None
    assert "baseline" in first.lower()
    assert "2" in first  # system count
    collector.reset_cache_for_tests()  # force refetch; same payload
    assert _beat() is None  # steady state costs zero tokens


def test_state_transition_fires_and_names_the_system(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"vision": "ok"}))
    _beat()
    collector.reset_cache_for_tests()
    _install_dashboard(monkeypatch, _dashboard_payload({"vision": "down"}))
    beat = _beat(cfg=_settings(min_interval_seconds=10_000))  # degradation bypasses limit
    assert beat is not None
    assert "label-vision" in beat
    assert "DOWN" in beat


def test_recovery_respects_rate_limit_then_reports(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"vision": "down"}))
    cfg = _settings(min_interval_seconds=10_000)
    _beat(cfg=cfg)
    collector.reset_cache_for_tests()
    _install_dashboard(monkeypatch, _dashboard_payload({"vision": "ok"}))
    # recovery (down -> ok) is not a degradation; rate limit suppresses it...
    assert _beat(cfg=cfg) is None
    # ...but the un-emitted change is retained, and reports once the window opens
    collector.reset_cache_for_tests()
    _install_dashboard(monkeypatch, _dashboard_payload({"vision": "ok"}))
    beat = _beat(cfg=_settings(min_interval_seconds=0))
    assert beat is not None and "label-vision" in beat


def test_single_missed_poll_is_absorbed_by_grace_window(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    _beat()
    # Fetch fails, but the last good reading is fresh -> no loss chatter.
    monkeypatch.setattr(collector, "_CACHED", None)
    _install_dashboard(monkeypatch, ConnectionError("refused"))
    assert _beat() is None


def test_sustained_sensor_loss_reported_as_state(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    _beat()
    # Age the last good reading past the grace window, then fail the fetch.
    monkeypatch.setattr(collector, "_CACHED", None)
    monkeypatch.setattr(collector, "_LAST_GOOD_AT", time.time() - 10_000)
    _install_dashboard(monkeypatch, ConnectionError("refused"))
    beat = _beat()
    assert beat is not None
    assert "sensor" in beat.lower()


def test_context_bucket_crossing_fires(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    small = [{"role": "user", "content": "x" * 400}]  # ~100 tokens
    _beat(history=small, cfg=_settings(context_window=2048))
    collector.reset_cache_for_tests()
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    big = [{"role": "user", "content": "x" * 6000}]  # ~1500 tokens of 2048 = 73%
    beat = _beat(history=big, cfg=_settings(context_window=2048))
    assert beat is not None
    assert "context fill" in beat


def test_mode_off_is_silent(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    assert _beat(cfg=_settings(heartbeat="off")) is None


def test_mode_always_emits_every_turn(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    cfg = _settings(heartbeat="always")
    assert _beat(cfg=cfg) is not None
    assert _beat(cfg=cfg) is not None


def test_sessions_are_isolated(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    assert _beat(session="a") is not None
    assert _beat(session="b") is not None  # b gets its own baseline
    assert _beat(session="a") is None


def test_truncation_respects_max_chars(monkeypatch):
    _install_dashboard(
        monkeypatch,
        _dashboard_payload({f"sys{i}": "ok" for i in range(30)}),
    )
    beat = _beat(cfg=_settings(max_chars=120))
    assert beat is not None and len(beat) <= 120


def test_heartbeat_never_raises(monkeypatch):
    # Even a hostile payload shape must not raise out of build_heartbeat's caller.
    _install_dashboard(monkeypatch, {"systems": [None, 42, {"id": None}], "needs": None})
    from plugins.proprioception import _pre_llm_call

    import hermes_cli.config as config_mod

    monkeypatch.setattr(
        config_mod, "load_config_readonly", lambda: {"proprioception": {"enabled": True}}
    )
    result = _pre_llm_call(session_id="s", conversation_history=None, is_first_turn=True)
    assert result is None or isinstance(result, dict)


# ---------------------------------------------------------------------------
# body_state tool
# ---------------------------------------------------------------------------

def test_tool_summary_lists_attention_only(monkeypatch):
    import hermes_cli.config as config_mod

    monkeypatch.setattr(
        config_mod, "load_config_readonly", lambda: {"proprioception": {"enabled": True}}
    )
    _install_dashboard(
        monkeypatch,
        _dashboard_payload({"agg": "ok", "vision": "down"}, needs=[{"sev": "warn", "text": "vision died"}]),
    )
    out = handle_body_state({"detail": "summary"})
    assert "attention" in out.lower()
    assert "label-vision" in out
    assert "label-agg" not in out  # ok systems stay out of the summary


def test_tool_full_groups_by_category(monkeypatch):
    import hermes_cli.config as config_mod

    monkeypatch.setattr(
        config_mod, "load_config_readonly", lambda: {"proprioception": {"enabled": True}}
    )
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    out = handle_body_state({"detail": "full"})
    assert "AI models:" in out
    assert "label-agg" in out


def test_tool_reports_sensor_outage(monkeypatch):
    import hermes_cli.config as config_mod

    monkeypatch.setattr(
        config_mod, "load_config_readonly", lambda: {"proprioception": {"enabled": True}}
    )
    _install_dashboard(monkeypatch, ConnectionError("refused"))
    out = handle_body_state({})
    assert "unreachable" in out.lower()


def test_tool_check_fn_fail_closed(monkeypatch):
    import hermes_cli.config as config_mod

    from plugins.proprioception.tools import check_body_state_available

    monkeypatch.setattr(config_mod, "load_config_readonly", lambda: {})
    assert check_body_state_available() is False
