"""Tests for reviving a cua-driver session the driver has expired.

The driver rejects calls whose session id it no longer knows — desktop app
closed, driver restarted, idle expiry — with an in-band ``isError`` result
rather than an exception:

    session 'hermes-abc123' has ended; tool call 'list_windows' was rejected.
    Call start_session with this id to revive it before issuing further
    actions, or use a new session id.

The transport is healthy throughout, so neither the closed-transport rung nor
the ``_started`` guard in ``call_tool`` fires. Before this rung the message
reached the model verbatim and it retried the identical ``capture`` until the
tool-loop guardrail hard-stopped ``computer_use`` for the rest of the turn.

These assert the recovery contract — revive once with the same id, retry once,
never loop — not the driver's exact wording.
"""

import pytest

from tools.computer_use.cua_backend import _CuaDriverSession


STALE_MSG = (
    "session 'hermes-abc123' has ended; tool call 'list_windows' was "
    "rejected. Call start_session with this id to revive it before issuing "
    "further actions, or use a new session id."
)
STALE = {"data": STALE_MSG, "images": [], "structuredContent": None, "isError": True}
OK = {"data": "ok", "images": [], "structuredContent": None, "isError": False}
ARGS = {"on_screen_only": True, "session": "hermes-abc123"}


class _FakeBridge:
    """Returns queued results in order; records the call it was handed."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    def run(self, call, timeout=None):
        self.calls.append(call)
        if not self._results:
            raise AssertionError(f"unexpected extra bridge call: {call}")
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _make_session(results) -> _CuaDriverSession:
    """A session wired to a fake bridge, with the transport stubbed out.

    ``_call_tool_async`` is replaced by a sentinel so the bridge records
    ``(name, args)`` per call and no coroutine is created (an un-awaited one
    would warn). Only the recovery ladder is under test.
    """
    session = object.__new__(_CuaDriverSession)
    session._started = True
    session._bridge = _FakeBridge(results)
    session._call_tool_async = lambda name, args: (name, dict(args))
    session._require_started = lambda: None
    return session


class TestStaleSessionDetection:
    def test_driver_rejection_is_detected(self):
        assert _CuaDriverSession._is_stale_session_result(STALE) is True

    def test_healthy_result_is_not_stale(self):
        assert _CuaDriverSession._is_stale_session_result(OK) is False

    def test_unrelated_error_is_not_stale(self):
        # Must not hijack the transient-daemon or generic failure paths.
        other = dict(STALE, data="Resource temporarily unavailable (os error 35)")
        assert _CuaDriverSession._is_stale_session_result(other) is False

    def test_non_string_payload_is_not_stale(self):
        # list_windows returns structured payloads; must not raise on them.
        assert _CuaDriverSession._is_stale_session_result(
            dict(STALE, data={"windows": []})
        ) is False

    def test_message_without_error_flag_is_not_stale(self):
        # A window *titled* like the rejection must not trigger a revive.
        assert _CuaDriverSession._is_stale_session_result(
            dict(OK, data=STALE_MSG)
        ) is False


class TestReviveAndRetry:
    def test_stale_session_is_revived_then_call_retried(self):
        session = _make_session([STALE, OK, OK])
        result = session.call_tool("list_windows", ARGS)

        assert result == OK
        assert session._bridge.calls == [
            ("list_windows", ARGS),
            ("start_session", {"session": "hermes-abc123"}),
            ("list_windows", ARGS),
        ], "must revive with the SAME id, then retry the original call"

    def test_revive_is_attempted_once_not_looped(self):
        # Still stale after a successful revive => surface it, don't spin.
        session = _make_session([STALE, OK, STALE])
        result = session.call_tool("list_windows", ARGS)

        assert result == STALE
        assert len(session._bridge.calls) == 3

    def test_failed_revive_surfaces_original_rejection(self):
        session = _make_session([STALE, RuntimeError("driver gone")])
        result = session.call_tool("list_windows", ARGS)

        assert result == STALE, "caller must still see why the call failed"
        assert len(session._bridge.calls) == 2

    def test_healthy_call_is_untouched(self):
        session = _make_session([OK])
        assert session.call_tool("list_windows", ARGS) == OK
        assert len(session._bridge.calls) == 1

    def test_lifecycle_calls_are_never_revived(self):
        # start_session reviving itself would recurse.
        session = _make_session([STALE])
        result = session.call_tool("start_session", {"session": "hermes-abc123"})

        assert result == STALE
        assert len(session._bridge.calls) == 1

    def test_call_without_session_arg_is_not_revived(self):
        # Nothing to revive with; must not invent an id.
        session = _make_session([STALE])
        result = session.call_tool("list_windows", {"on_screen_only": True})

        assert result == STALE
        assert len(session._bridge.calls) == 1

    @pytest.mark.parametrize("tool", ["list_windows", "screenshot", "get_window_state"])
    def test_revive_applies_to_every_capture_stage_tool(self, tool):
        # The rejection is raised by whichever tool runs first in capture().
        session = _make_session([STALE, OK, OK])
        assert session.call_tool(tool, ARGS) == OK
        assert session._bridge.calls[1][0] == "start_session"
