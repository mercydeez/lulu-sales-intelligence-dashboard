"""
RAG agent node — thin wrapper over the existing document retriever.

Calls rag.answer_from_docs (Postgres full-text retrieval, tenant-scoped — NO new
vector store) and records {ok, answer, citations, chunks}. Grounded: with an LLM
it narrates strictly from retrieved chunks; without one it returns the top chunk
verbatim with a citation. Never raises.
"""
from __future__ import annotations

import logging

from app.services.llm import get_provider_chain
from app.services.rag import answer_from_docs
from ..state import AgentState, add_trace

logger = logging.getLogger(__name__)


async def rag_agent_node(state: AgentState) -> AgentState:
    providers = get_provider_chain()
    res = await answer_from_docs(state["user_query"], state["tenant_id"], providers=providers)
    state["rag_result"] = {
        "ok": res.ok, "answer": res.answer,
        "citations": res.citations, "chunks": res.chunks,
    }
    if res.ok:
        for c in res.citations:
            state.setdefault("evidence", []).append({"kind": "doc", "citation": c})
    add_trace(state, "rag_agent",
              f"rag ok={res.ok}, {len(res.citations)} citation(s)")
    return state
