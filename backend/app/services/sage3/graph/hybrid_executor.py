"""
Hybrid executor node — answer a multi-part question across domains/sources.

Reuses sage2.answer_multipart (decompose → route each sub to NL→SQL/RAG/API →
recompose into the bold-line, source-attributed table), threading
tenant_id/role/allowed_stores so every guarded sub-query is store-scoped
(app.allowed_store_ids GUC, migration 040). Preserves the existing grounded,
units≠AED output format. Never raises.
"""
from __future__ import annotations

import logging

from app.services.llm import get_provider_chain
from app.services.sage2 import answer_multipart
from app.services.sage2.orchestrator import INTERNAL_SOURCE
from ..state import AgentState, add_trace

logger = logging.getLogger(__name__)


async def hybrid_executor_node(state: AgentState) -> AgentState:
    providers = get_provider_chain()
    multi = await answer_multipart(
        state["user_query"],
        state["tenant_id"],
        role=state.get("role", "store_manager"),
        providers=providers,
        allowed_stores=state.get("allowed_stores") or None,
    )
    hr = state.get("hybrid_result") or {}
    hr.update({
        "ok": multi.ok, "answer": multi.answer,
        "reason": multi.reason, "used_llm": multi.used_llm,
        "parts": [{"label": p.label, "ok": p.ok, "source": p.source,
                   "sql": p.sql, "rows": p.rows, "error": p.error}
                  for p in multi.parts],
    })
    state["hybrid_result"] = hr
    if multi.ok:
        for p in multi.parts:
            if p.ok and p.sql:
                state.setdefault("evidence", []).append(
                    {"kind": "sql", "label": p.label, "sql": p.sql, "row_count": len(p.rows)})
            elif p.ok and p.source != INTERNAL_SOURCE:
                state.setdefault("evidence", []).append(
                    {"kind": "source", "label": p.label, "source": p.source})
    add_trace(state, "hybrid_executor",
              f"multipart ok={multi.ok}, {sum(1 for p in multi.parts if p.ok)}/{len(multi.parts)} parts")
    return state
