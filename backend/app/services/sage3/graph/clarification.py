"""
Clarification node (Phase 2).

When intent clarity is low, the graph short-circuits here instead of guessing: it
emits ONE focused clarifying question as the answer and marks needs_clarification.
The runtime stores the pending question; the user's next message is folded into a
refined query and re-run (capped at 2 rounds so it can never loop forever). No SQL
runs on a clarification turn — nothing is fabricated.
"""
from __future__ import annotations

from ..state import AgentState, add_trace

_PREFIX = "🤔 Quick check so I answer the right thing — "


async def clarification_node(state: AgentState) -> AgentState:
    q = state.get("clarification_question")
    if not q:
        amb = state.get("ambiguities") or []
        q = amb[0] if amb else "Could you specify the store, time period, or metric you mean?"

    state["needs_clarification"] = True
    state["draft_answer"] = _PREFIX + q
    state["grounded"] = False
    state["clarification_question"] = q
    add_trace(state, "clarification",
              f"asked (round {state.get('clarification_round', 0) + 1}): {q[:60]}")
    return state
