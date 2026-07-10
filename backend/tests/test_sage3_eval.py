"""
Sage v3 golden-question eval harness (Phase 7).

20 retail goldens spanning SQL reads, document RAG, multi-part hybrid, and
ambiguous→clarify. These assert the graph's ROUTING and DIALOGUE behavior, which
are deterministic and DB-independent (executors fall back gracefully without a
live warehouse). Numeric correctness is covered by the live store-scoping checks
in test_sage3_rbac.py and the manual end-to-end runs.
"""
import pytest

pytest.importorskip("langgraph", reason="langgraph not installed (USE_SAGE_V3 path)")

from app.services.sage3.graph.router import decide_route          # noqa: E402
from app.services.sage3.graph.intent import _heuristic_clarity     # noqa: E402
from app.services.sage3.runtime import answer_sage3                # noqa: E402

# (query, expected_route) — routing is pre-clarity, pre-execution.
ROUTE_GOLDENS = [
    ("What were total sales today?", "sql"),
    ("Top 5 stores by revenue", "sql"),
    ("Units sold per category", "sql"),
    ("Which items had the most returns this month?", "sql"),
    ("Revenue last week", "sql"),
    ("How many transactions today?", "sql"),
    ("Best selling products", "sql"),
    ("Show recent transactions", "sql"),
    ("What does the employee handbook say about opening hours?", "rag"),
    ("Summarize the procurement policy document", "rag"),
    ("What does the strategy document say?", "rag"),
    ("top stores by revenue and total returns", "hybrid"),
    ("2030 target, total sales revenue, and which distributors serve North", "hybrid"),
    ("CRM pipeline revenue and average online selling price", "hybrid"),
]

# Vague asks that must trip the clarification gate (clarity < 0.5).
AMBIGUOUS_GOLDENS = ["sales", "show me", "returns", "stores", "data"]


@pytest.mark.parametrize("query,route", ROUTE_GOLDENS)
def test_routing_golden(query, route):
    assert decide_route(query) == route


@pytest.mark.parametrize("query", AMBIGUOUS_GOLDENS)
def test_ambiguous_low_clarity(query):
    clarity, ambiguities = _heuristic_clarity(query)
    assert clarity < 0.5 and ambiguities


def test_specific_query_high_clarity():
    clarity, _ = _heuristic_clarity("What was revenue for Karama last week?")
    assert clarity >= 0.8


# --- behavioral goldens through the full graph -----------------------------
@pytest.mark.asyncio
async def test_vague_triggers_clarification():
    st = await answer_sage3("g:1", "sales", tenant_id=1, role="super_admin", allowed_stores=[])
    assert st.get("needs_clarification") is True
    # No SQL ran on a clarification turn (nothing fabricated).
    assert st.get("sql_result") in (None, {}) or not (st.get("sql_result") or {}).get("rows")


@pytest.mark.asyncio
async def test_multipart_triggers_readback_then_confirms(fake_redis):
    # Two turns that must share `pending` (the parked readback). That state now
    # lives in Redis, not a process dict, so this test needs a Redis stand-in — the
    # same requirement multi-worker serving imposes in production.
    q = "top stores by revenue and total returns"
    st1 = await answer_sage3("g:2", q, tenant_id=1, role="super_admin", allowed_stores=[])
    assert st1.get("needs_readback") is True
    st2 = await answer_sage3("g:2", "yes", tenant_id=1, role="super_admin", allowed_stores=[])
    assert st2.get("needs_readback") in (False, None)
    nodes = [t["node"] for t in st2["trace"]]
    assert "hybrid_executor" in nodes and nodes[-1] == "finaliser"


@pytest.mark.asyncio
async def test_simple_read_skips_validation_stack():
    st = await answer_sage3("g:3", "What were total sales today?", tenant_id=1,
                            role="super_admin", allowed_stores=[])
    nodes = [t["node"] for t in st["trace"]]
    # Conditional validation: a simple single read must NOT run cross-validation.
    assert "cross_validator" not in nodes
    assert nodes[-1] == "finaliser"
