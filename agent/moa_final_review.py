"""MoA final-submission review.

The reference model reviews the acting agent's DRAFTED final answer just before it
is sent to the user; if it flags a MATERIAL problem, the aggregator revises once.
Together with ``fanout: user_turn`` (first-plan critique) this bookends the turn:
critique the plan going in, sanity-check the answer coming out.

Contract: fail-open and opt-in. ``maybe_final_review`` returns the ORIGINAL
``final_response`` unchanged when the preset flag is off, when the answer is not a
substantive user-facing answer (empty / error / interrupt), or on ANY exception. It
never raises into the turn and is bounded by a short per-call timeout so a flapping
local endpoint cannot stall delivery. Adds at most two model calls (one reviewer,
one aggregator revision) and only when ``final_review`` is enabled on the preset.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_REVIEW_TIMEOUT_S = 40.0
_ANSWER_CAP = 6000       # chars of the drafted answer shown to the reviewer
_REQUEST_CAP = 2000      # chars of the user request
_EVIDENCE_CAP = 2500     # total chars of recent tool evidence
_EVIDENCE_MAX_MSGS = 4
_MIN_ANSWER_CHARS = 40   # below this, not worth a review pass
_REVIEWER_MAX_TOKENS = 800

# Non-answers we must never "review" — reviewing an error string would just turn a
# clean failure message into confusing prose.
_SKIP_PREFIXES = (
    "i apologize, but i encountered repeated errors",
    "invalid api response",
    "request payload too large",
    "context length exceeded",
    "(empty)",
)

_REVIEWER_SYSTEM = (
    "You are the final-submission reviewer in a Mixture of Agents process. The acting "
    "agent has produced the answer below and is about to send it to the user. Your job "
    "is a last-line sanity check of the ANSWER ITSELF - not the plan, not the style.\n"
    "Check only for MATERIAL problems: factual or logic errors, numbers that don't foot "
    "or contradict the work shown, claims of actions or results the work does not "
    "support, a part of the user's request that went unanswered, or an unsafe / "
    "irreversible action described as already done when it wasn't.\n"
    "Be disciplined: if the answer is sound, reply with exactly \"OK\" and nothing else. "
    "Only if there is a MATERIAL problem, reply with one or two sentences naming it and "
    "the concrete fix. Do NOT nitpick wording, suggest extra work the user didn't ask "
    "for, or ask for access. Assume any referenced files or systems exist."
)

_REVISE_SYSTEM = (
    "You are the acting agent. Below is the final answer you drafted for the user and a "
    "reviewer's flag. If the flag is correct, return a corrected final answer. If the flag "
    "is wrong or immaterial, return your original answer unchanged. Return ONLY the final "
    "answer text to send to the user - no meta commentary, no mention of the reviewer."
)


def _extract_text(response: Any) -> str:
    """Assistant text with the gpt-oss ``reasoning_content`` fallback (mirrors
    ``agent.amdp.loop._extract_text``: reasoning-only models put the field in
    ``message.model_extra``, not as a declared attribute)."""
    try:
        message = response.choices[0].message
    except (AttributeError, IndexError, TypeError):
        return ""
    if isinstance(message, dict):
        for field in ("content", "reasoning_content", "reasoning"):
            val = message.get(field)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return ""
    extra = getattr(message, "model_extra", None)
    if not isinstance(extra, dict):
        extra = {}
    for field in ("content", "reasoning_content", "reasoning"):
        val = getattr(message, field, None)
        if not (isinstance(val, str) and val.strip()):
            val = extra.get(field)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _call(slot: dict, messages: list, *, temperature, max_tokens: int) -> str:
    from agent.auxiliary_client import call_llm
    from agent.moa_loop import _slot_runtime

    runtime = _slot_runtime(slot)
    resp = call_llm(
        task="moa_final_review",
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=_REVIEW_TIMEOUT_S,
        **runtime,
    )
    return _extract_text(resp)


def _is_substantive(text: Any) -> bool:
    if not isinstance(text, str):
        return False
    stripped = text.strip()
    if len(stripped) < _MIN_ANSWER_CHARS:
        return False
    low = stripped.lower()
    if any(low.startswith(p) for p in _SKIP_PREFIXES):
        return False
    if "waiting for model response" in low and "elapsed)" in low:
        return False
    return True


def _last_user_request(messages: list) -> str:
    for m in reversed(messages or []):
        if isinstance(m, dict) and m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                return c
            if isinstance(c, list):  # multimodal parts
                return " ".join(
                    str(p.get("text", "")) for p in c if isinstance(p, dict)
                ).strip()
    return ""


def _recent_evidence(messages: list, cap: int) -> str:
    out: list[str] = []
    total = 0
    for m in reversed(messages or []):
        if isinstance(m, dict) and m.get("role") == "tool":
            c = m.get("content")
            if isinstance(c, str) and c.strip():
                snip = c.strip()[:800]
                out.append(snip)
                total += len(snip)
                if total >= cap or len(out) >= _EVIDENCE_MAX_MSGS:
                    break
    return "\n---\n".join(reversed(out))


def _flag_is_material(verdict: str) -> bool:
    """The reviewer answers "OK" when the draft is sound. Anything else that isn't a
    trivial endorsement is treated as a material flag (the aggregator revision step
    can still reject a wrong flag, so a false positive costs one call, not a bad edit)."""
    v = (verdict or "").strip()
    if not v:
        return False  # blank reviewer output = no actionable flag; ship as-is
    head = v.splitlines()[0].strip().strip('"').strip().rstrip(".").upper()
    if head == "OK" or head.startswith("OK "):
        return False
    low = v.lower()
    if len(v) < 12 and any(w in low for w in ("ok", "fine", "good", "sound")):
        return False
    return True


def maybe_final_review(agent: Any, final_response: Any, messages: list, moa_config: Any) -> Any:
    """Return the (possibly revised) final answer. Opt-in, fail-open, never raises."""
    try:
        if not isinstance(moa_config, dict) or not moa_config.get("final_review"):
            return final_response
        if not _is_substantive(final_response):
            return final_response

        refs = moa_config.get("reference_models") or []
        aggregator = moa_config.get("aggregator") or {}
        if not refs or not aggregator:
            return final_response
        reviewer = refs[0]

        request = _last_user_request(messages)[:_REQUEST_CAP]
        evidence = _recent_evidence(messages, _EVIDENCE_CAP)
        answer = str(final_response)[:_ANSWER_CAP]

        review_user = (
            (f"User's request:\n{request}\n\n" if request else "")
            + (f"Work / evidence from this turn (truncated):\n{evidence}\n\n" if evidence else "")
            + f"DRAFTED final answer to review:\n{answer}"
        )
        verdict = _call(
            reviewer,
            [
                {"role": "system", "content": _REVIEWER_SYSTEM},
                {"role": "user", "content": review_user},
            ],
            temperature=moa_config.get("reference_temperature"),
            max_tokens=_REVIEWER_MAX_TOKENS,
        )

        if not _flag_is_material(verdict):
            logger.info("MoA final review: answer passed (verdict=%r)", (verdict or "")[:80])
            return final_response

        logger.info("MoA final review flagged a material issue: %s", verdict.strip()[:200])
        revise_user = (
            (f"User's request:\n{request}\n\n" if request else "")
            + f"Your drafted answer:\n{answer}\n\nReviewer flag:\n{verdict.strip()[:800]}"
        )
        revised = _call(
            aggregator,
            [
                {"role": "system", "content": _REVISE_SYSTEM},
                {"role": "user", "content": revise_user},
            ],
            temperature=moa_config.get("aggregator_temperature"),
            max_tokens=moa_config.get("max_tokens") or 4096,
        )
        if _is_substantive(revised):
            logger.info(
                "MoA final review: answer revised (%d -> %d chars)",
                len(str(final_response)), len(revised),
            )
            return revised
        return final_response
    except Exception as exc:  # fail-open: a review must never break delivery
        logger.warning("MoA final review skipped (fail-open): %s", exc)
        return final_response
