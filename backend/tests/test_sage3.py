"""
Sage v3 (LangGraph multi-agent) — Phase 0 scaffold tests.

Verifies the graph compiles and runs the happy path (router → intent →
executor → synthesiser → finaliser), routes correctly, and — critically — never
widens RBAC scope: tenant_id/role/allowed_stores come out exactly as they went
in. Executors are Phase-0 stubs (DB-free), so these tests need no live Postgres.

langgraph is an optional dependency that only activates under USE_SAGE_V3, so the
whole module skips cleanly where it isn't installed (e.g. a minimal local venv).
"""
import pytest

pytest.importorskip("langgraph", reason="langgraph not installed (USE_SAGE_V3 path)")

from app.services.sage3.graph.router import decide_route  # noqa: E402
from app.services.sage3.state import initial_state  # noqa: E402
from app.services.sage3 import run_sage3, get_graph  # noqa: E402


# --- pure routing ----------------------------------------------------------
def test_route_simple_metric_is_sql():
    assert decide_route("What were total sales today?") == "sql"


def test_route_document_question_is_rag():
    # A pure document question (no second metric intent) routes to RAG. A doc
    # question that ALSO asks a metric is multi-part and routes to hybrid — that
    # refinement is Phase 1; Phase 0 keeps this deterministic split.
    assert decide_route("What does the employee handbook say about opening hours?") == "rag"


def test_route_multipart_is_hybrid():
    q = "Show me 2030 target, total sales revenue, and which distributors serve North"
    assert decide_route(q) == "hybrid"


# --- state init ------------------------------------------------------------
def test_initial_state_carries_rbac():
    st = initial_state(session_id="s", user_query="q", tenant_id=7,
                       role="store_manager", allowed_stores=[2, 5])
    assert st["tenant_id"] == 7
    assert st["role"] == "store_manager"
    assert st["allowed_stores"] == [2, 5]


def test_initial_state_empty_stores_means_all():
    st = initial_state(session_id="s", user_query="q", tenant_id=1,
                       role="super_admin", allowed_stores=None)
    assert st["allowed_stores"] == []  # [] => no store restriction (super_admin)


# --- graph compile + run ---------------------------------------------------
def test_graph_compiles():
    assert get_graph() is get_graph()  # cached singleton


@pytest.mark.asyncio
async def test_graph_runs_and_preserves_scope():
    st = await run_sage3(session_id="u1:s", user_query="What were total sales today?",
                         tenant_id=3, role="regional_manager", allowed_stores=[4, 9])
    # RBAC scope unchanged end-to-end — no node widened it.
    assert st["tenant_id"] == 3
    assert st["role"] == "regional_manager"
    assert st["allowed_stores"] == [4, 9]
    # Happy path fired in order and produced a terminal answer + trace.
    assert st["route"] == "sql"
    nodes = [t["node"] for t in st["trace"]]
    # Simple single read: router→intent→sql→synthesiser→critic→finaliser (the
    # conditional validation stack is skipped for confident/simple reads).
    assert nodes == ["router", "intent", "sql_agent", "synthesiser", "critic", "finaliser"]
    assert "final_answer" in st


@pytest.mark.asyncio
async def test_hybrid_fresh_query_reads_back():
    # A fresh multi-part query is read back for confirmation before executing.
    q = "Show me 2030 target, total sales revenue, and which distributors serve North"
    st = await run_sage3(session_id="u1:s2", user_query=q, tenant_id=1,
                         role="super_admin", allowed_stores=[])
    assert st.get("needs_readback") is True
    nodes = [t["node"] for t in st["trace"]]
    assert nodes == ["router", "intent", "readback", "finaliser"]


@pytest.mark.asyncio
async def test_hybrid_confirmed_runs_validation_stack():
    # With readback confirmed, the full multi-part + validation pipeline runs.
    q = "Show me 2030 target, total sales revenue, and which distributors serve North"
    st = await run_sage3(session_id="u1:s3", user_query=q, tenant_id=1,
                         role="super_admin", allowed_stores=[], readback_confirmed=True)
    nodes = [t["node"] for t in st["trace"]]
    # The multi-part + validation pipeline runs (an optional single reground may
    # repeat the middle when sub-queries return no data, e.g. no live warehouse).
    for n in ["planner", "hybrid_executor", "synthesiser", "critic",
              "cross_validator", "arbiter", "completeness"]:
        assert n in nodes, f"missing {n} in {nodes}"
    assert nodes[0] == "router" and nodes[-1] == "finaliser"
