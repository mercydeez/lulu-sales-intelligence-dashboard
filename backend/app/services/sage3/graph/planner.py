"""
Planner node — record the sub-question plan for a multi-part query.

The heavy lifting (decompose → per-sub NL→SQL/RAG → recompose) lives in
sage2.answer_multipart, which the hybrid executor calls next. To avoid a second
LLM decompose call, the planner derives a deterministic plan preview from the
sage2 intent matcher (and zone) purely for the user-facing trace; when no intents
match it notes that the executor will decompose with the LLM.
"""
from __future__ import annotations

from app.services.sage2.intents import match_intents, extract_zone
from ..state import AgentState, add_trace


async def planner_node(state: AgentState) -> AgentState:
    q = state["user_query"]
    zone = extract_zone(q)
    labels = [i.label for i in match_intents(q)]
    plan = {"sub_questions": labels, "zone": zone}
    hr = state.get("hybrid_result") or {}
    hr["plan"] = plan
    state["hybrid_result"] = hr
    preview = ", ".join(labels) if labels else "LLM decompose at executor"
    add_trace(state, "planner",
              f"plan: {preview}" + (f" [zone={zone}]" if zone else ""))
    return state
