"""Tests for the pluggable state feed — the upstream-standalone guarantee.

The key property: AMDP plans using only the universal gateway runtime status,
with no proprioception plugin installed. Proprioception is optional enrichment.
"""

from __future__ import annotations

import json

from agent.amdp import loop, state

COA_JSON = json.dumps({"coas": [
    {"coa_id": "A", "summary": "s1", "dispatches": [{"task": "t1", "kind": "observe"}]},
    {"coa_id": "B", "summary": "s2", "dispatches": [{"task": "t2", "kind": "act"}]},
]})
REVIEW_JSON = json.dumps({"alignment_1to10": 7, "fragility_0to1": 0.4,
                          "risks": [{"desc": "r", "severity_1to5": 3}]})
MULTISTEP = "Migrate the database end-to-end and deploy the pipeline."


# --- gateway feed (universal, no plugins) ---
def test_gateway_feed_is_not_blind_when_status_present(monkeypatch):
    import gateway.status as gs
    monkeypatch.setattr(gs, "read_runtime_status", lambda path=None: {"gateway_state": "running", "active_agents": 2})
    s = state.gateway_feed({})
    assert s["sensors_down"] == []            # gateway status present -> not blind
    assert s["gateway_state"] == "running"
    assert "gateway status" in s["brief"]


def test_gateway_feed_is_blind_when_no_status(monkeypatch):
    import gateway.status as gs
    monkeypatch.setattr(gs, "read_runtime_status", lambda path=None: None)
    s = state.gateway_feed({})
    assert "gateway-status" in s["sensors_down"]   # truly blind -> planner refuses


# --- auto resolution without the proprioception plugin ---
def test_auto_uses_gateway_when_proprioception_absent(monkeypatch):
    monkeypatch.setattr(state, "_proprioception_available", lambda: False)
    import gateway.status as gs
    monkeypatch.setattr(gs, "read_runtime_status", lambda path=None: {"gateway_state": "running"})
    s = state.get_believed_state({}, mode="auto")
    assert s["gateway_state"] == "running" and s["sensors_down"] == []


def test_proprioception_mode_falls_back_to_gateway_when_plugin_missing(monkeypatch):
    # Force the plugin import inside proprioception_feed to fail.
    import builtins
    real_import = builtins.__import__

    def blocked(name, *a, **k):
        if name.startswith("plugins.proprioception"):
            raise ImportError("no proprioception plugin (upstream install)")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", blocked)
    import gateway.status as gs
    monkeypatch.setattr(gs, "read_runtime_status", lambda path=None: {"gateway_state": "running"})
    s = state.proprioception_feed({})
    assert s["gateway_state"] == "running" and s["sensors_down"] == []   # degraded to gateway feed


# --- full integration: AMDP plans with ONLY gateway status (the upstream case) ---
def test_amdp_plans_with_gateway_feed_only(monkeypatch, tmp_path):
    import gateway.status as gs
    monkeypatch.setattr(gs, "read_runtime_status", lambda path=None: {"gateway_state": "running"})
    monkeypatch.setattr(loop, "_call",
                        lambda slot, m, **k: (COA_JSON if slot.get("provider") == "planner-prov" else REVIEW_JSON, ""))
    monkeypatch.setattr(loop, "_audit_path", lambda cfg: str(tmp_path / "a.jsonl"))
    cfg = {"amdp": {
        "enabled": True,
        "planner": {"provider": "planner-prov", "model": "pm"},
        "reviewer": {"provider": "reviewer-prov", "model": "rm"},
        "gate": {"min_estimated_steps": 1},
        "state_feed": "gateway",
    }}
    out = loop.maybe_amdp_context(MULTISTEP, [], cfg)
    assert out and "AMDP plan" in out    # planned with no proprioception plugin at all
    rec = json.loads((tmp_path / "a.jsonl").read_text(encoding="utf-8").strip())
    assert rec["refused"] is False


def test_state_feed_config_validates():
    from agent.amdp.config import resolve_amdp_config
    base = {"enabled": True, "planner": {"provider": "p", "model": "m"}, "reviewer": {"provider": "r", "model": "m"}}
    assert resolve_amdp_config({"amdp": base}).state_feed == "auto"              # default
    assert resolve_amdp_config({"amdp": dict(base, state_feed="gateway")}).state_feed == "gateway"
    assert resolve_amdp_config({"amdp": dict(base, state_feed="bogus")}).state_feed == "auto"  # unknown -> auto
