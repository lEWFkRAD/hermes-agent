"""#138195: a failed ``claude --version`` probe must not silently downgrade the
OAuth identity for the whole process lifetime.

A successful detection is persisted to a machine-level sidecar; when detection
later fails, the recorded value is used instead of the stale static fallback
(which 400s every Opus 5.5 request with ``claude_code_version_too_old``).
Recorded and detected values are validated ASCII-strict before they can reach
the ``user-agent`` header.
"""

from __future__ import annotations

import json
import subprocess

import pytest

import agent.anthropic_adapter as adapter
from agent.anthropic_adapter import (
    _CLAUDE_CODE_VERSION_FALLBACK,
    _claude_code_version_ok,
    _detect_claude_code_version,
    _get_claude_code_version,
)


@pytest.fixture(autouse=True)
def _fresh_process_cache(monkeypatch, tmp_path):
    """Empty in-memory cache + sidecar under a temp root, per test."""
    monkeypatch.setattr(adapter, "_claude_code_version_cache", None)
    monkeypatch.setattr(
        adapter, "_claude_code_version_cache_path", lambda: tmp_path / "claude_code_version.json"
    )


def _no_candidates(monkeypatch):
    monkeypatch.setattr(adapter, "_claude_code_candidates", lambda: [])


def _detected(monkeypatch, version: str):
    def runner(cmd, *args, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=f"{version} (Claude Code)", stderr="")

    monkeypatch.setattr(adapter, "_claude_code_candidates", lambda: ["/bin/claude"])
    monkeypatch.setattr(adapter.subprocess, "run", runner)


def test_successful_detection_is_recorded(monkeypatch, tmp_path):
    _detected(monkeypatch, "2.1.294")
    assert _get_claude_code_version() == "2.1.294"
    assert json.loads((tmp_path / "claude_code_version.json").read_text())["version"] == "2.1.294"


def test_detection_failure_uses_recorded_value(monkeypatch, tmp_path):
    (tmp_path / "claude_code_version.json").write_text(json.dumps({"version": "2.1.294"}))
    _no_candidates(monkeypatch)
    assert _get_claude_code_version() == "2.1.294" != _CLAUDE_CODE_VERSION_FALLBACK


def test_recorded_older_than_fallback_is_ignored(monkeypatch, tmp_path):
    older = ".".join(str(int(p) - 1) for p in _CLAUDE_CODE_VERSION_FALLBACK.split("."))
    (tmp_path / "claude_code_version.json").write_text(json.dumps({"version": older}))
    _no_candidates(monkeypatch)
    assert _get_claude_code_version() == _CLAUDE_CODE_VERSION_FALLBACK


def test_corrupt_cache_never_breaks_oauth_path(monkeypatch, tmp_path):
    (tmp_path / "claude_code_version.json").write_text("{ not json")
    _no_candidates(monkeypatch)
    assert _get_claude_code_version() == _CLAUDE_CODE_VERSION_FALLBACK


@pytest.mark.parametrize(
    "raw",
    [
        "2.1.400\n",   # trailing newline: $-anchored re.match lets this through -> LocalProtocolError
        "2.1.400 ",
        " 2.1.400",
        "2.1.400\r",
        "٢.١.٤٠٠",      # Arabic-Indic digits: \d matches, int() parses, header fails
        "２.１.４００",   # fullwidth digits
        "2.1.300,beta",
        ["2.1.400"],   # JSON list as the cached value
        None,
        400,
    ],
)
def test_version_validation_is_ascii_strict(raw):
    assert not _claude_code_version_ok(raw)


@pytest.mark.parametrize("good", ["2.1.74", "2.1.400", "2.1.80-beta.1", "2.1.400+build.7", "2.1.400.1"])
def test_valid_versions_pass_validation(good):
    assert _claude_code_version_ok(good)


def test_invalid_detected_value_is_not_persisted(monkeypatch, tmp_path):
    _detected(monkeypatch, "2.1.300,beta")
    assert _get_claude_code_version() == _CLAUDE_CODE_VERSION_FALLBACK
    assert not (tmp_path / "claude_code_version.json").exists()


def test_unchanged_value_is_not_rewritten(monkeypatch, tmp_path):
    _detected(monkeypatch, "2.1.294")
    assert _get_claude_code_version() == "2.1.294"
    first = (tmp_path / "claude_code_version.json").read_text()
    monkeypatch.setattr(adapter, "_claude_code_version_cache", None)
    assert _get_claude_code_version() == "2.1.294"
    assert (tmp_path / "claude_code_version.json").read_text() == first
