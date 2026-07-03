"""Delta heartbeat: decide *whether* to speak and *what* to say.

Design constraints (these are load-bearing, not style — several came out
of an adversarial review):

* **Ephemeral tail injection only.** The returned text goes through the
  ``pre_llm_call`` → ``plugin_user_context`` path, which appends it to the
  current turn's user message at API-call time and never persists it. At
  most ONE heartbeat is visible in context at any moment, so repeated
  near-identical blocks cannot accumulate and self-condition the model
  (the failure mode behind the tool-loop degeneration work, #41490).
* **Every emission has a cache price.** The injected tokens make the
  current user message diverge from what history replays next turn, so
  the previous turn's tail gets re-prefilled once per emission. Bounded
  (one turn of lag), but it means emissions must be RARE: no all-green
  baselines, no content-free changes, no flap storms.
* **Fenced and attributed.** The text rides inside the user message, so
  a smaller model needs an explicit fence + system note to know it is
  telemetry about the HOST machine, not the user talking (mirrors the
  ``<memory-context>`` convention in agent/memory_manager.py).
* **Renderer/fingerprint parity.** Everything the change-fingerprint
  tracks has a renderer; if nothing renders, nothing is emitted. A
  fingerprint delta can never produce an empty change message.
* **Perception, not policy.** The text reports state; it never instructs
  the model to act, retry, or route around anything.
* **Never break the turn.** Any internal failure returns ``None``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from plugins.proprioception import collector
from plugins.proprioception.collector import ATTENTION_STATES

logger = logging.getLogger(__name__)

# Context-fill thresholds (fractions of the configured window). Upward
# crossings are reported with a small hysteresis margin; downward moves
# (compression just ran — self-evident) silently re-bucket.
_CTX_BUCKETS = (0.50, 0.70, 0.85)
_CTX_HYSTERESIS = 0.02

# A (system, attention-state) edge may bypass the rate limit only once
# per this window; a flapping system degrades to normal rate-limited
# reporting instead of emitting on every turn.
_BYPASS_MEMORY_SECONDS = 600.0

_FENCE_OPEN = "<host-telemetry>"
_FENCE_CLOSE = "</host-telemetry>"
_SYSTEM_NOTE = (
    "[System note: automated status of the machine this assistant runs on — "
    "NOT part of the user's message. Do not volunteer or mention it to the "
    "user unless they ask, or it directly affects their request.]"
)

# Rotating sentence frames for change messages. With ephemeral injection
# only one is ever visible, so rotation is belt-and-suspenders against
# repetition — cheap, deterministic (per-session counter), testable.
_CHANGE_FRAMES = (
    "Host status change since the last reading:",
    "Since the previous reading, host status shifted:",
    "Host telemetry update:",
    "A change in the host machine's status:",
)

_STATE_WORDS = {
    "ok": "ok",
    "info": "info",
    "warn": "needs attention",
    "warning": "needs attention",
    "down": "DOWN",
    "error": "ERROR",
    "crit": "CRITICAL",
    "critical": "CRITICAL",
    "absent": "no longer tracked",
}


class _SessionState:
    __slots__ = (
        "lock",
        "fingerprint",
        "ctx_bucket",
        "last_emit",
        "emit_count",
        "last_dash_snapshot",
        "prev_sensors_down",
        "prev_gateway_state",
        "prev_verdict",
        "bypass_memory",
    )

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.fingerprint: Optional[Tuple] = None
        self.ctx_bucket: Optional[int] = None
        self.last_emit: float = 0.0
        self.emit_count: int = 0
        # Last snapshot that actually CARRIED dashboard data — kept
        # separately so a sensor outage between readings can't swallow a
        # system transition (diffing against a dashboard-less snapshot
        # returns no transitions).
        self.last_dash_snapshot: Optional[collector.Snapshot] = None
        self.prev_sensors_down: Tuple[str, ...] = ()
        self.prev_gateway_state: str = ""
        self.prev_verdict: str = ""
        self.bypass_memory: Dict[Tuple[str, str], float] = {}


_SESSIONS_LOCK = threading.Lock()
_SESSIONS: "OrderedDict[str, _SessionState]" = OrderedDict()
_MAX_SESSIONS = 1024


def _session_state(session_id: str) -> _SessionState:
    with _SESSIONS_LOCK:
        state = _SESSIONS.get(session_id)
        if state is None:
            state = _SessionState()
            _SESSIONS[session_id] = state
        _SESSIONS.move_to_end(session_id)
        while len(_SESSIONS) > _MAX_SESSIONS:
            evicted_id, _ = _SESSIONS.popitem(last=False)
            logger.info("proprioception: evicted session state for %s", evicted_id)
        return state


def _ctx_bucket(tokens: int, window: int, *, hysteresis: bool = False) -> int:
    frac = tokens / max(1, window)
    margin = _CTX_HYSTERESIS if hysteresis else 0.0
    bucket = 0
    for threshold in _CTX_BUCKETS:
        if frac >= threshold + margin:
            bucket += 1
    return bucket


def _estimate_context_tokens(conversation_history: Optional[List[Dict[str, Any]]]) -> int:
    if not conversation_history:
        return 0
    from agent.model_metadata import estimate_messages_tokens_rough

    return estimate_messages_tokens_rough(conversation_history)


def _fmt_tokens(tokens: int) -> str:
    if tokens >= 1000:
        return f"~{tokens / 1000:.0f}k"
    return f"~{tokens}"


def _wrap(body: str, settings: Dict[str, Any]) -> str:
    text = f"{_FENCE_OPEN}\n{_SYSTEM_NOTE}\n\n{body}\n{_FENCE_CLOSE}"
    limit = int(settings["max_chars"])
    if len(text) <= limit:
        return text
    # Truncate the body, keep the fence intact.
    overhead = len(_FENCE_OPEN) + len(_FENCE_CLOSE) + len(_SYSTEM_NOTE) + 4
    body = body[: max(20, limit - overhead - 1)] + "…"
    return f"{_FENCE_OPEN}\n{_SYSTEM_NOTE}\n\n{body}\n{_FENCE_CLOSE}"


def _ctx_phrase(ctx_tokens: int, window: int) -> str:
    pct = 100.0 * ctx_tokens / max(1, window)
    return (
        f"conversation {_fmt_tokens(ctx_tokens)} tokens of the "
        f"{_fmt_tokens(window)}-token window (rough count, excludes system prompt)"
    )


def _baseline_body(
    snap: collector.Snapshot, ctx_tokens: int, window: int, bucket: int
) -> Tuple[str, bool]:
    """Return (body, has_signal). All-green baselines carry no signal."""
    parts: List[str] = []
    signal = False
    if snap.dashboard is not None:
        systems = [s for s in (snap.dashboard.get("systems") or []) if isinstance(s, dict)]
        not_ok = [s for s in systems if str(s.get("state")) in ATTENTION_STATES]
        if not_ok:
            signal = True
            names = "; ".join(
                f"{s.get('label', s.get('id', '?'))}: "
                f"{_STATE_WORDS.get(str(s.get('state')), s.get('state'))}"
                for s in not_ok[:4]
            )
            parts.append(
                f"{len(systems)} host systems tracked, attention on {len(not_ok)} ({names})"
            )
        else:
            parts.append(f"all {len(systems)} tracked host systems ok")
        verdict = str(snap.dashboard.get("verdict", ""))
        if verdict and verdict != "ok":
            signal = True
            parts.append(f"overall verdict: {verdict}")
    else:
        # A cold-start fetch miss is usually the dashboard's own collection
        # cycle briefly blocking its single-threaded listener — with no prior
        # reading to compare against, announcing "feed unreachable" would be
        # a likely false alarm. Stay silent; a real outage is reported as a
        # sensor-loss transition on a later turn (where history exists).
        parts.append("host status feed unreachable (no external readings available)")
    if snap.gateway is not None and snap.gateway_state not in ("running", "ok"):
        signal = True
        parts.append(f"gateway {snap.gateway_state}")
    if bucket > 0:
        signal = True
        parts.append(_ctx_phrase(ctx_tokens, window))
    body = "First status reading this session: " + "; ".join(parts) + "."
    return body, signal


def build_heartbeat(
    *,
    session_id: str,
    conversation_history: Optional[List[Dict[str, Any]]],
    settings: Dict[str, Any],
) -> Optional[str]:
    """Return heartbeat text for this turn, or ``None`` to stay silent."""
    mode = settings["heartbeat"]
    if mode == "off":
        return None

    # Collect BEFORE taking the per-session lock: get_snapshot serves
    # stale-while-revalidating, so this is cheap for everyone except the
    # single refreshing thread.
    snap = collector.get_snapshot(settings)
    fp = collector.fingerprint(snap)
    ctx_tokens = _estimate_context_tokens(conversation_history)
    window = int(settings["context_window"])

    state = _session_state(session_id)
    with state.lock:
        return _decide_locked(state, snap, fp, ctx_tokens, window, mode, settings)


def _decide_locked(
    state: _SessionState,
    snap: collector.Snapshot,
    fp: Tuple,
    ctx_tokens: int,
    window: int,
    mode: str,
    settings: Dict[str, Any],
) -> Optional[str]:
    now = time.monotonic()

    # Bucket update rule: climb only past threshold+hysteresis (and report
    # it); fall silently on any drop below a threshold (compression just
    # ran — self-evident); inside the hysteresis band, keep the old bucket
    # so a slow creep can't silently swallow a crossing.
    bucket_up = _ctx_bucket(ctx_tokens, window, hysteresis=True)
    bucket_down = _ctx_bucket(ctx_tokens, window)
    prev_bucket = state.ctx_bucket if state.ctx_bucket is not None else 0
    if bucket_up > prev_bucket:
        new_bucket, ctx_crossed_up = bucket_up, True
    elif bucket_down < prev_bucket:
        new_bucket, ctx_crossed_up = bucket_down, False
    else:
        new_bucket, ctx_crossed_up = prev_bucket, False

    def _record(emitted: bool) -> None:
        state.fingerprint = fp
        state.ctx_bucket = new_bucket
        if snap.dashboard is not None:
            state.last_dash_snapshot = snap
        state.prev_sensors_down = snap.sensors_down
        state.prev_gateway_state = snap.gateway_state
        state.prev_verdict = (
            str(snap.dashboard.get("verdict", "")) if snap.dashboard is not None else ""
        )
        if emitted:
            state.last_emit = now
            state.emit_count += 1

    # --- first reading for this session ---
    if state.fingerprint is None:
        body, signal = _baseline_body(snap, ctx_tokens, window, bucket_down)
        _record(emitted=signal)
        if signal or mode == "always":
            return _wrap(body, settings)
        return None  # all green: silence is the baseline

    # --- diff against the previous reading ---
    lines: List[str] = []

    transitions = collector.diff_systems(state.last_dash_snapshot, snap)
    for label, old, new in transitions[:6]:
        lines.append(
            f"{label}: {_STATE_WORDS.get(old, old)} -> {_STATE_WORDS.get(new, new)}"
        )
    if len(transitions) > 6:
        lines.append(f"(+{len(transitions) - 6} more transitions)")

    prev_down, cur_down = set(state.prev_sensors_down), set(snap.sensors_down)
    sensor_lost = bool(cur_down - prev_down)
    for sensor in sorted(cur_down - prev_down):
        lines.append(f"lost the {sensor} status feed (unreachable)")
    for sensor in sorted(prev_down - cur_down):
        lines.append(f"{sensor} status feed back online")

    if snap.gateway is not None and state.prev_gateway_state not in ("", snap.gateway_state):
        lines.append(f"gateway: {state.prev_gateway_state} -> {snap.gateway_state}")

    cur_verdict = (
        str(snap.dashboard.get("verdict", "")) if snap.dashboard is not None else ""
    )
    # Verdict changes usually ride along with a system transition; only
    # render it alone when nothing else explains the shift.
    if not transitions and cur_verdict and state.prev_verdict not in ("", cur_verdict):
        lines.append(f"overall verdict: {state.prev_verdict} -> {cur_verdict}")

    if ctx_crossed_up:
        boundary = _CTX_BUCKETS[new_bucket - 1]
        pct = 100.0 * ctx_tokens / max(1, window)
        lines.append(
            f"context fill climbed past {boundary:.0%} "
            f"(now ~{pct:.0f}% of {_fmt_tokens(window)})"
        )

    if mode == "always":
        frame = _CHANGE_FRAMES[state.emit_count % len(_CHANGE_FRAMES)]
        if lines:
            body = f"{frame} " + "; ".join(lines) + ". Status only — act on it only if it matters to the user's request."
        else:
            body, _ = _baseline_body(snap, ctx_tokens, window, bucket_down)
            body = body.replace("First status reading this session:", f"Periodic reading — {frame.rstrip(':').lower()}", 1)
        _record(emitted=True)
        return _wrap(body, settings)

    if not lines:
        # Includes the fingerprint-changed-but-nothing-renders case (by
        # construction there shouldn't be one) and downward ctx moves:
        # update silently so the same non-event can't re-trigger.
        _record(emitted=False)
        return None

    # Rate limit with a degradation bypass — but each (system, bad-state)
    # edge may bypass only once per window, so a flapping system can't
    # emit on every turn.
    min_interval = float(settings["min_interval_seconds"])
    degraded_edges = [
        (label, new)
        for label, _old, new in transitions
        if new in ATTENTION_STATES
    ]
    fresh_degradation = False
    for edge in degraded_edges:
        if now - state.bypass_memory.get(edge, -_BYPASS_MEMORY_SECONDS) >= _BYPASS_MEMORY_SECONDS:
            fresh_degradation = True
    bypass = fresh_degradation or sensor_lost

    if not bypass and (now - state.last_emit) < min_interval:
        # Suppressed: deliberately do NOT update state, so the change is
        # still reported once the window opens (diff old-vs-newest).
        return None

    for edge in degraded_edges:
        state.bypass_memory[edge] = now
    if len(state.bypass_memory) > 64:
        cutoff = now - _BYPASS_MEMORY_SECONDS
        state.bypass_memory = {
            k: v for k, v in state.bypass_memory.items() if v >= cutoff
        }

    frame = _CHANGE_FRAMES[state.emit_count % len(_CHANGE_FRAMES)]
    _record(emitted=True)
    body = (
        f"{frame} "
        + "; ".join(lines)
        + ". Status only — act on it only if it matters to the user's request."
    )
    return _wrap(body, settings)


def reset_for_tests() -> None:
    with _SESSIONS_LOCK:
        _SESSIONS.clear()
