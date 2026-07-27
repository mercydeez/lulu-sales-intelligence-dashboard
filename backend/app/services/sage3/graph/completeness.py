"""
Completeness node (Phase 4) — the recall gate.

Asks "did we answer EVERY part?" For a multi-part question, every planned
sub-question must have produced data; for a single read, the answer must be
grounded and non-empty. If something is missing and we haven't already retried,
it requests ONE reground (re-execute) — the orchestrator caps this at a single
extra pass so it can't loop. Deterministic by default; LLM optional for nuanced
"missing entity" detection.
"""
from __future__ import annotations

from typing import List

from app.services.llm import get_provider_chain
from ..state import AgentState, add_trace
from .llm_util import complete_json
from .prompts import COMPLETENESS_SYSTEM


def _heuristic_completeness(state: AgentState) -> dict:
    route = state.get("route")
    if route == "hybrid":
        parts = (state.get("hybrid_result") or {}).get("parts", [])
        missing = [p.get("label", "?") for p in parts if not p.get("ok")]
        return {"complete": not missing, "missing": missing}
    # sql / rag: complete if we produced a grounded, non-empty answer.
    answer = (state.get("draft_answer") or "").strip()
    complete = bool(answer) and state.get("grounded", False)
    return {"complete": complete, "missing": [] if complete else ["a grounded answer"]}


async def completeness_node(state: AgentState) -> AgentState:
    result = None
    providers = get_provider_chain()
    if providers:
        obj = await complete_json(providers, COMPLETENESS_SYSTEM,
                                  f"Question: {state.get('user_query','')}\n\n"
                                  f"ANSWER:\n{state.get('draft_answer','')}")
        if obj and "complete" in obj:
            obj.setdefault("missing", [])
            result = {"complete": bool(obj["complete"]), "missing": list(obj["missing"])}
    if result is None:
        result = _heuristic_completeness(state)

    state["completeness"] = result

    # Decide reground HERE (in the node) so the counter persists — a routing
    # function's state mutations are discarded by LangGraph, which would loop.
    rc = int(state.get("reground_count", 0))
    if not result["complete"] and rc < 1:
        state["reground_count"] = rc + 1
        state["want_reground"] = True
    else:
        state["want_reground"] = False

    miss = result.get("missing") or []
    add_trace(state, "completeness",
              ("complete" if result["complete"]
               else f"incomplete: {', '.join(map(str, miss))[:50]}"
                    + (" → reground" if state["want_reground"] else "")))
    return state
