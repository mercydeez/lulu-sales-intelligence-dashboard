"""
Synthesiser node — produce the draft answer from the chosen executor's result.

When the executor grounded an answer (nl2sql / rag / multipart), that grounded,
source-attributed text IS the draft (it already follows the bold-line, units≠AED
format from sage2/federation). When it didn't (no LLM configured, guard/exec
failure, or no matching doc), the synthesiser falls back to the EXISTING
deterministic, store-scoped rule-based responder so the demo always answers with
real data and zero paid keys (invariant #2).
"""
from __future__ import annotations

import logging

from app.services.ai_assistant import get_intelligent_fallback
from ..state import AgentState, add_trace

logger = logging.getLogger(__name__)


def _route_result(state: AgentState) -> dict:
    route = state.get("route", "sql")
    return {
        "sql": state.get("sql_result"),
        "rag": state.get("rag_result"),
        "hybrid": state.get("hybrid_result"),
    }.get(route) or {}


async def synthesiser_node(state: AgentState) -> AgentState:
    res = _route_result(state)
    if res.get("ok") and res.get("answer"):
        state["draft_answer"] = res["answer"]
        state["grounded"] = True
        add_trace(state, "synthesiser", f"grounded draft from {state.get('route')}")
        return state

    # Fallback: deterministic, RBAC-scoped rule-based responder (always answers).
    intent_info = state.get("intent") or {}
    fallback = await get_intelligent_fallback(
        state["user_query"], intent_info,
        state["tenant_id"], state.get("allowed_stores") or None,
    )
    state["draft_answer"] = fallback
    state["grounded"] = False
    add_trace(state, "synthesiser",
              f"rule-based fallback ({res.get('reason') or 'no grounded answer'})")
    return state
