"""The ``body_state`` tool — on-demand full proprioceptive reading.

The heartbeat whispers deltas; this tool is the deliberate look. It
bypasses nothing: same collector, same sources, formatted as a grouped
plain-text report the model can quote to the user directly.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List

from plugins.proprioception import collector
from plugins.proprioception.settings import get_settings, is_enabled

_STATE_ICONS = {
    "ok": "[ok]",
    "info": "[i]",
    "warn": "[!]",
    "warning": "[!]",
    "down": "[DOWN]",
    "error": "[ERR]",
    "crit": "[CRIT]",
    "critical": "[CRIT]",
}

BODY_STATE_SCHEMA: Dict[str, Any] = {
    "name": "body_state",
    "description": (
        "Read your own machine's status (proprioception): local model servers, "
        "GPUs, gateway, self-healing tasks, disk, and network. Use when the user "
        "asks about system health, when a heartbeat reported a change you need "
        "detail on, or before work that depends on local models being up."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "detail": {
                "type": "string",
                "enum": ["summary", "full"],
                "description": "summary = verdict + anything needing attention; full = every tracked system.",
            }
        },
        "required": [],
    },
}


def check_body_state_available() -> bool:
    """Gate registration/dispatch on the config master switch (fail-closed)."""
    return is_enabled()


def handle_body_state(args: Dict[str, Any], **_kw: Any) -> str:
    detail = str((args or {}).get("detail") or "summary").lower()
    settings = get_settings()
    snap = collector.get_snapshot(settings)
    lines: List[str] = []

    if snap.dashboard is None:
        lines.append(
            "Status dashboard unreachable ({}) — external body-sense is offline. "
            "Gateway self-report below may still work.".format(snap.dashboard_error or "no detail")
        )
    else:
        verdict = str(snap.dashboard.get("verdict", "?"))
        lines.append(f"Overall verdict: {verdict}")
        needs = [n for n in (snap.dashboard.get("needs") or []) if isinstance(n, dict)]
        if needs:
            lines.append("Needs attention:")
            for n in needs:
                lines.append(f"  - ({n.get('sev', 'info')}) {n.get('text', '')}")
        systems = [s for s in (snap.dashboard.get("systems") or []) if isinstance(s, dict)]
        attention = [s for s in systems if str(s.get("state")) in collector.ATTENTION_STATES]
        if detail == "full":
            by_cat: Dict[str, List[Dict[str, Any]]] = {}
            for s in systems:
                by_cat.setdefault(str(s.get("cat", "other")), []).append(s)
            for cat, members in by_cat.items():
                lines.append(f"{cat}:")
                for s in members:
                    icon = _STATE_ICONS.get(str(s.get("state")), f"[{s.get('state')}]")
                    lines.append(f"  {icon} {s.get('label', s.get('id'))}: {s.get('detail', '')}")
        else:
            lines.append(f"{len(systems)} systems tracked; {len(attention)} need attention.")
            for s in attention:
                icon = _STATE_ICONS.get(str(s.get("state")), f"[{s.get('state')}]")
                lines.append(f"  {icon} {s.get('label', s.get('id'))}: {s.get('detail', '')}")

    if snap.gateway is not None:
        gw_state = snap.gateway.get("state") or snap.gateway.get("gateway_state") or "?"
        lines.append(f"Gateway self-report: {gw_state}")
        platforms = snap.gateway.get("platforms")
        if isinstance(platforms, dict):
            bad = {
                name: str(p.get("state"))
                for name, p in platforms.items()
                if isinstance(p, dict) and str(p.get("state")) not in ("connected", "ok")
            }
            if bad:
                lines.append("  Platform issues: " + json.dumps(bad, ensure_ascii=False))
    elif snap.gateway_error:
        lines.append(f"Gateway self-report unavailable: {snap.gateway_error}")

    age = max(0.0, time.time() - snap.fetched_at)
    lines.append(f"(reading is {age:.0f}s old; sources: command-center rollup + gateway state file)")
    return "\n".join(lines)
