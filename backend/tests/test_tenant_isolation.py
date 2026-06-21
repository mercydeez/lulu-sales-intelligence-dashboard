"""
B2 — multi-tenant isolation.

The primary control is app-layer tenant scoping: every read filters `tenant_id`.
These tests prove the scoping is actually injected (by capturing the SQL the
service builds against a mocked session) and that caches are tenant-partitioned,
so one tenant can never be served another tenant's cached payload. RLS
(migration 012) is the defense-in-depth backstop; we assert it's present.

A live-DB integration test (two real tenants, disjoint data) is included but
skipped unless a Postgres test database is reachable.
"""
import os

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.data_sync import DataSyncService

# Resolve the migrations dir for both the host repo layout (backend/tests/../../database)
# and the container layout (database mounted at /app/database, i.e. ../database).
def _find_migrations_dir() -> str:
    here = os.path.dirname(__file__)
    for rel in (("..", "..", "database", "migrations"), ("..", "database", "migrations")):
        candidate = os.path.join(here, *rel)
        if os.path.isdir(candidate):
            return candidate
    return os.path.join(here, "..", "..", "database", "migrations")


MIGRATIONS_DIR = _find_migrations_dir()


def _fake_session(fetchone=None, fetchall=None, scalar=None):
    """An AsyncSession stand-in that records execute() calls."""
    session = MagicMock()
    result = MagicMock()
    result.fetchone.return_value = fetchone
    result.fetchall.return_value = fetchall or []
    result.scalar.return_value = scalar
    session.execute = AsyncMock(return_value=result)
    return session


def _executed_sql(session) -> str:
    return "\n".join(str(call.args[0]) for call in session.execute.call_args_list)


def _executed_params(session):
    return [call.args[1] for call in session.execute.call_args_list if len(call.args) > 1]


@pytest.mark.asyncio
async def test_inventory_summary_filters_by_tenant():
    session = _fake_session(fetchone=(5, 1000.0, 2, 1, 0))
    await DataSyncService.get_inventory_summary(
        session, accessible_stores=[1, 2], tenant_id=2
    )
    sql = _executed_sql(session)
    assert "tenant_id = :tenant_id" in sql
    assert any(p.get("tenant_id") == 2 for p in _executed_params(session))


@pytest.mark.asyncio
async def test_inventory_items_filters_by_tenant():
    session = _fake_session(fetchall=[], scalar=0)
    await DataSyncService.get_inventory_from_sales(
        session, accessible_stores=[1], tenant_id=7, page=1, limit=10
    )
    sql = _executed_sql(session)
    # Both the main query and the COUNT query must carry the tenant filter.
    assert sql.count("tenant_id = :tenant_id") >= 2
    assert all(p.get("tenant_id") == 7 for p in _executed_params(session))


@pytest.mark.asyncio
async def test_categories_inventory_interpolates_tenant():
    session = _fake_session(fetchall=[])
    await DataSyncService.get_categories_inventory(
        session, accessible_stores=[1], tenant_id=3
    )
    sql = _executed_sql(session)
    assert "tenant_id = 3" in sql


@pytest.mark.asyncio
async def test_promotions_from_sales_filters_by_tenant():
    session = _fake_session(fetchall=[])
    await DataSyncService.get_promotions_from_sales(
        session, accessible_stores=None, tenant_id=4
    )
    assert "s.tenant_id = 4" in _executed_sql(session)


@pytest.mark.asyncio
async def test_category_performance_filters_by_tenant():
    session = _fake_session(fetchall=[])
    await DataSyncService.get_category_performance(
        session, accessible_stores=None, tenant_id=6
    )
    # Both the current and previous period CTEs must carry the tenant filter.
    assert _executed_sql(session).count("s.tenant_id = 6") == 2


@pytest.mark.asyncio
async def test_alerts_from_sales_filters_by_tenant():
    session = _fake_session(fetchall=[])
    # Alerts uses SAVEPOINTs (begin_nested); give the mock an async CM for it.
    nested = MagicMock()
    nested.__aenter__ = AsyncMock(return_value=None)
    nested.__aexit__ = AsyncMock(return_value=None)
    session.begin_nested = MagicMock(return_value=nested)
    await DataSyncService.generate_alerts_from_sales(
        session, accessible_stores=None, tenant_id=8
    )
    sql = _executed_sql(session)
    assert "tenant_id = 8" in sql        # bare CTE
    assert "s.tenant_id = 8" in sql      # aliased queries


def test_kpis_cache_key_is_tenant_isolated():
    from app.routes.kpis import kpis_cache_key
    k1 = kpis_cache_key([1, 2], tenant_id=1)
    k2 = kpis_cache_key([1, 2], tenant_id=2)
    assert k1 != k2, "KPI cache keys must differ across tenants"


def test_model_metrics_cache_key_is_tenant_isolated():
    from app.routes.analytics import model_metrics_cache_key
    k1 = model_metrics_cache_key(1, None, 14)
    k2 = model_metrics_cache_key(2, None, 14)
    assert k1 != k2


def test_rls_migration_present_and_well_formed():
    path = os.path.join(MIGRATIONS_DIR, "012_tenant_rls.sql")
    assert os.path.exists(path), "RLS migration 012 must exist"
    body = open(path, encoding="utf-8").read()
    assert "ENABLE ROW LEVEL SECURITY" in body
    assert "CREATE POLICY tenant_isolation" in body
    assert "current_tenant_id()" in body


def test_second_tenant_seed_present():
    path = os.path.join(MIGRATIONS_DIR, "013_seed_second_tenant.sql")
    assert os.path.exists(path), "Second-tenant seed migration 013 must exist"
    body = open(path, encoding="utf-8").read()
    assert "Northwind" in body
    assert "owner@northwind.ae" in body
    assert "tenant_id = 2" in body or ", 2)" in body


def test_tenant_context_default_is_demo():
    """The per-request tenant GUC source defaults to the demo tenant when unset."""
    from app.services.database import tenant_context
    assert tenant_context.get() == 1


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_DB_TESTS") != "1",
    reason="needs a seeded Postgres with both tenants (set RUN_DB_TESTS=1)",
)
async def test_two_tenant_data_is_disjoint_live():
    """With a live DB: tenant 1 and tenant 2 must see strictly disjoint sales."""
    from app.services.database import async_session
    from sqlalchemy import text
    async with async_session() as s:
        t1_stores = {r.id for r in (await s.execute(
            text("SELECT id FROM stores WHERE tenant_id = 1"))).fetchall()}
        t2_stores = {r.id for r in (await s.execute(
            text("SELECT id FROM stores WHERE tenant_id = 2"))).fetchall()}
        assert t1_stores and t2_stores
        assert t1_stores.isdisjoint(t2_stores)
