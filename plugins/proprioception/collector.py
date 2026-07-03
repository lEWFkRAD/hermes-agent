"""Body-state collection for the proprioception plugin.

Two external senses plus one internal:

* **Dashboard rollup** — ``GET /api/home`` on the Onyx Command Center
  (a local HttpListener that already aggregates ~19 systems into
  ``{verdict, needs[], systems[{id, state, label, detail, cat}]}``).
  We deliberately reuse it instead of probing the systems ourselves:
  one collector on the machine, not two drifting ones.
* **Gateway runtime status** — ``{HERMES_HOME}/gateway_state.json`` via
  :func:`gateway.status.read_runtime_status` (file read, no HTTP, works
  even when the API server is disabled).
* **Context estimate** — computed by the caller from the live message
  list and passed into the heartbeat, never fetched here.

A failing source is *data* ("sensor offline"), never an exception into
the agent loop.  The snapshot is cached process-wide with a short TTL so
concurrent sessions share one fetch.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# States (from the dashboard) that mean "something needs attention".
# Anything not in this set — "ok" and the informational "info" — is calm.
ATTENTION_STATES = frozenset({"warn", "warning", "down", "error", "crit", "critical"})


@dataclass
class Snapshot:
    """One reading of the body. Sensor failures are recorded, not raised."""

    fetched_at: float
    dashboard: Optional[Dict[str, Any]] = None
    dashboard_error: str = ""
    gateway: Optional[Dict[str, Any]] = None
    gateway_error: str = ""

    @property
    def sensors_down(self) -> Tuple[str, ...]:
        out = []
        if self.dashboard is None:
            out.append("dashboard")
        if self.gateway is None:
            out.append("gateway-status")
        return tuple(out)


_CACHE_LOCK = threading.Lock()
_CACHED: Optional[Snapshot] = None

# Last successful dashboard payload, kept so a single missed poll (the
# dashboard is a single-threaded listener; an occasional timeout is normal)
# doesn't read as "sensor lost" and produce loss/recovery chatter. A fetch
# failure only becomes sensor-down once the last good reading is older than
# this many seconds.
_STALE_GRACE_SECONDS = 180.0
_LAST_GOOD_DASHBOARD: Optional[Dict[str, Any]] = None
_LAST_GOOD_AT: float = 0.0


def _fetch_dashboard(url: str, timeout: float) -> Dict[str, Any]:
    import requests

    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict) or "systems" not in payload:
        raise ValueError("unexpected /api/home shape")
    return payload


def _fetch_gateway_status() -> Optional[Dict[str, Any]]:
    from gateway.status import read_runtime_status

    return read_runtime_status()


def get_snapshot(settings: Dict[str, Any], *, force: bool = False) -> Snapshot:
    """Return the current body snapshot, cached for ``cache_ttl_seconds``.

    Never raises. Thread-safe: concurrent sessions share one fetch.
    """
    global _CACHED
    ttl = float(settings["cache_ttl_seconds"])
    with _CACHE_LOCK:
        if (
            not force
            and _CACHED is not None
            and (time.time() - _CACHED.fetched_at) < ttl
        ):
            return _CACHED

        global _LAST_GOOD_DASHBOARD, _LAST_GOOD_AT
        snap = Snapshot(fetched_at=time.time())
        try:
            snap.dashboard = _fetch_dashboard(
                str(settings["dashboard_url"]), float(settings["timeout_seconds"])
            )
            _LAST_GOOD_DASHBOARD = snap.dashboard
            _LAST_GOOD_AT = snap.fetched_at
        except Exception as exc:  # sensor down is data, not an error
            snap.dashboard_error = f"{type(exc).__name__}: {exc}"[:200]
            logger.debug("proprioception: dashboard fetch failed: %s", snap.dashboard_error)
            # Grace window: reuse the last good reading rather than flapping
            # to sensor-down on one missed poll.
            if (
                _LAST_GOOD_DASHBOARD is not None
                and (snap.fetched_at - _LAST_GOOD_AT) < _STALE_GRACE_SECONDS
            ):
                snap.dashboard = _LAST_GOOD_DASHBOARD
                snap.dashboard_error = ""
        try:
            snap.gateway = _fetch_gateway_status()
            if snap.gateway is None:
                snap.gateway_error = "no gateway_state.json"
        except Exception as exc:
            snap.gateway_error = f"{type(exc).__name__}: {exc}"[:200]
            logger.debug("proprioception: gateway status read failed: %s", snap.gateway_error)

        _CACHED = snap
        return snap


def fingerprint(snap: Snapshot) -> Tuple:
    """Reduce a snapshot to the fields whose *change* is material.

    Deliberately excludes free-text ``detail`` strings (VRAM/temp numbers
    wobble every reading — diffing them would make the heartbeat chatty)
    and timestamps. A sensor being unreachable is itself a state.
    """
    dash_part: Tuple = ("sensor-down",)
    if snap.dashboard is not None:
        systems = snap.dashboard.get("systems") or []
        dash_part = (
            str(snap.dashboard.get("verdict", "")),
            tuple(
                sorted(
                    (str(s.get("id", "?")), str(s.get("state", "?")))
                    for s in systems
                    if isinstance(s, dict)
                )
            ),
            # needs[] with severity above plain info are material
            tuple(
                sorted(
                    str(n.get("text", ""))[:80]
                    for n in (snap.dashboard.get("needs") or [])
                    if isinstance(n, dict) and str(n.get("sev", "info")) != "info"
                )
            ),
        )
    gw_part: Tuple = ("sensor-down",)
    if snap.gateway is not None:
        gw_part = (str(snap.gateway.get("state", snap.gateway.get("gateway_state", "?"))),)
    return (dash_part, gw_part)


def diff_systems(
    prev: Optional[Snapshot], cur: Snapshot
) -> Tuple[Tuple[str, str, str], ...]:
    """Per-system (label, old_state, new_state) transitions between snapshots.

    Systems present only on one side are reported against ``"absent"``.
    Empty when either side has no dashboard data (sensor transitions are
    handled separately by the caller).
    """
    if prev is None or prev.dashboard is None or cur.dashboard is None:
        return ()

    def _by_id(s: Snapshot) -> Dict[str, Dict[str, Any]]:
        return {
            str(sys_.get("id", "?")): sys_
            for sys_ in (s.dashboard.get("systems") or [])
            if isinstance(sys_, dict)
        }

    old, new = _by_id(prev), _by_id(cur)
    out = []
    for sid in sorted(set(old) | set(new)):
        old_state = str(old[sid].get("state", "?")) if sid in old else "absent"
        new_state = str(new[sid].get("state", "?")) if sid in new else "absent"
        if old_state != new_state:
            label = str((new.get(sid) or old.get(sid) or {}).get("label", sid))
            out.append((label, old_state, new_state))
    return tuple(out)


def has_degradation(transitions: Tuple[Tuple[str, str, str], ...]) -> bool:
    """True when any transition lands in an attention state (rate-limit bypass)."""
    return any(new in ATTENTION_STATES for _, _, new in transitions)


def reset_cache_for_tests() -> None:
    global _CACHED, _LAST_GOOD_DASHBOARD, _LAST_GOOD_AT
    with _CACHE_LOCK:
        _CACHED = None
        _LAST_GOOD_DASHBOARD = None
        _LAST_GOOD_AT = 0.0
