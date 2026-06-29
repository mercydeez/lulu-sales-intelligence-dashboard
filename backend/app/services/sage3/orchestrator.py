"""
Sage v3 orchestrator — builds and compiles the full LangGraph state machine.

    START → router → classify_intent
         ├─(low clarity)──────────────→ clarification ─→ finaliser → END
         ├─(multi-part, unconfirmed)──→ readback ──────→ finaliser → END
         └─(proceed)→ {sql_agent | rag_agent | planner→hybrid_executor}
                    → synthesiser → critic
                        ├─(simple, high-confidence)──────────────→ finaliser → END
                        └─(borderline / multi-part)→ cross_validator → arbiter
                            → completeness
                                ├─(incomplete, 1st time)─→ re-execute (reground)
                                └─(else)─────────────────→ finaliser → END

The validation stack is CONDITIONAL for latency: simple, high-confidence single
reads skip straight to the finaliser; only borderline (critic 0.4–0.7) or
multi-part answers pay for cross-validation/arbitration/completeness, with at most
ONE reground. LangGraph is imported lazily so the app boots without the package
when settings.use_sage_v3 is false.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

from .state import AgentState, initial_state
from .graph.router import router_node
from .graph.intent import intent_node
from .graph.clarification import clarification_node
from .graph.readback import readback_node
from .graph.sql_agent import sql_agent_node
from .graph.rag_agent import rag_agent_node
from .graph.planner import planner_node
from .graph.hybrid_executor import hybrid_executor_node
from .graph.synthesiser import synthesiser_node
from .graph.critic import critic_node
from .graph.cross_validator import cross_validator_node
from .graph.arbiter import arbiter_node
from .graph.completeness import completeness_node
from .graph.finaliser import finaliser_node

logger = logging.getLogger(__name__)

_CLARITY_THRESHOLD = 0.5
_MAX_CLARIFY_ROUNDS = 2
_CRITIC_LOW = 0.4
_CRITIC_HIGH = 0.7


def _executor_for(route: str) -> str:
    return {"rag": "rag_agent", "hybrid": "planner"}.get(route, "sql_agent")


def route_after_intent(state: AgentState) -> str:
    """Clarify when ambiguous; read back complex multi-part plans; else execute."""
    clarity = float(state.get("clarity_score", 1.0))
    rounds = int(state.get("clarification_round", 0))
    if clarity < _CLARITY_THRESHOLD and rounds < _MAX_CLARIFY_ROUNDS:
        return "clarification"
    if state.get("route") == "hybrid" and not state.get("readback_confirmed"):
        return "readback"
    return _executor_for(state.get("route", "sql"))


def route_after_critic(state: AgentState) -> str:
    """Conditional validation: skip it for simple high-confidence reads."""
    verdict = state.get("critic_verdict") or {}
    conf = float(verdict.get("confidence", 0.6))
    if state.get("route") == "hybrid":
        return "validate"              # multi-part always gets cross-checked
    if not state.get("grounded"):
        return "finalise"              # rule-based fallback: nothing to cross-check
    if conf > _CRITIC_HIGH:
        return "finalise"              # simple, confident single read
    return "validate"                  # borderline / low → validate (may reground)


def route_after_completeness(state: AgentState) -> str:
    """One reground retry when the answer is incomplete, else finalise.

    PURE read of the decision the completeness NODE already made — a routing
    function's state mutations are discarded by LangGraph, so the reground counter
    must be advanced in the node (else the loop never caps → recursion error)."""
    if state.get("want_reground"):
        return _executor_for(state.get("route", "sql"))
    return "finalise"


def _build_graph():
    from langgraph.graph import StateGraph, START, END

    g = StateGraph(AgentState)
    g.add_node("router", router_node)
    g.add_node("classify_intent", intent_node)   # 'intent' collides with a state key
    g.add_node("clarification", clarification_node)
    g.add_node("readback", readback_node)
    g.add_node("sql_agent", sql_agent_node)
    g.add_node("rag_agent", rag_agent_node)
    g.add_node("planner", planner_node)
    g.add_node("hybrid_executor", hybrid_executor_node)
    g.add_node("synthesiser", synthesiser_node)
    g.add_node("critic", critic_node)
    g.add_node("cross_validator", cross_validator_node)
    g.add_node("arbiter", arbiter_node)
    g.add_node("completeness_check", completeness_node)  # 'completeness' is a state key
    g.add_node("finaliser", finaliser_node)

    g.add_edge(START, "router")
    g.add_edge("router", "classify_intent")
    g.add_conditional_edges("classify_intent", route_after_intent, {
        "clarification": "clarification",
        "readback": "readback",
        "sql_agent": "sql_agent",
        "rag_agent": "rag_agent",
        "planner": "planner",
    })
    # Dialogue branches short-circuit to the finaliser (no SQL runs).
    g.add_edge("clarification", "finaliser")
    g.add_edge("readback", "finaliser")
    # Execution branches.
    g.add_edge("sql_agent", "synthesiser")
    g.add_edge("rag_agent", "synthesiser")
    g.add_edge("planner", "hybrid_executor")
    g.add_edge("hybrid_executor", "synthesiser")
    g.add_edge("synthesiser", "critic")
    g.add_conditional_edges("critic", route_after_critic, {
        "finalise": "finaliser",
        "validate": "cross_validator",
    })
    g.add_edge("cross_validator", "arbiter")
    g.add_edge("arbiter", "completeness_check")
    g.add_conditional_edges("completeness_check", route_after_completeness, {
        "sql_agent": "sql_agent",
        "rag_agent": "rag_agent",
        "planner": "planner",
        "finalise": "finaliser",
    })
    g.add_edge("finaliser", END)
    return g


def _make_checkpointer():
    """Stateless compile for now; the runtime carries cross-turn state. A Redis,
    fail-open saver lands with deeper continuity work (must match langgraph 0.1.x's
    BaseCheckpointSaver.aput signature)."""
    return None


@lru_cache(maxsize=1)
def get_graph():
    """Compiled Sage v3 graph (built once)."""
    checkpointer = _make_checkpointer()
    compiled = (_build_graph().compile(checkpointer=checkpointer)
                if checkpointer is not None else _build_graph().compile())
    logger.info("Sage v3 graph compiled (full pipeline, checkpointer=%s).",
                type(checkpointer).__name__ if checkpointer else "none")
    return compiled


async def run_sage3(
    *,
    session_id: str,
    user_query: str,
    tenant_id: int,
    role: str,
    allowed_stores: Optional[list] = None,
    conversation_history: Optional[list] = None,
    clarification_round: int = 0,
    readback_confirmed: bool = False,
) -> AgentState:
    """Run the graph once and return the terminal state. RBAC scope is fixed in the
    initial state and never widened. `clarification_round`/`readback_confirmed` are
    threaded by the runtime to drive the cross-turn dialogue loops."""
    graph = get_graph()
    state = initial_state(
        session_id=session_id,
        user_query=user_query,
        tenant_id=tenant_id,
        role=role,
        allowed_stores=allowed_stores,
        conversation_history=conversation_history,
    )
    state["clarification_round"] = clarification_round
    state["readback_confirmed"] = readback_confirmed
    # recursion_limit margin: full pipeline (~10) + one reground pass (~8) < 50.
    config = {"configurable": {"thread_id": session_id}, "recursion_limit": 50}
    result: AgentState = await graph.ainvoke(state, config=config)
    return result
