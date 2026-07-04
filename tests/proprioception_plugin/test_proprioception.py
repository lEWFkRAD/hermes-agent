"""Tests for the proprioception plugin (settings, collector, heartbeat, tool).

Windows note: safe to run standalone; module globals are reset by the
autouse fixture, so the file should also survive full-tree runs.
"""

from __future__ import annotations

import threading
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
        cache_ttl_seconds=1,
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


def _enable_config(monkeypatch):
    import hermes_cli.config as config_mod

    monkeypatch.setattr(
        config_mod, "load_config_readonly", lambda: {"proprioception": {"enabled": True}}
    )


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


def test_settings_config_read_failure_is_disabled_and_warns_once(monkeypatch, caplog):
    import logging

    import hermes_cli.config as config_mod
    import plugins.proprioception.settings as settings_mod

    def boom():
        raise RuntimeError("config exploded")

    monkeypatch.setattr(config_mod, "load_config_readonly", boom)
    monkeypatch.setattr(settings_mod, "_warned_config_failure", False)
    with caplog.at_level(logging.WARNING):
        assert get_settings()["enabled"] is False
        assert get_settings()["enabled"] is False
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1  # latched, not per-call


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


def test_stale_while_revalidate_does_not_block_second_caller(monkeypatch):
    """A slow refresh must not serialize other sessions' prologues."""
    payload = _dashboard_payload({"agg": "ok"})
    release = threading.Event()

    def slow_fetch(url, timeout):
        release.wait(5)
        return payload

    cfg = _settings(cache_ttl_seconds=0.001 if False else 1)
    # Prime the cache with a fast fetch.
    _install_dashboard(monkeypatch, payload)
    collector.get_snapshot(cfg)
    # Expire it and make the next fetch hang.
    monkeypatch.setattr(collector, "_fetch_dashboard", slow_fetch)
    monkeypatch.setattr(collector, "_CACHED", collector.Snapshot(
        fetched_at=time.monotonic() - 100, dashboard=payload))

    slow_started = threading.Event()

    def refresher():
        slow_started.set()
        collector.get_snapshot(cfg)

    t = threading.Thread(target=refresher)
    t.start()
    slow_started.wait(2)
    time.sleep(0.05)  # let the refresher enter the fetch
    start = time.monotonic()
    snap = collector.get_snapshot(cfg)  # must be served stale immediately
    elapsed = time.monotonic() - start
    release.set()
    t.join(timeout=5)
    assert elapsed < 1.0, f"second caller blocked {elapsed:.2f}s behind the fetch"
    assert snap.dashboard is not None


def test_grace_window_marks_data_stale(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    collector.get_snapshot(_settings())
    monkeypatch.setattr(collector, "_CACHED", None)
    monkeypatch.setattr(collector, "_LAST_GOOD_AT", time.monotonic() - 30)
    _install_dashboard(monkeypatch, ConnectionError("refused"))
    snap = collector.get_snapshot(_settings(stale_grace_seconds=90))
    assert snap.dashboard is not None  # grace served the old data
    assert snap.dashboard_stale_for >= 30  # ...but discloses its age
    assert snap.dashboard_error  # ...and keeps the error visible


def test_fingerprint_ignores_detail_and_needs_noise():
    a = collector.Snapshot(
        fetched_at=0,
        dashboard=_dashboard_payload({"gpu": "ok"}, needs=[{"sev": "warn", "text": "14 hours"}]),
    )
    b = collector.Snapshot(
        fetched_at=1,
        dashboard=_dashboard_payload({"gpu": "ok"}, needs=[{"sev": "warn", "text": "15 hours"}]),
    )
    b.dashboard["systems"][0]["detail"] = "38C, 2.1 GiB free"
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


# ---------------------------------------------------------------------------
# heartbeat
# ---------------------------------------------------------------------------

def _beat(session="s1", history=None, cfg=None):
    return heartbeat.build_heartbeat(
        session_id=session,
        conversation_history=history,
        settings=cfg or _settings(),
    )


def _refetch(monkeypatch, payload_or_exc):
    """Expire the collector cache and point it at new data."""
    collector.reset_cache_for_tests()
    return _install_dashboard(monkeypatch, payload_or_exc)


def test_all_green_baseline_is_silent(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok", "vision": "ok"}))
    assert _beat() is None  # nothing to report; silence is the baseline
    _refetch(monkeypatch, _dashboard_payload({"agg": "ok", "vision": "ok"}))
    assert _beat() is None  # steady state stays silent


def test_baseline_with_signal_fires_and_is_fenced(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok", "vision": "warn"}))
    first = _beat()
    assert first is not None
    assert first.startswith("<host-telemetry>") and first.rstrip().endswith("</host-telemetry>")
    assert "not the user's words" in first
    assert "label-vision" in first
    # No second-person machine talk.
    assert "your own machine" not in first.lower()


def test_state_transition_fires_names_system_and_rotates_frames(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"vision": "ok"}))
    assert _beat() is None  # green baseline, silent
    _refetch(monkeypatch, _dashboard_payload({"vision": "down"}))
    beat = _beat(cfg=_settings(min_interval_seconds=10_000))  # degradation bypasses limit
    assert beat is not None
    assert "label-vision" in beat and "DOWN" in beat


def test_flapping_system_cannot_bypass_rate_limit_twice(monkeypatch):
    cfg = _settings(min_interval_seconds=10_000)
    _install_dashboard(monkeypatch, _dashboard_payload({"tg": "ok"}))
    _beat(cfg=cfg)
    _refetch(monkeypatch, _dashboard_payload({"tg": "warn"}))
    assert _beat(cfg=cfg) is not None  # first edge: bypass fires
    _refetch(monkeypatch, _dashboard_payload({"tg": "ok"}))
    assert _beat(cfg=cfg) is None  # recovery: rate-limited
    _refetch(monkeypatch, _dashboard_payload({"tg": "warn"}))
    assert _beat(cfg=cfg) is None  # same edge again inside bypass memory: no bypass


def test_recovery_respects_rate_limit_then_reports(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"vision": "down"}))
    cfg = _settings(min_interval_seconds=10_000)
    _beat(cfg=cfg)  # baseline (has signal)
    _refetch(monkeypatch, _dashboard_payload({"vision": "ok"}))
    # recovery (down -> ok) is not a degradation; rate limit suppresses it...
    assert _beat(cfg=cfg) is None
    # ...but the un-emitted change is retained, and reports once the window opens
    _refetch(monkeypatch, _dashboard_payload({"vision": "ok"}))
    beat = _beat(cfg=_settings(min_interval_seconds=0))
    assert beat is not None and "label-vision" in beat


def test_flap_within_rate_window_nets_to_silence(monkeypatch):
    cfg_limited = _settings(min_interval_seconds=10_000)
    _install_dashboard(monkeypatch, _dashboard_payload({"x": "warn"}))
    _beat(cfg=cfg_limited)  # baseline w/ signal
    _refetch(monkeypatch, _dashboard_payload({"x": "ok"}))
    assert _beat(cfg=cfg_limited) is None  # suppressed recovery
    _refetch(monkeypatch, _dashboard_payload({"x": "warn"}))
    # back to the original state: no net change; must stay silent even
    # with the rate window wide open
    assert _beat(cfg=_settings(min_interval_seconds=0)) is None


def test_sensor_outage_bridge_does_not_swallow_recovery(monkeypatch):
    """down -> (dashboard outage) -> ok must still report the recovery."""
    cfg = _settings(min_interval_seconds=0, stale_grace_seconds=0)
    _install_dashboard(monkeypatch, _dashboard_payload({"vision": "down"}))
    _beat(cfg=cfg)  # baseline: vision down
    _refetch(monkeypatch, ConnectionError("refused"))
    lost = _beat(cfg=cfg)
    assert lost is not None and "status feed" in lost  # sensor loss reported
    _refetch(monkeypatch, _dashboard_payload({"vision": "ok"}))
    back = _beat(cfg=cfg)
    assert back is not None
    assert "label-vision" in back  # the down->ok transition survived the outage
    assert "back online" in back


def test_gateway_state_change_renders_named_line(monkeypatch):
    cfg = _settings(min_interval_seconds=0)
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    monkeypatch.setattr(collector, "_fetch_gateway_status", lambda: {"state": "running"})
    _beat(cfg=cfg)
    collector.reset_cache_for_tests()
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    monkeypatch.setattr(collector, "_fetch_gateway_status", lambda: {"state": "draining"})
    beat = _beat(cfg=cfg)
    assert beat is not None
    assert "gateway: running -> draining" in beat  # never an empty change body


def test_needs_text_churn_emits_nothing(monkeypatch):
    cfg = _settings(min_interval_seconds=0)
    _install_dashboard(
        monkeypatch,
        _dashboard_payload({"agg": "ok"}, needs=[{"sev": "warn", "text": "stale 14h"}]),
    )
    _beat(cfg=cfg)
    _refetch(
        monkeypatch,
        _dashboard_payload({"agg": "ok"}, needs=[{"sev": "warn", "text": "stale 15h"}]),
    )
    assert _beat(cfg=cfg) is None  # churn in operator text is not a state change


def test_context_upward_crossing_fires_downward_is_silent(monkeypatch):
    cfg = lambda: _settings(context_window=2048, min_interval_seconds=0)  # noqa: E731
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    small = [{"role": "user", "content": "x" * 400}]
    assert _beat(history=small, cfg=cfg()) is None  # green baseline, low fill
    _refetch(monkeypatch, _dashboard_payload({"agg": "ok"}))
    big = [{"role": "user", "content": "x" * 6000}]  # ~1500/2048 = 73%
    up = _beat(history=big, cfg=cfg())
    assert up is not None and "context fill climbed past" in up
    _refetch(monkeypatch, _dashboard_payload({"agg": "ok"}))
    # Compression dropped fill back down: silent re-bucket.
    assert _beat(history=small, cfg=cfg()) is None
    _refetch(monkeypatch, _dashboard_payload({"agg": "ok"}))
    # Climb again: reports again.
    again = _beat(history=big, cfg=cfg())
    assert again is not None and "context fill" in again


def test_slow_creep_through_threshold_still_reports(monkeypatch):
    cfg = lambda: _settings(context_window=1000, min_interval_seconds=0)  # noqa: E731
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    # 40% — below every threshold: green baseline, silent
    low = [{"role": "user", "content": "x" * (400 * 4)}]
    assert _beat(history=low, cfg=cfg()) is None
    _refetch(monkeypatch, _dashboard_payload({"agg": "ok"}))
    # 51% — inside the hysteresis band (50% + 2%): silent, bucket must NOT advance
    mid = [{"role": "user", "content": "x" * (510 * 4)}]
    assert _beat(history=mid, cfg=cfg()) is None
    _refetch(monkeypatch, _dashboard_payload({"agg": "ok"}))
    # 55% — clears the band: the 50% crossing must be reported, not swallowed
    over = [{"role": "user", "content": "x" * (550 * 4)}]
    beat = _beat(history=over, cfg=cfg())
    assert beat is not None and "context fill climbed past 50%" in beat


def test_mode_off_is_silent(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "warn"}))
    assert _beat(cfg=_settings(heartbeat="off")) is None


def test_mode_always_emits_every_turn_with_rotation(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    cfg = _settings(heartbeat="always")
    first = _beat(cfg=cfg)
    second = _beat(cfg=cfg)
    third = _beat(cfg=cfg)
    assert first and second and third
    assert "First status reading" in first
    assert "Periodic reading" in second
    assert second != third  # frames rotate; no byte-identical repeats


def test_sessions_are_isolated(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "warn"}))
    assert _beat(session="a") is not None
    assert _beat(session="b") is not None  # b gets its own baseline
    assert _beat(session="a") is None


def test_truncation_keeps_fence_intact(monkeypatch):
    _install_dashboard(
        monkeypatch,
        _dashboard_payload({f"sys{i}": "warn" for i in range(30)}),
    )
    # budget must exceed the fixed fence+system-note overhead (~341 chars) with
    # room for a truncated body; 500 exercises truncation without starving it.
    beat = _beat(cfg=_settings(max_chars=500))
    assert beat is not None and len(beat) <= 500
    assert beat.startswith("<host-telemetry>")
    assert beat.rstrip().endswith("</host-telemetry>")


def test_heartbeat_never_raises(monkeypatch):
    _install_dashboard(monkeypatch, {"systems": [None, 42, {"id": None}], "needs": None})
    from plugins.proprioception import _pre_llm_call

    _enable_config(monkeypatch)
    result = _pre_llm_call(session_id="s", conversation_history=None, is_first_turn=True)
    assert result is None or isinstance(result, dict)


def test_falsy_session_id_gets_thread_scoped_key(monkeypatch):
    from plugins.proprioception import _pre_llm_call

    _enable_config(monkeypatch)
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "warn"}))
    r1 = _pre_llm_call(session_id=None, conversation_history=None)
    assert r1 is not None  # got its own baseline, not swallowed by a shared key
    assert f"no-session-{threading.get_ident()}" in heartbeat._SESSIONS


# ---------------------------------------------------------------------------
# body_state tool
# ---------------------------------------------------------------------------

def test_tool_summary_lists_attention_only(monkeypatch):
    _enable_config(monkeypatch)
    _install_dashboard(
        monkeypatch,
        _dashboard_payload(
            {"agg": "ok", "vision": "down"},
            needs=[{"sev": "warn", "text": "Vision died. Run schtasks /run /tn Fix-It now."}],
        ),
    )
    out = handle_body_state({"detail": "summary"})
    assert "label-vision" in out
    assert "label-agg" not in out  # ok systems stay out of the summary
    # Operator text is labeled and trimmed to its first sentence.
    assert "addressed to the operator" in out
    assert "Vision died." in out and "schtasks" not in out


def test_tool_full_groups_by_category(monkeypatch):
    _enable_config(monkeypatch)
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    out = handle_body_state({"detail": "full"})
    assert "AI models:" in out
    assert "label-agg" in out
    assert out.startswith("Host status report.")


def test_tool_reports_sensor_outage(monkeypatch):
    _enable_config(monkeypatch)
    _install_dashboard(monkeypatch, ConnectionError("refused"))
    out = handle_body_state({})
    assert "unreachable" in out.lower()


def test_tool_discloses_stale_grace_data(monkeypatch):
    _enable_config(monkeypatch)
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    collector.get_snapshot(_settings())
    monkeypatch.setattr(collector, "_CACHED", None)
    monkeypatch.setattr(collector, "_LAST_GOOD_AT", time.monotonic() - 45)
    _install_dashboard(monkeypatch, ConnectionError("refused"))
    out = handle_body_state({})
    assert "live fetch is failing" in out
    assert "old" in out  # age disclosed


def test_tool_check_fn_fail_closed(monkeypatch):
    import hermes_cli.config as config_mod

    from plugins.proprioception.tools import check_body_state_available

    monkeypatch.setattr(config_mod, "load_config_readonly", lambda: {})
    assert check_body_state_available() is False


def test_cold_start_sensor_miss_is_silent_then_recovers(monkeypatch):
    """First-ever reading failing to reach the dashboard must not emit a
    false 'feed unreachable' baseline; a later real loss still reports."""
    cfg = _settings(stale_grace_seconds=0)
    _install_dashboard(monkeypatch, ConnectionError("cold miss"))
    assert _beat(cfg=cfg) is None  # cold miss: silent
    _refetch(monkeypatch, _dashboard_payload({"agg": "ok"}))
    assert _beat(cfg=cfg) is not None  # feed coming online IS a transition


# ---------------------------------------------------------------------------
# fallback awareness (consumes core turn-telemetry last_turn record)
# ---------------------------------------------------------------------------

_ON = {"has_data": True, "was_fallback": False, "provider": "moa",
       "primary_model": "moa-personal", "primary_provider": "moa"}
_OFF = {"has_data": True, "was_fallback": True, "provider": "anthropic",
        "primary_model": "moa-personal", "primary_provider": "moa"}


def _beat_lt(session, last_turn, cfg=None):
    return heartbeat.build_heartbeat(
        session_id=session, conversation_history=[],
        settings=cfg or _settings(min_interval_seconds=10_000), last_turn=last_turn)


def test_fallback_transition_emits_despite_rate_limit(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    assert _beat_lt("f1", _ON) is None                    # on primary, green -> silent
    _refetch(monkeypatch, _dashboard_payload({"agg": "ok"}))
    beat = _beat_lt("f1", _OFF)                            # fell back -> emits (bypass)
    assert beat is not None
    assert "fallback runtime" in beat and "moa-personal" in beat and "anthropic" in beat


def test_fallback_not_repeated_while_still_degraded(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    _beat_lt("f2", _ON)
    _refetch(monkeypatch, _dashboard_payload({"agg": "ok"}))
    assert _beat_lt("f2", _OFF) is not None                # transition
    _refetch(monkeypatch, _dashboard_payload({"agg": "ok"}))
    assert _beat_lt("f2", _OFF) is None                    # still off -> no repeat


def test_back_on_primary_emits_recovery(monkeypatch):
    # recovery is announced only if the fallback was announced first:
    # on-primary baseline -> fell back (emit) -> back on primary (recovery).
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    assert _beat_lt("f3", _ON) is None                     # on-primary baseline
    _refetch(monkeypatch, _dashboard_payload({"agg": "ok"}))
    assert _beat_lt("f3", _OFF) is not None                # fell back (announced)
    _refetch(monkeypatch, _dashboard_payload({"agg": "ok"}))
    beat = _beat_lt("f3", _ON)                             # recovered
    assert beat is not None and "back on your primary" in beat.lower()


def test_empty_last_turn_never_triggers_fallback(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    assert _beat_lt("f4", {"has_data": False}) is None
    _refetch(monkeypatch, _dashboard_payload({"agg": "ok"}))
    assert _beat_lt("f4", None) is None


def test_session_starting_on_fallback_is_reported_next_turn(monkeypatch):
    # first turn already off-primary: baseline stays silent about it, but the
    # next reading reports the True->False transition (not silently normalized).
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    assert _beat_lt("f5", _OFF) is None                    # baseline, green -> silent
    _refetch(monkeypatch, _dashboard_payload({"agg": "ok"}))
    beat = _beat_lt("f5", _OFF)
    assert beat is not None and "fallback runtime" in beat  # caught on turn 2


# ---------------------------------------------------------------------------
# continuity / suspension gap
# ---------------------------------------------------------------------------

def _backdate_last_turn(session: str, seconds_ago: float) -> None:
    """Age the session's wall stamp so the next beat sees a suspension gap."""
    heartbeat._SESSIONS[session].last_turn_wall = time.time() - seconds_ago


def test_gap_below_threshold_is_silent(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    cfg = _settings(gap_report_seconds=1800)
    assert _beat(session="g1", cfg=cfg) is None       # green baseline records a stamp
    _backdate_last_turn("g1", 600)                    # 10 min < 30 min threshold
    _refetch(monkeypatch, _dashboard_payload({"agg": "ok"}))
    assert _beat(session="g1", cfg=cfg) is None        # no gap line


def test_gap_over_threshold_emits_and_names_duration(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    cfg = _settings(gap_report_seconds=1800)
    assert _beat(session="g2", cfg=cfg) is None        # green baseline
    _backdate_last_turn("g2", 3 * 3600)                # dormant 3h
    _refetch(monkeypatch, _dashboard_payload({"agg": "ok"}))
    beat = _beat(session="g2", cfg=cfg)
    assert beat is not None
    assert "since your last turn" in beat and "3.0 h" in beat
    assert beat.startswith("<host-telemetry>") and beat.rstrip().endswith("</host-telemetry>")


def test_gap_emits_once_then_quiet(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    cfg = _settings(gap_report_seconds=1800)
    _beat(session="g3", cfg=cfg)                        # baseline
    _backdate_last_turn("g3", 7200)                     # 2h
    _refetch(monkeypatch, _dashboard_payload({"agg": "ok"}))
    assert _beat(session="g3", cfg=cfg) is not None     # reports the gap
    _refetch(monkeypatch, _dashboard_payload({"agg": "ok"}))
    assert _beat(session="g3", cfg=cfg) is None         # stamp advanced -> no repeat


def test_gap_bypasses_rate_limit(monkeypatch):
    # Baseline carries a signal so it emits and sets last_emit; then a big gap
    # must still fire despite a 10k-second floor.
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "warn"}))
    cfg = _settings(gap_report_seconds=1800, min_interval_seconds=10_000)
    assert _beat(session="g4", cfg=cfg) is not None     # baseline emitted (warn)
    _backdate_last_turn("g4", 4 * 3600)
    _refetch(monkeypatch, _dashboard_payload({"agg": "warn"}))  # no transition, only the gap
    beat = _beat(session="g4", cfg=cfg)
    assert beat is not None and "since your last turn" in beat


def test_backward_clock_never_reports_gap(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"agg": "ok"}))
    cfg = _settings(gap_report_seconds=60)
    _beat(session="g5", cfg=cfg)                        # baseline
    # Clock jumped backward: the stamp is in the future relative to now.
    heartbeat._SESSIONS["g5"].last_turn_wall = time.time() + 5000
    _refetch(monkeypatch, _dashboard_payload({"agg": "ok"}))
    assert _beat(session="g5", cfg=cfg) is None         # non-positive delta ignored


def test_gap_coexists_with_system_transition(monkeypatch):
    _install_dashboard(monkeypatch, _dashboard_payload({"vision": "ok"}))
    cfg = _settings(gap_report_seconds=1800)
    assert _beat(session="g6", cfg=cfg) is None         # green baseline
    _backdate_last_turn("g6", 2 * 3600)
    _refetch(monkeypatch, _dashboard_payload({"vision": "down"}))
    beat = _beat(session="g6", cfg=cfg)
    assert beat is not None
    assert "label-vision" in beat and "DOWN" in beat    # transition renders
    assert "since your last turn" in beat               # ...and so does the gap


def test_settings_gap_report_seconds_sanitized(monkeypatch):
    import hermes_cli.config as config_mod

    monkeypatch.setattr(
        config_mod, "load_config_readonly",
        lambda: {"proprioception": {"enabled": True, "gap_report_seconds": "nope"}},
    )
    assert get_settings()["gap_report_seconds"] == DEFAULTS["gap_report_seconds"]  # garbage -> default
    monkeypatch.setattr(
        config_mod, "load_config_readonly",
        lambda: {"proprioception": {"enabled": True, "gap_report_seconds": -50}},
    )
    assert get_settings()["gap_report_seconds"] == 0  # negative floored
