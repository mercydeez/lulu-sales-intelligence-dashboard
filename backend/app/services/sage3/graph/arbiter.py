"""
Arbiter node (Phase 4) — reconcile the critic and the cross-validator.

When they agree, it averages their confidence. When they disagree (e.g. the critic
passed but the cross-validator found an unsupported figure), it takes the
CONSERVATIVE view — the lower confidence wins and any unsupported figures are
surfaced as a caveat — so a plausible-but-wrong answer can't slip through on a
single optimistic vote. Pure/deterministic: no LLM needed.
"""
from __future__ import annotations

from ..state import AgentState, add_trace


async def arbiter_node(state: AgentState) -> AgentState:
    critic = state.get("critic_verdict") or {}
    cross = state.get("cross_check") or {}
    # Only average the voters that actually ran. Defaulting a missing node to 0.5
    # meant one absent voter halved a confident answer's score and pushed it under
    # the 0.7 pass line — an abstention should not count as a vote of no confidence.
    votes = [float(v["confidence"]) for v in (critic, cross) if "confidence" in v]
    supported = bool(cross.get("supported", True))

    if supported:
        confidence = round(sum(votes) / len(votes), 2) if votes else 0.5
        verdict = "pass" if confidence >= 0.7 else "uncertain"
        rationale = ("critic and cross-validator agree" if len(votes) > 1
                     else "single validator, no disagreement")
    else:
        # Disagreement → conservative: penalise and caveat.
        confidence = round((min(votes) if votes else 0.5) * 0.8, 2)
        verdict = "retry" if confidence < 0.5 else "uncertain"
        rationale = "cross-validator found unsupported figures; took the cautious view"

    state["arbiter_verdict"] = {
        "confidence": confidence, "verdict": verdict, "rationale": rationale,
        "unsupported": cross.get("unsupported", []),
    }
    add_trace(state, "arbiter", f"{verdict} @ {confidence:.2f} — {rationale}",
              confidence=confidence)
    return state
