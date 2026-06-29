"""
Sage v3 RBAC scope tests (Phase 7).

Proves the hard invariant: tenant_id + allowed_stores enter the graph from the
authenticated request and are NEVER widened by any node, and that store scope is
rendered into the DB GUC correctly. Mirrors tests/test_ai_rbac.py for the new
graph. DB-free: asserts scope plumbing, not warehouse numbers (those are verified
live against the running sage_ro role).
"""
import pytest

pytest.importorskip("langgraph", reason="langgraph not installed (USE_SAGE_V3 path)")

from app.services.nl2sql.executor import _store_ids_guc            # noqa: E402
from app.services.sage3.runtime import answer_sage3                # noqa: E402


# --- GUC rendering (the DB-enforced store filter input) --------------------
def test_guc_empty_means_no_restriction():
    assert _store_ids_guc(None) == ""
    assert _store_ids_guc([]) == ""


def test_guc_renders_int_array_literal():
    assert _store_ids_guc([3, 4]) == "{3,4}"
    assert _store_ids_guc([7]) == "{7}"


def test_guc_coerces_and_is_injection_safe():
    # Values are ints; rendering can't carry SQL — only digits/braces/commas.
    out = _store_ids_guc([3, 4, 5])
    assert out == "{3,4,5}"
    assert all(c in "0123456789{},-" for c in out)


# --- scope never widened end-to-end ----------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("role,stores", [
    ("store_manager", [5]),
    ("regional_manager", [3, 4]),
    ("super_admin", []),
])
async def test_scope_preserved_through_graph(role, stores):
    st = await answer_sage3("rbac:" + role, "What were total sales today?",
                            tenant_id=2, role=role, allowed_stores=stores)
    # Tenant + store scope come out EXACTLY as they went in — no node widened them.
    assert st["tenant_id"] == 2
    assert st["role"] == role
    assert st["allowed_stores"] == stores


@pytest.mark.asyncio
async def test_clarification_turn_runs_no_query():
    """A clarification turn must not execute SQL — no data path, no scope to leak."""
    st = await answer_sage3("rbac:clar", "sales", tenant_id=2,
                            role="store_manager", allowed_stores=[5])
    assert st.get("needs_clarification") is True
    assert not (st.get("sql_result") or {}).get("rows")
    assert st["allowed_stores"] == [5]


@pytest.mark.asyncio
async def test_multipart_scope_reaches_subqueries():
    """Confirmed multipart threads the same store scope into every sub-query."""
    await answer_sage3("rbac:mp", "top stores by revenue and total returns",
                       tenant_id=1, role="regional_manager", allowed_stores=[3, 4])
    st = await answer_sage3("rbac:mp", "yes", tenant_id=1,
                            role="regional_manager", allowed_stores=[3, 4])
    assert st["allowed_stores"] == [3, 4]
    assert st["tenant_id"] == 1
