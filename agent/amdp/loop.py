"""AMDP episode loop, integrated into the agent runtime.

Same shape as the proven out-of-tree prototype, but wired to real
infrastructure: model calls go through ``agent.auxiliary_client.call_llm``
(resolved via MoA's ``_slot_runtime``), and believed state comes from the
proprioception collector's snapshot instead of raw HTTP.

``maybe_amdp_context`` is the single entry point the conversation loop calls.
It is fail-closed: it returns ``""`` (inject nothing, proceed normally) on a
disabled config, a turn that doesn't clear the gate, blind/stale state, or ANY
exception. It never raises into the turn.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from agent.amdp import prompts, schemas, scoring
from agent.amdp.config import AmdpConfig, resolve_amdp_config

logger = logging.getLogger(__name__)

_MAX_REVIEW_WORKERS = 8


# --------------------------------------------------------------------------- #
# Model plumbing (real infra)
# --------------------------------------------------------------------------- #
def _extract_text(response: Any) -> str:
    """Assistant text with the gpt-oss reasoning_content fallback."""
    try:
        message = response.choices[0].message
    except (AttributeError, IndexError, TypeError):
        return ""
    for field in ("content", "reasoning_content", "reasoning"):
        val = message.get(field) if isinstance(message, dict) else getattr(message, field, None)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _call(
    slot: dict[str, str],
    messages: list[dict[str, Any]],
    *,
    temperature: float | None,
    max_tokens: int | None,
    json_mode: bool = False,
) -> tuple[str, str]:
    """One model call through call_llm. Returns (text, error). Never raises."""
    try:
        from agent.auxiliary_client import call_llm
        from agent.moa_loop import _slot_runtime

        runtime = _slot_runtime(slot)
        extra_body = {"response_format": {"type": "json_object"}} if json_mode else None
        response = call_llm(
            task="amdp",
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
            **runtime,
        )
        return _extract_text(response), ""
    except Exception as exc:  # fail-closed
        logger.warning("AMDP model call failed for %s: %s", slot, exc)
        return "", f"{type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------- #
# State intake (proprioception collector)
# --------------------------------------------------------------------------- #
def _proprioception_settings(config: dict[str, Any]) -> dict[str, Any]:
    from plugins.proprioception.settings import DEFAULTS

    merged = dict(DEFAULTS)
    block = (config or {}).get("proprioception")
    if isinstance(block, dict):
        merged.update(block)
    return merged


def _intake(config: dict[str, Any]) -> dict[str, Any]:
    """Return {brief, sensors_down, staleness_s} from the live snapshot. Never
    raises; on failure reports every sensor down so the gate refuses."""
    try:
        from plugins.proprioception.collector import ATTENTION_STATES, get_snapshot

        settings = _proprioception_settings(config)
        snap = get_snapshot(settings, force=True)
        systems = (snap.dashboard or {}).get("systems") or []
        attention = [
            s for s in systems if isinstance(s, dict) and str(s.get("state")) in ATTENTION_STATES
        ]
        verdict = "attention" if attention else ("ok" if snap.dashboard is not None else "unknown")
        lines = [f"overall verdict: {verdict}", f"gateway: {snap.gateway_state}"]
        if snap.sensors_down:
            lines.append(f"sensors DOWN: {', '.join(snap.sensors_down)}")
        if snap.dashboard_stale_for:
            lines.append(f"state staleness: {snap.dashboard_stale_for:.0f}s")
        if attention:
            lines.append("systems needing attention:")
            for s in attention[:12]:
                lines.append(f"  - {s.get('label', s.get('id', '?'))}: {s.get('state')} ({s.get('detail', '')})")
        else:
            lines.append(f"all {len(systems)} monitored systems calm")
        return {
            "brief": "\n".join(lines),
            "sensors_down": list(snap.sensors_down),
            "staleness_s": float(snap.dashboard_stale_for or 0.0),
            "verdict": verdict,
            "gateway_state": snap.gateway_state,
            "system_count": len(systems),
        }
    except Exception as exc:
        logger.warning("AMDP state intake failed: %s", exc)
        return {"brief": "", "sensors_down": ["intake-failed"], "staleness_s": 0.0,
                "verdict": "unknown", "gateway_state": "unknown", "system_count": 0}


def _should_refuse(state: dict[str, Any], *, staleness_max_s: float) -> tuple[bool, str]:
    if state.get("sensors_down"):
        return True, f"sensors down: {', '.join(state['sensors_down'])}"
    if state.get("staleness_s", 0) > staleness_max_s:
        return True, f"state staleness {state['staleness_s']:.0f}s exceeds max {staleness_max_s:.0f}s"
    return False, ""


# --------------------------------------------------------------------------- #
# Gate — is this turn dispatch-worthy? (cheap heuristic, no model call)
# --------------------------------------------------------------------------- #
_MULTISTEP_HINTS = re.compile(
    r"\b(migrate|refactor|pipeline|deploy|and then|then\b|after that|first\b|"
    r"step\s*\d|each of|all of|for every|for each|end[- ]to[- ]end|multi[- ]step)\b",
    re.IGNORECASE,
)


def _estimate_steps(user_prompt: str, api_messages: list[dict[str, Any]]) -> int:
    """Very cheap dispatch-worthiness estimate. Don't spend a model call deciding
    whether to spend model calls."""
    text = user_prompt or ""
    score = 0
    score += len(_MULTISTEP_HINTS.findall(text))
    score += text.count("\n- ") + text.count("\n1.") + text.count("\n2.")  # list items
    if len(text) > 400:
        score += 1
    tool_msgs = sum(1 for m in api_messages if isinstance(m, dict) and m.get("role") == "tool")
    if tool_msgs >= 3:
        score += 1
    return score


# --------------------------------------------------------------------------- #
# Planner (ported from the proven prototype)
# --------------------------------------------------------------------------- #
def _generate_coas(cfg: AmdpConfig, intent: str, state_brief: str, errors: list[str]) -> list[dict[str, Any]]:
    msgs = prompts.commander_prompt(intent, state_brief, cfg.n_coas)
    text, err = _call(cfg.planner, msgs, temperature=0.4, max_tokens=3500, json_mode=True)
    if not text:
        errors.append(f"commander failed: {err or 'empty'}")
        return []
    try:
        return schemas.coerce_coas(schemas.extract_json(text))
    except ValueError as exc:
        errors.append(f"COA parse failed ({exc}); retrying")
    repair = msgs + [
        {"role": "assistant", "content": text[:2000]},
        {"role": "user", "content": "Return ONLY the JSON object with a top-level 'coas' array. No prose."},
    ]
    text2, err2 = _call(cfg.planner, repair, temperature=0.1, max_tokens=3500, json_mode=True)
    if not text2:
        errors.append(f"commander repair failed: {err2 or 'empty'}")
        return []
    try:
        return schemas.coerce_coas(schemas.extract_json(text2))
    except ValueError as exc:
        errors.append(f"COA parse failed after repair: {exc}")
        return []


def _review_one(cfg: AmdpConfig, intent: str, state_brief: str, coa: dict[str, Any]) -> dict[str, Any]:
    msgs = prompts.review_prompt(intent, state_brief, coa)
    text, _err = _call(cfg.reviewer, msgs, temperature=0.3, max_tokens=cfg.reviewer_max_tokens)
    if text:
        try:
            return schemas.coerce_review(schemas.extract_json(text), coa["coa_id"])
        except ValueError:
            pass
    repair = msgs + [
        {"role": "assistant", "content": (text or "")[:1500]},
        {"role": "user", "content": "Return ONLY the JSON verdict object. No prose."},
    ]
    text2, _err2 = _call(cfg.reviewer, repair, temperature=0.1, max_tokens=cfg.reviewer_max_tokens)
    if text2:
        try:
            return schemas.coerce_review(schemas.extract_json(text2), coa["coa_id"])
        except ValueError:
            pass
    return {
        "coa_id": coa["coa_id"], "alignment_1to10": 0.0,
        "risks": [{"desc": "reviewer unavailable — COA unvetted", "severity_1to5": 5}],
        "unstated_assumptions": [], "fragility_0to1": 1.0, "_review_failed": True,
    }


def _review_all(cfg: AmdpConfig, intent: str, state_brief: str, coas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any] | None] = [None] * len(coas)
    workers = min(_MAX_REVIEW_WORKERS, len(coas)) or 1
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_review_one, cfg, intent, state_brief, c): i for i, c in enumerate(coas)}
        for fut, i in futs.items():
            results[i] = fut.result()
    return [r for r in results if r is not None]


def _decide(cfg: AmdpConfig, coas: list[dict[str, Any]], reviews: list[dict[str, Any]], staleness_norm: float):
    review_by_id = {r["coa_id"]: r for r in reviews}
    scored = []
    for coa in coas:
        review = review_by_id.get(coa["coa_id"]) or {"coa_id": coa["coa_id"], "alignment_1to10": 0.0, "risks": [], "fragility_0to1": 1.0}
        by_profile = {
            name: {"score": round(scoring.score(review, staleness_norm=staleness_norm, profile=name).score, 3)}
            for name in scoring.PROFILES
        }
        scored.append({"coa": coa, "review": review, "scores": by_profile})
    prof = cfg.decision_profile
    best = max(scored, key=lambda s: (s["scores"][prof]["score"], -len(s["coa"]["dispatches"])))
    return best, scored


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #
def _audit_path(cfg: AmdpConfig) -> str:
    home = os.environ.get("HERMES_HOME") or os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes")
    return os.path.join(home, cfg.audit_log)


def _append_audit(cfg: AmdpConfig, record: dict[str, Any]) -> None:
    try:
        path = _audit_path(cfg)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:  # audit must never break a turn
        logger.debug("AMDP audit write failed: %s", exc)


# --------------------------------------------------------------------------- #
# Plan rendering + entry point
# --------------------------------------------------------------------------- #
def _render_plan(best: dict[str, Any], cfg: AmdpConfig) -> str:
    coa, review = best["coa"], best["review"]
    lines = [
        "[AMDP plan — private guidance for the agent loop. You may follow it, adapt it, "
        "or finish normally; you own tool calling and turn termination.]",
        f"Chosen course of action ({coa['coa_id']}): {coa['summary']}",
        "Dispatches:",
    ]
    for i, d in enumerate(coa["dispatches"], 1):
        flag = " [IRREVERSIBLE — confirm before acting]" if d.get("irreversible") else ""
        crit = f" success: {'; '.join(d['success_criteria'])}" if d.get("success_criteria") else ""
        lines.append(f"  {i}. [{d['kind']}]{flag} {d['task']}.{crit}")
    if coa.get("assumptions"):
        lines.append("Assumptions: " + "; ".join(coa["assumptions"][:5]))
    if review.get("risks"):
        top = sorted(review["risks"], key=lambda r: r.get("severity_1to5", 0), reverse=True)[:3]
        lines.append("Watch for: " + "; ".join(f"{r['desc']} (sev {r['severity_1to5']})" for r in top))
    return "\n".join(lines)


def maybe_amdp_context(
    user_prompt: str,
    api_messages: list[dict[str, Any]],
    config: dict[str, Any] | None,
) -> str:
    """The single entry point. Returns an injectable plan block, or "" to inject
    nothing and let the agent proceed normally. Fail-closed."""
    t0 = time.monotonic()
    try:
        cfg = resolve_amdp_config(config)
        if cfg is None:
            return ""  # AMDP absent/disabled

        est = _estimate_steps(user_prompt, api_messages)
        if est < cfg.min_estimated_steps:
            return ""  # not dispatch-worthy; don't spend model calls

        state = _intake(config or {})
        refuse, reason = _should_refuse(state, staleness_max_s=cfg.staleness_max_s)
        if refuse:
            _append_audit(cfg, {
                "ts": time.time(), "intent": user_prompt[:2000], "refused": True,
                "refuse_reason": reason, "believed_state": {k: state[k] for k in ("verdict", "gateway_state", "sensors_down", "staleness_s", "system_count")},
            })
            logger.info("AMDP refused to plan: %s", reason)
            return ""

        errors: list[str] = []
        coas = _generate_coas(cfg, user_prompt, state["brief"], errors)
        if not coas:
            _append_audit(cfg, {"ts": time.time(), "intent": user_prompt[:2000], "coas": 0, "errors": errors})
            return ""
        reviews = _review_all(cfg, user_prompt, state["brief"], coas)
        staleness_norm = min(1.0, state["staleness_s"] / cfg.staleness_max_s) if cfg.staleness_max_s else 0.0
        best, scored = _decide(cfg, coas, reviews, staleness_norm)

        _append_audit(cfg, {
            "ts": time.time(), "intent": user_prompt[:2000], "refused": False,
            "decision_profile": cfg.decision_profile, "estimated_steps": est,
            "believed_state": {k: state[k] for k in ("verdict", "gateway_state", "sensors_down", "staleness_s", "system_count")},
            "coas": coas, "reviews": reviews,
            "scores": [{"coa_id": s["coa"]["coa_id"], "by_profile": s["scores"]} for s in scored],
            "chosen": best["coa"]["coa_id"], "errors": errors,
            "elapsed_s": round(time.monotonic() - t0, 2),
        })
        return _render_plan(best, cfg)
    except Exception as exc:  # fail-closed: never break the turn
        logger.warning("AMDP planning failed, proceeding without a plan: %s", exc)
        return ""
