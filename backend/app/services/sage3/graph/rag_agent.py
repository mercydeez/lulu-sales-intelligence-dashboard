"""
RAG agent node — routes document questions through the zero-hallucination
pipeline (rag/pipeline.py::answer_grounded): RBAC-scoped hybrid retrieval →
source-confidence gate → constrained cited generation → output guardrails.

RBAC is enforced: role + allowed_stores come from AgentState (set once from the
JWT, HARD INVARIANT) and scope retrieval so this node can never surface a chunk
the caller isn't allowed to see. Below the confidence threshold it refuses
(ok=False) instead of guessing. Never raises.
"""
from __future__ import annotations

import logging

from app.services.llm import get_provider_chain
from app.services.rag.pipeline import answer_grounded
from ..state import AgentState, add_trace

logger = logging.getLogger(__name__)


async def rag_agent_node(state: AgentState) -> AgentState:
    providers = get_provider_chain()
    g = await answer_grounded(
        state["user_query"], state["tenant_id"],
        role=state.get("role"), allowed_stores=state.get("allowed_stores") or None,
        providers=providers,
    )
    state["rag_result"] = {
        "ok": g.ok, "answer": g.answer,
        "citations": g.citations, "chunks": [],
        "confidence": g.confidence, "refused": g.refused,
    }
    if g.ok:
        for c in g.citations:
            state.setdefault("evidence", []).append({"kind": "doc", "citation": c})
    add_trace(state, "rag_agent",
              f"rag ok={g.ok}, conf={g.confidence}, {len(g.citations)} citation(s)"
              + (f", refused={g.refusal_reason}" if g.refused else ""))
    return state
