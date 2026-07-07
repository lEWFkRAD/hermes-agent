"""Pluggable believed-state feeds for AMDP.

AMDP needs a view of the system's current state to satisfy the paper's step-1
precondition (do not plan blind). The *source* of that state is deliberately
pluggable so AMDP is a standalone orchestration-layer feature, not one coupled
to any particular monitoring plugin:

* ``gateway``       — universal. Reads the gateway runtime status file that
                      every Hermes install writes. No external dependencies.
                      This is the default and the upstream-safe baseline.
* ``proprioception``— optional enrichment. If the proprioception plugin is
                      installed, use its richer snapshot (external system
                      dashboard + attention states + staleness). Falls back to
                      the gateway feed if the plugin is absent.
* ``auto``          — proprioception if importable, else gateway (the default).

Every feed returns the same believed-state contract consumed by the planner::

    {brief, sensors_down, staleness_s, verdict, gateway_state, system_count,
     dashboard_up}

Only ``"gateway-status"`` appearing in ``sensors_down`` (or staleness beyond the
configured max) blinds the planner into refusing; a richer feed's enrichment
being unavailable degrades gracefully rather than refusing.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _blind() -> dict[str, Any]:
    """No usable state at all — the planner will refuse (truly blind)."""
    return {"brief": "", "sensors_down": ["gateway-status"], "staleness_s": 0.0,
            "verdict": "unknown", "gateway_state": "unknown", "system_count": 0,
            "dashboard_up": False}


def gateway_feed(config: dict[str, Any], timeout_s: float | None = None) -> dict[str, Any]:
    """Universal feed: the gateway runtime status file. No plugins required."""
    try:
        from gateway.status import read_runtime_status

        status = read_runtime_status()
        if not status:
            return _blind()
        gw = str(status.get("gateway_state") or status.get("state") or "running")
        agents = status.get("active_agents")
        brief = f"gateway: {gw}"
        if agents is not None:
            brief += f" ({agents} active agent(s))"
        brief += "\nno external system dashboard configured — planning on gateway status"
        return {
            "brief": brief,
            "sensors_down": [],          # gateway status IS present → not blind
            "staleness_s": 0.0,          # runtime file is live
            "verdict": "ok",
            "gateway_state": gw,
            "system_count": 0,
            "dashboard_up": False,
        }
    except Exception as exc:
        logger.warning("AMDP gateway state feed failed: %s", exc)
        return _blind()


def proprioception_feed(config: dict[str, Any], timeout_s: float | None = None) -> dict[str, Any]:
    """Optional enrichment feed via the proprioception plugin. Falls back to the
    gateway feed if the plugin is not installed."""
    try:
        from plugins.proprioception.collector import ATTENTION_STATES, get_snapshot
        from plugins.proprioception.settings import DEFAULTS
    except Exception:
        logger.debug("AMDP: proprioception plugin unavailable; using gateway feed")
        return gateway_feed(config, timeout_s)
    try:
        settings = dict(DEFAULTS)
        block = (config or {}).get("proprioception")
        if isinstance(block, dict):
            settings.update(block)
        if timeout_s:
            settings = {**settings, "timeout_seconds": float(timeout_s)}
        snap = get_snapshot(settings, force=False)
        systems = (snap.dashboard or {}).get("systems") or []
        attention = [s for s in systems if isinstance(s, dict) and str(s.get("state")) in ATTENTION_STATES]
        dashboard_up = snap.dashboard is not None
        verdict = "attention" if attention else ("ok" if dashboard_up else "unknown")
        blinding = ["gateway-status"] if "gateway-status" in list(snap.sensors_down) else []
        lines = [f"overall verdict: {verdict}", f"gateway: {snap.gateway_state}"]
        if not dashboard_up:
            lines.append("system dashboard unavailable — planning on gateway status alone")
        if snap.dashboard_stale_for:
            lines.append(f"state staleness: {snap.dashboard_stale_for:.0f}s")
        if attention:
            lines.append("systems needing attention:")
            for s in attention[:12]:
                lines.append(f"  - {s.get('label', s.get('id', '?'))}: {s.get('state')} ({s.get('detail', '')})")
        elif dashboard_up:
            lines.append(f"all {len(systems)} monitored systems calm")
        return {
            "brief": "\n".join(lines),
            "sensors_down": blinding,
            "staleness_s": float(snap.dashboard_stale_for or 0.0),
            "verdict": verdict,
            "gateway_state": snap.gateway_state,
            "system_count": len(systems),
            "dashboard_up": dashboard_up,
        }
    except Exception as exc:
        logger.warning("AMDP proprioception feed failed, falling back to gateway: %s", exc)
        return gateway_feed(config, timeout_s)


def _proprioception_available() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("plugins.proprioception.collector") is not None
    except Exception:
        return False


def get_believed_state(
    config: dict[str, Any], timeout_s: float | None = None, mode: str = "auto"
) -> dict[str, Any]:
    """Resolve the configured state feed and return the believed-state dict.
    Never raises — a total failure returns a blind state (planner refuses)."""
    try:
        mode = (mode or "auto").strip().lower()
        if mode == "gateway":
            return gateway_feed(config, timeout_s)
        if mode == "proprioception":
            return proprioception_feed(config, timeout_s)
        # auto: enrichment if present, else the universal gateway feed
        if _proprioception_available():
            return proprioception_feed(config, timeout_s)
        return gateway_feed(config, timeout_s)
    except Exception as exc:
        logger.warning("AMDP state feed resolution failed: %s", exc)
        return _blind()
