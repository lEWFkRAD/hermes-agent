"""Delta heartbeat: decide *whether* to speak and *what* to say.

Design constraints (these are load-bearing, not style):

* **Ephemeral tail injection only.** The returned text goes through the
  ``pre_llm_call`` → ``plugin_user_context`` path, which appends it to the
  current turn's user message at API-call time and never persists it. At
  most ONE heartbeat is visible in context at any moment, so repeated
  near-identical blocks cannot accumulate and self-condition the model
  (the failure mode behind the tool-loop degeneration work, #41490).
* **Delta by default.** Steady state costs zero tokens. The heartbeat
  speaks on: session baseline, material state transitions, sensor
  loss/recovery, and context-fill bucket crossings.
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

# Context-fill thresholds (fractions of the configured window). The
# heartbeat reports when fill crosses a boundary in either direction.
_CTX_BUCKETS = (0.50, 0.70, 0.85)

# Rotating sentence frames. With ephemeral injection only one is ever
# visible, so rotation is belt-and-suspenders against repetition — cheap,
# deterministic (keyed on a per-session counter), and testable.
_CHANGE_FRAMES = (
    "Body-state change since the last reading:",
    "Since the previous check, your system status shifted:",
    "Proprioceptive update — something changed:",
    "A change in your own machine's state:",
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
    "absent": "gone from the rollup",
}


class _SessionState:
    __slots__ = ("fingerprint", "ctx_bucket", "last_emit", "emit_count", "had_snapshot")

    def __init__(self) -> None:
        self.fingerprint: Optional[Tuple] = None
        self.ctx_bucket: Optional[int] = None
        self.last_emit: float = 0.0
        self.emit_count: int = 0
        self.had_snapshot: Optional[collector.Snapshot] = None


_SESSIONS_LOCK = threading.Lock()
_SESSIONS: "OrderedDict[str, _SessionState]" = OrderedDict()
_MAX_SESSIONS = 256


def _session_state(session_id: str) -> _SessionState:
    with _SESSIONS_LOCK:
        state = _SESSIONS.get(session_id)
        if state is None:
            state = _SessionState()
            _SESSIONS[session_id] = state
        _SESSIONS.move_to_end(session_id)
        while len(_SESSIONS) > _MAX_SESSIONS:
            _SESSIONS.popitem(last=False)
        return state


def _ctx_bucket(tokens: int, window: int) -> int:
    frac = tokens / max(1, window)
    bucket = 0
    for threshold in _CTX_BUCKETS:
        if frac >= threshold:
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


def _summarize_baseline(snap: collector.Snapshot, ctx_tokens: int, window: int) -> str:
    parts: List[str] = []
    if snap.dashboard is not None:
        systems = [s for s in (snap.dashboard.get("systems") or []) if isinstance(s, dict)]
        not_ok = [s for s in systems if str(s.get("state")) in ATTENTION_STATES]
        if not_ok:
            names = "; ".join(
                f"{s.get('label', s.get('id', '?'))}: {_STATE_WORDS.get(str(s.get('state')), s.get('state'))}"
                for s in not_ok[:4]
            )
            parts.append(f"{len(systems)} systems tracked, attention on {len(not_ok)} ({names})")
        else:
            parts.append(f"all {len(systems)} tracked systems ok")
        verdict = str(snap.dashboard.get("verdict", ""))
        if verdict and verdict != "ok":
            parts.append(f"overall verdict: {verdict}")
    else:
        parts.append("status dashboard unreachable (flying without that sensor)")
    if snap.gateway is not None:
        gw_state = snap.gateway.get("state") or snap.gateway.get("gateway_state") or "?"
        parts.append(f"gateway {gw_state}")
    pct = 100.0 * ctx_tokens / max(1, window)
    parts.append(f"context {_fmt_tokens(ctx_tokens)} tokens (~{pct:.0f}% of {_fmt_tokens(window)})")
    return (
        "[proprioception] Session baseline — your own machine's state: "
        + "; ".join(parts)
        + ". Passive awareness only; no action implied."
    )


def _summarize_change(
    frame: str,
    transitions: Tuple[Tuple[str, str, str], ...],
    sensor_changes: List[str],
    ctx_line: str,
) -> str:
    lines: List[str] = []
    for label, old, new in transitions[:6]:
        old_w = _STATE_WORDS.get(old, old)
        new_w = _STATE_WORDS.get(new, new)
        lines.append(f"{label}: {old_w} -> {new_w}")
    if len(transitions) > 6:
        lines.append(f"(+{len(transitions) - 6} more transitions)")
    lines.extend(sensor_changes)
    if ctx_line:
        lines.append(ctx_line)
    body = "; ".join(lines)
    return f"[proprioception] {frame} {body}. Report of state only — act on it only if it matters to the user's request."


def build_heartbeat(
    *,
    session_id: str,
    is_first_turn: bool,
    conversation_history: Optional[List[Dict[str, Any]]],
    settings: Dict[str, Any],
) -> Optional[str]:
    """Return heartbeat text for this turn, or ``None`` to stay silent."""
    mode = settings["heartbeat"]
    if mode == "off":
        return None

    state = _session_state(session_id or "no-session")
    snap = collector.get_snapshot(settings)
    fp = collector.fingerprint(snap)

    ctx_tokens = _estimate_context_tokens(conversation_history)
    window = int(settings["context_window"])
    bucket = _ctx_bucket(ctx_tokens, window)

    now = time.time()
    first_reading = state.fingerprint is None

    # --- baseline: first reading for this session ---
    if first_reading:
        state.fingerprint = fp
        state.ctx_bucket = bucket
        state.had_snapshot = snap
        state.last_emit = now
        state.emit_count += 1
        return _truncate(_summarize_baseline(snap, ctx_tokens, window), settings)

    # --- what changed since the last reading? ---
    transitions = collector.diff_systems(state.had_snapshot, snap)

    sensor_changes: List[str] = []
    prev_down = set(state.had_snapshot.sensors_down if state.had_snapshot else ())
    cur_down = set(snap.sensors_down)
    for sensor in sorted(cur_down - prev_down):
        sensor_changes.append(f"lost the {sensor} sensor (status feed unreachable)")
    for sensor in sorted(prev_down - cur_down):
        sensor_changes.append(f"{sensor} sensor back online")

    ctx_line = ""
    if state.ctx_bucket is not None and bucket != state.ctx_bucket:
        pct = 100.0 * ctx_tokens / max(1, window)
        direction = "climbed past" if bucket > state.ctx_bucket else "dropped back under"
        boundary = _CTX_BUCKETS[max(bucket, state.ctx_bucket) - 1]
        ctx_line = f"context fill {direction} {boundary:.0%} (now ~{pct:.0f}% of {_fmt_tokens(window)})"

    changed = fp != state.fingerprint or bool(ctx_line)

    # Update tracking state regardless of whether we speak, EXCEPT when a
    # non-critical change is suppressed by the rate limit — then we keep the
    # old baseline so the change is still reported once the window opens.
    if mode == "always" or not changed:
        state.fingerprint = fp
        state.ctx_bucket = bucket
        state.had_snapshot = snap

    if mode == "always":
        state.last_emit = now
        state.emit_count += 1
        return _truncate(_summarize_baseline(snap, ctx_tokens, window), settings)

    if not changed:
        return None

    # Rate limit: suppress non-degradation chatter inside the window.
    min_interval = float(settings["min_interval_seconds"])
    degraded = collector.has_degradation(transitions) or bool(cur_down - prev_down)
    if not degraded and (now - state.last_emit) < min_interval:
        return None

    state.fingerprint = fp
    state.ctx_bucket = bucket
    state.had_snapshot = snap
    state.last_emit = now
    frame = _CHANGE_FRAMES[state.emit_count % len(_CHANGE_FRAMES)]
    state.emit_count += 1
    return _truncate(_summarize_change(frame, transitions, sensor_changes, ctx_line), settings)


def _truncate(text: str, settings: Dict[str, Any]) -> str:
    limit = int(settings["max_chars"])
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def reset_for_tests() -> None:
    with _SESSIONS_LOCK:
        _SESSIONS.clear()
