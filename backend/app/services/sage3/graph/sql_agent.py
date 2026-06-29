"""
SQL agent node — thin wrapper over the existing nl2sql pipeline.

Calls nl2sql.answer_question (LLM proposes SQL → allow-list guard → sage_ro
executor → narrate), threading the caller's RBAC scope. Store scope is
DB-enforced via the app.allowed_store_ids GUC (migration 040). Never raises:
on no-LLM / guard / exec failure it records ok=False and the synthesiser falls
back to the deterministic rule-based responder (invariant #2: works with no LLM).
"""
from __future__ import annotations

import logging

from app.services.llm import get_provider_chain
from app.services.nl2sql import answer_question
from ..state import AgentState, add_trace

logger = logging.getLogger(__name__)


async def sql_agent_node(state: AgentState) -> AgentState:
    providers = get_provider_chain()
    res = await answer_question(
        state["user_query"],
        state["tenant_id"],
        providers=providers,
        allowed_stores=state.get("allowed_stores") or None,
    )
    state["sql_result"] = {
        "ok": res.ok, "answer": res.answer, "sql": res.sql,
        "rows": res.rows, "reason": res.reason,
    }
    if res.ok:
        state.setdefault("evidence", []).append(
            {"kind": "sql", "sql": res.sql, "row_count": len(res.rows)})
    add_trace(state, "sql_agent",
              f"nl2sql ok={res.ok}" + (f" ({res.reason})" if not res.ok else f", {len(res.rows)} rows"))
    return state
