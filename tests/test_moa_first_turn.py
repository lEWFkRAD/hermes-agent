"""Unit tests for the first_turn fanout cadence (references fire only on the
opening user turn; final_review is the other bookend). Offline, no GPU."""
import agent.moa_loop as ml
from hermes_cli.moa_config import _coerce_fanout, _normalize_preset

ADV = ml._ADVISORY_INSTRUCTION
def U(c): return {"role": "user", "content": c}
def A(c): return {"role": "assistant", "content": c}
def T(c): return {"role": "tool", "content": c}


def test_coerce_fanout_allows_first_turn():
    assert _coerce_fanout("first_turn") == "first_turn"
    assert _coerce_fanout("user_turn") == "user_turn"
    assert _coerce_fanout("bogus") == "per_iteration"


def test_normalizer_keeps_first_turn():
    assert _normalize_preset({"fanout": "first_turn"})["fanout"] == "first_turn"


def test_skip_never_for_other_modes():
    two_turns = [U("a"), A("b"), U("c")]
    assert ml._first_turn_skip("user_turn", two_turns) is False
    assert ml._first_turn_skip("per_iteration", two_turns) is False


def test_first_turn_runs_on_opening_turn():
    assert ml._first_turn_skip("first_turn", [U("do the thing")]) is False
    # mid-tool-loop growth: assistant/tool + synthetic advisory marker, still ONE real user
    msgs = [U("do the thing"), A("calling tool"), T("result"), U(ADV)]
    assert ml._first_turn_skip("first_turn", msgs) is False


def test_first_turn_skips_after_opening():
    assert ml._first_turn_skip("first_turn", [U("first"), A("done"), U("second")]) is True
    # advisory markers interleaved must not confuse the count -> still 2 real users
    msgs = [U("first"), A("x"), T("y"), U(ADV), A("z"), U("second")]
    assert ml._first_turn_skip("first_turn", msgs) is True
