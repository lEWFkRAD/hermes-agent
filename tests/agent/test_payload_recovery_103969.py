"""Regression tests for #103969 gap 1 — asymmetric recovery on truncated
(non-streamed) tool-call payloads.

The non-streaming path in agent/turn_tool_validation.py treated a truncated
JSON arguments payload (unparsable AND not ending in ``}``/``]``) as fatal on
the FIRST occurrence: it reset ``_invalid_json_retries`` and returned a
terminal partial exit asserting "output length limit" — a cause that is often
false (finish_reason is frequently ``tool_calls`` because routers rewrite
``length``, see #91738). The streaming path (agent/turn_truncation.py) does
bounded recovery for the exact same failure class. Same defect, two entry
points, opposite outcomes.

Contract asserted here: truncated payloads take the SAME bounded invalid-JSON
recovery as every other invalid-args class (bounded re-issue, then the
existing recovery-results injection), the call never executes, and no error
text asserts an unproven output-length cause.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.turn_tool_validation import validate_tool_calls

TRUNCATED = '{"path":"report.md","content":"cut off mid str'


def _mock_tool_call(name, arguments, call_id):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _msg(tool_calls):
    return SimpleNamespace(content="", tool_calls=tool_calls)


def _agent():
    a = MagicMock()
    a.valid_tool_names = {"write_file"}
    a.log_prefix = ""
    a._invalid_json_retries = 0
    a._invalid_tool_retries = 0
    a._repair_tool_call.return_value = None
    a._uniquify_tool_call_ids = lambda tcs: None
    a._build_assistant_message = lambda m, fr: {"role": "assistant", "content": ""}
    return a


def _run(agent, tool_calls, messages, finish_reason="tool_calls"):
    return validate_tool_calls(
        agent, _msg(tool_calls), finish_reason=finish_reason,
        messages=messages, conversation_history=[],
        api_call_count=1, effective_task_id="task-1",
    )


def test_first_truncated_payload_retries_instead_of_terminating():
    """Gap 1: first truncated payload on the non-streaming path must request a
    bounded re-issue (verdict 'continue'), not a terminal partial exit."""
    agent = _agent()
    tc = _mock_tool_call("write_file", TRUNCATED, "c1")
    messages = []

    verdict = _run(agent, [tc], messages)

    assert verdict.action == "continue", (
        "truncated payload must retry like the streaming path, not terminate"
    )
    assert verdict.result is None
    # Nothing appended to history before the retry.
    assert messages == []


def test_truncation_shares_the_bounded_retry_counter():
    """Truncated payloads advance _invalid_json_retries so recovery stays
    bounded — the OLD code reset the counter on truncation, which killed the
    task on strike one and would loop forever if the hard-stop were simply
    removed without counting."""
    agent = _agent()

    first = _run(agent, [_mock_tool_call("write_file", TRUNCATED, "c1")], [])
    assert first.action == "continue"
    assert agent._invalid_json_retries == 1

    second = _run(agent, [_mock_tool_call("write_file", TRUNCATED, "c2")], [])
    assert second.action == "continue"
    assert agent._invalid_json_retries == 2


def test_exhaustion_injects_recovery_results_never_false_cause():
    """Once the bounded budget is exhausted the turn recovers via tool-role
    error results (model can agent-correct, role alternation preserved); it
    must not execute the call and must not blame an unproven 'output length
    limit' — routers rewrite finish_reason so that cause is unproven
    (#103969, #91738)."""
    agent = _agent()
    agent._invalid_json_retries = 2  # next strike exhausts the budget
    messages = []

    verdict = _run(agent, [_mock_tool_call("write_file", TRUNCATED, "c3")], messages)

    assert verdict.action == "continue"
    assert verdict.result is None
    assert any(
        m["role"] == "tool" and "invalid json" in m["content"].lower()
        for m in messages
    )
    for m in messages:
        assert "output length limit" not in str(m.get("content", "")).lower()


def test_no_first_strike_hard_stop_remains():
    """The first-strike hard-stop must be gone: the truncated branch may no
    longer reset the retry counter or return a terminal partial — recovery is
    bounded and shared with the invalid-JSON class."""
    import inspect

    import agent.turn_tool_validation as mod

    src = inspect.getsource(mod)
    # Locate the truncated branch and assert it contains neither the old
    # counter-reset nor the terminal return.
    i = src.index("if _truncated:")
    j = src.index("if agent._invalid_json_retries <", i)
    branch = src[i:j]
    assert "_invalid_json_retries = 0" not in branch
    assert '_verdict("return"' not in branch


