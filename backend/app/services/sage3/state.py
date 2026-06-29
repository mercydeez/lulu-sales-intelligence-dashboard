"""
Sage v3 — graph state.

`AgentState` is the single typed dict threaded through every LangGraph node. It
carries (1) the request + RBAC scope that must reach every SQL/RAG call
unchanged, (2) the per-node working fields (route/intent/results/draft), and
(3) the user-facing output (final answer + confidence + evidence + trace).

HARD INVARIANT: `tenant_id`, `role`, and `allowed_stores` are set ONCE from the
authenticated request in the initial state and are READ-ONLY thereafter. No node
may widen data scope — see docs/SAGE_V3_AGENT_INTEGRATION.md §2.3.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class TraceEntry(TypedDict, total=False):
    """One node hop, surfaced to the user as the agent "thinking" trace."""
    node: str
    summary: str
    confidence: Optional[float]
    ms: Optional[int]


class AgentState(TypedDict, total=False):
    # --- request ---
    session_id: str
    user_query: str
    conversation_history: List[Dict[str, str]]  # [{role, content}, ...]

    # --- RBAC scope (READ-ONLY after init; every data call gets these) ---
    tenant_id: int
    role: str
    allowed_stores: List[int]   # [] / absent => no store restriction (super_admin)

    # --- routing / intent ---
    route: str                  # 'sql' | 'rag' | 'hybrid'
    intent: Dict[str, Any]      # {intents: [...], mentioned_store, clarity_score, ...}

    # --- clarification / readback ---
    clarity_score: float
    ambiguities: List[str]
    clarification_round: int
    needs_clarification: bool
    clarification_question: Optional[str]
    readback_confirmed: bool   # set by runtime when the user confirms a prior readback
    needs_readback: bool
    readback_text: Optional[str]

    # --- execution results (each node writes its own slot) ---
    sql_result: Optional[Dict[str, Any]]   # {ok, answer, sql, rows, reason}
    rag_result: Optional[Dict[str, Any]]   # {ok, answer, citations, chunks}
    hybrid_result: Optional[Dict[str, Any]]
    draft_answer: str
    grounded: bool             # True => answer traced to rows/chunks; False => rule-based

    # --- validation stack (later phases) ---
    critic_verdict: Optional[Dict[str, Any]]      # {verdict, confidence, issues}
    cross_check: Optional[Dict[str, Any]]
    arbiter_verdict: Optional[Dict[str, Any]]
    completeness: Optional[Dict[str, Any]]
    reground_count: int
    want_reground: bool

    # --- output ---
    final_answer: str
    final_confidence: float
    evidence: List[Dict[str, Any]]   # [{kind: 'sql'|'doc'|'source', ...}]
    trace: List[TraceEntry]


def initial_state(
    *,
    session_id: str,
    user_query: str,
    tenant_id: int,
    role: str,
    allowed_stores: Optional[List[int]] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> AgentState:
    """Build the graph's entry state from an authenticated, already-scoped request.

    `allowed_stores` MUST be the caller's accessible-store list (empty => all
    stores in the tenant, i.e. super_admin). Mirrors routes/ai.py exactly so the
    v3 path can never see more than the v2 path.
    """
    return AgentState(
        session_id=session_id,
        user_query=user_query,
        conversation_history=conversation_history or [],
        tenant_id=int(tenant_id),
        role=role or "store_manager",
        allowed_stores=list(allowed_stores or []),
        intent={},
        clarification_round=0,
        reground_count=0,
        draft_answer="",
        final_answer="",
        final_confidence=0.0,
        evidence=[],
        trace=[],
    )


def add_trace(state: AgentState, node: str, summary: str,
              confidence: Optional[float] = None, ms: Optional[int] = None) -> None:
    """Append a node hop to the trace (mutates state in place)."""
    state.setdefault("trace", []).append(
        TraceEntry(node=node, summary=summary, confidence=confidence, ms=ms)
    )
