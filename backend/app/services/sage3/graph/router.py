"""
Router node — decide which executor handles the query: 'sql' | 'rag' | 'hybrid'.

Phase 0: deterministic, no-LLM keyword routing (reuses sage2.is_multipart and the
existing keyword detectors). Phase 1+ threads RBAC + source availability and may
consult the LLM. This node NEVER touches data — it only picks a path.
"""
from __future__ import annotations

import logging

from app.services.sage2 import is_multipart
from ..state import AgentState, add_trace

logger = logging.getLogger(__name__)

# Words that signal a document/policy question rather than a metric question.
_DOC_HINTS = (
    "policy", "document", "strategy", "according to", "per the", "memo",
    "guideline", "handbook", "procedure", "report says", "what does the",
)


def decide_route(query: str) -> str:
    q = (query or "").lower()
    if is_multipart(query):
        return "hybrid"
    if any(h in q for h in _DOC_HINTS):
        return "rag"
    return "sql"


async def router_node(state: AgentState) -> AgentState:
    route = decide_route(state.get("user_query", ""))
    state["route"] = route
    add_trace(state, "router", f"route → {route}")
    return state
