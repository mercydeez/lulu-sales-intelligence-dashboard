"""
Finaliser node (Phase 5) — promote the draft to the final answer + confidence.

Confidence comes from the validation stack when it ran (arbiter → critic), else a
provisional grounded/fallback value. The rendered confidence BADGE, collapsible
SQL, and citation block are produced by the frontend from the SSE 'done' meta
(sage3_meta) — the finaliser keeps final_answer clean so the spoken/voice answer
isn't cluttered. It DOES append a short honesty caveat when the cross-validator
flagged figures it couldn't verify, so the text itself never over-claims.
"""
from __future__ import annotations

from typing import Optional

from ..state import AgentState, add_trace

_GROUNDED_CONF = 0.75
_FALLBACK_CONF = 0.5
_CAVEAT = ("\n\n⚠️ _Some figures couldn't be fully verified against the returned "
           "data — please double-check before acting on them._")


def _resolve_confidence(state: AgentState) -> Optional[float]:
    """Confidence in the ANSWER, or None when this turn isn't an answer.

    A clarifying question or a read-back is a dialogue turn: the validation stack
    never ran, so there is no evidence to be confident about. Emitting a number
    here (the old `_FALLBACK_CONF`) badged a question we asked the USER with a
    made-up score, which reads as "the model is unsure of its own answer".
    """
    if state.get("needs_clarification") or state.get("needs_readback"):
        return None
    arb = state.get("arbiter_verdict") or {}
    if "confidence" in arb:
        return float(arb["confidence"])
    crit = state.get("critic_verdict") or {}
    if "confidence" in crit:
        return float(crit["confidence"])
    return _GROUNDED_CONF if state.get("grounded") else _FALLBACK_CONF


async def finaliser_node(state: AgentState) -> AgentState:
    answer = state.get("draft_answer", "") or ""

    # Honesty caveat only for grounded answers the cross-validator couldn't fully
    # support (never on clarification/readback turns).
    arb = state.get("arbiter_verdict") or {}
    if (arb.get("unsupported") and state.get("grounded")
            and not state.get("needs_clarification") and not state.get("needs_readback")):
        answer = answer + _CAVEAT

    state["final_answer"] = answer
    state["final_confidence"] = _resolve_confidence(state)

    tag = ("clarification" if state.get("needs_clarification")
           else "readback" if state.get("needs_readback")
           else "grounded" if state.get("grounded") else "rule-based")
    conf = state["final_confidence"]
    conf_txt = f"{conf:.2f}" if conf is not None else "n/a (dialogue turn)"
    add_trace(state, "finaliser", f"final ready (confidence {conf_txt}, {tag})",
              confidence=conf)
    return state
