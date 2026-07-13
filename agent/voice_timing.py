"""Best-effort JSONL timing receipts for the Hermes speech path.

Receipt writes must never delay or fail a user-visible voice turn.  Keep the
schema deliberately flat and append-only so PowerShell and WSL helpers can
write compatible records to the same file.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


def voice_timing_log_path() -> Path:
    configured = os.environ.get("HERMES_VOICE_TIMING_LOG", "").strip()
    if configured:
        return Path(configured).expanduser()
    home = os.environ.get("HERMES_HOME", "").strip()
    if home:
        return Path(home).expanduser() / "logs" / "voice_timing.jsonl"
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "hermes" / "logs" / "voice_timing.jsonl"
    return Path.home() / ".hermes" / "logs" / "voice_timing.jsonl"


def append_voice_timing(event: str, status: str, **fields: Any) -> None:
    """Append one receipt.  Diagnostics are intentionally fail-open."""
    try:
        path = voice_timing_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "status": status,
            **fields,
        }
        line = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        fd = os.open(path, flags, 0o600)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except Exception:
        # Timing telemetry is never allowed to break voice delivery.
        return
