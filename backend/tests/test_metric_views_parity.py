"""
E6-1 — canonical metric views parity + tenant safety.

Migration 050 moved the revenue / week-over-week math out of Python (routes/kpis.py)
and JavaScript (worker/src/rules.js) into shared SQL views (`metric_*`). These tests
lock that refactor as VALUE-PRESERVING and TENANT-SAFE:

  * metric_sales_fact.revenue_aed / units must still equal an independently-written
    `units * unit_price_aed` (items-only join surface — the same one kpis.py used).
  * The WoW ratios the views expose must be internally consistent.
  * metric_returns_wow must equal an independent returned-units sum straight off
    sales_fact_view (the surface the original returnSpike rule used — no item join).
  * No view may join an item of a different tenant onto a sale.

A future edit that drifts a view away from the convention fails here.

Live-DB tests, gated on RUN_DB_TESTS=1 (same convention as test_tenant_isolation.py's
two-tenant check) so the DB-free unit suite is unaffected. CI runs them against the
freshly seeded stack.
"""
import os

import pytest
from sqlalchemy import text

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("RUN_DB_TESTS") != "1",
        reason="needs a seeded Postgres (set RUN_DB_TESTS=1)",
    ),
]

# Independent restatement of the units/AED convention — NOT read from the view, so it
# is a real cross-check of metric_sales_fact's revenue_aed / units columns. Items-only
# join on (id, tenant_id) mirrors metric_sales_fact exactly.
_LEGACY_FACT = """
    SELECT
        COALESCE(SUM(s.sales * i.unit_price_aed), 0)::numeric AS revenue,
        COALESCE(SUM(s.sales), 0)::bigint                     AS units
    FROM sales_fact_view s
    JOIN items i ON i.id = s.item_id AND i.tenant_id = s.tenant_id
    WHERE s.tenant_id = :t
"""

_VIEW_FACT = """
    SELECT
        COALESCE(SUM(revenue_aed), 0)::numeric AS revenue,
        COALESCE(SUM(units), 0)::bigint         AS units
    FROM metric_sales_fact
    WHERE tenant_id = :t
"""


async def _tenant_ids(s):
    rows = (await s.execute(text("SELECT DISTINCT tenant_id FROM stores ORDER BY tenant_id"))).fetchall()
    return [r.tenant_id for r in rows]


async def test_metric_sales_fact_matches_units_times_price():
    """metric_sales_fact.revenue_aed / units == an independent units*price restatement,
    for every seeded tenant."""
    from app.services.database import async_session
    async with async_session() as s:
        tenants = await _tenant_ids(s)
        assert tenants, "expected at least one seeded tenant"
        for t in tenants:
            legacy = (await s.execute(text(_LEGACY_FACT), {"t": t})).fetchone()
            view = (await s.execute(text(_VIEW_FACT), {"t": t})).fetchone()
            assert abs(float(view.revenue) - float(legacy.revenue)) < 0.01, f"revenue drift, tenant {t}"
            assert int(view.units) == int(legacy.units), f"units drift, tenant {t}"


async def test_metric_sales_fact_never_crosses_tenants():
    """The item join is tenant-matched: no row may carry an item from another tenant.
    (A missing tenant match would let a per-tenant id collision bleed a wrong price.)"""
    from app.services.database import async_session
    async with async_session() as s:
        bad = (await s.execute(text("""
            SELECT COUNT(*) AS n
            FROM metric_sales_fact f
            JOIN items i ON i.id = f.item_id
            WHERE i.tenant_id <> f.tenant_id
        """))).fetchone()
        assert int(bad.n) == 0


async def test_store_wow_change_is_internally_consistent():
    """metric_store_wow.change must equal (rev_recent - rev_prior) / rev_prior wherever
    rev_prior > 0, and gap_pp must equal chain_avg_change - change."""
    from app.services.database import async_session
    async with async_session() as s:
        rows = (await s.execute(text(
            "SELECT rev_recent, rev_prior, change, chain_avg_change, gap_pp "
            "FROM metric_store_wow WHERE rev_prior > 0"
        ))).fetchall()
        for r in rows:
            expected = (float(r.rev_recent) - float(r.rev_prior)) / float(r.rev_prior)
            assert abs(float(r.change) - expected) < 1e-9
            assert abs(float(r.gap_pp) - (float(r.chain_avg_change) - float(r.change))) < 1e-9


async def test_returns_wow_matches_independent_return_sum():
    """metric_returns_wow recent/prior returned units == an independent sum of abs(sales)
    over rows with sales < 0 in each window, straight off sales_fact_view."""
    from app.services.database import async_session
    async with async_session() as s:
        tenants = await _tenant_ids(s)
        for t in tenants:
            indep = (await s.execute(text("""
                SELECT
                    COALESCE(SUM(ABS(sales)) FILTER (
                        WHERE sales < 0 AND date >= CURRENT_DATE - INTERVAL '7 days'), 0)::bigint AS recent,
                    COALESCE(SUM(ABS(sales)) FILTER (
                        WHERE sales < 0 AND date >= CURRENT_DATE - INTERVAL '14 days'
                                       AND date <  CURRENT_DATE - INTERVAL '7 days'), 0)::bigint AS prior
                FROM sales_fact_view WHERE tenant_id = :t
            """), {"t": t})).fetchone()
            view = (await s.execute(text(
                "SELECT returns_recent_units, returns_prior_units, change "
                "FROM metric_returns_wow WHERE tenant_id = :t"
            ), {"t": t})).fetchone()
            # No sales at all for a tenant => it may be absent from the grouped view.
            if view is None:
                assert int(indep.recent) == 0 and int(indep.prior) == 0
                continue
            assert int(view.returns_recent_units) == int(indep.recent)
            assert int(view.returns_prior_units) == int(indep.prior)
            # `change` must be a TRUE fraction, not integer-truncated. This is the
            # guard that catches the bigint-division regression: with prior returns,
            # change == (recent - prior) / prior computed as a real ratio.
            if int(view.returns_prior_units) > 0:
                expected = (int(indep.recent) - int(indep.prior)) / int(indep.prior)
                assert abs(float(view.change) - expected) < 1e-9, (
                    f"metric_returns_wow.change is not a true fraction (tenant {t}): "
                    f"{float(view.change)} != {expected} — check for integer division"
                )
