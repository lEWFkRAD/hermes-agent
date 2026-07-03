"""Proprioception plugin — a body sense for Hermes.

Three tiers:

1. **Delta heartbeat** (``pre_llm_call`` hook): when the machine's state
   materially changes between turns — a model server goes down, VRAM
   pressure trips the dashboard, context fill crosses a bucket — a short
   status line rides into the current turn's user message. Ephemeral:
   injected at API-call time via ``plugin_user_context``, never persisted,
   so exactly one heartbeat is ever visible in context.
2. **``body_state`` tool**: on-demand full reading, grouped by category.
3. **Event language**: sensor loss ("dashboard unreachable") is reported
   as a state like any other, so the agent knows when it's flying blind.

Fail-closed: without ``proprioception.enabled: true`` in config.yaml the
hook returns ``None`` and the tool's check_fn hides it. Bundled backend
kind → auto-loads like the spotify plugin; the config flag is the single
switch (soft-launch friendly, ConfigSentinel-visible).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _pre_llm_call(**kwargs: Any) -> Optional[dict]:
    """Turn-prologue hook: contribute an ephemeral heartbeat, or nothing.

    ``invoke_hook`` already isolates exceptions, but we catch everything
    anyway: a broken body sense must never cost a turn.
    """
    try:
        from plugins.proprioception.settings import get_settings

        settings = get_settings()
        if not settings["enabled"]:
            return None

        from plugins.proprioception.heartbeat import build_heartbeat

        text = build_heartbeat(
            session_id=str(kwargs.get("session_id") or "no-session"),
            is_first_turn=bool(kwargs.get("is_first_turn")),
            conversation_history=kwargs.get("conversation_history"),
            settings=settings,
        )
        if text:
            return {"context": text}
        return None
    except Exception:
        logger.debug("proprioception heartbeat failed; staying silent", exc_info=True)
        return None


def register(ctx) -> None:
    """Called once by the plugin loader."""
    from plugins.proprioception.tools import (
        BODY_STATE_SCHEMA,
        check_body_state_available,
        handle_body_state,
    )

    ctx.register_tool(
        name="body_state",
        toolset="proprioception",
        schema=BODY_STATE_SCHEMA,
        handler=handle_body_state,
        check_fn=check_body_state_available,
        emoji="🫀",
    )
    ctx.register_hook("pre_llm_call", _pre_llm_call)
