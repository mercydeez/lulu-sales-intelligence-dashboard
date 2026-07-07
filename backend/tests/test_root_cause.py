"""
E7-4 — deterministic root-cause decomposition.

Two layers:
  * PURE unit tests (no DB) for the period/share/validation math — run in the
    normal backend CI job, so the deterministic logic is always guarded.
  * LIVE-DB tests (RUN_DB_TESTS=1) that exercise the SQL decomposition against the
    seeded stack and assert value-correctness + tenant isolation. Wired into the
    smoke job. Same gating convention as test_metric_views_parity.py.
"""
import os
from datetime import date, timedelta

import pytest

from app.services import root_cause as rc


# ===========================================================================
# PURE LOGIC (no database) — always runs in CI
# ===========================================================================

def test_previous_period_is_immediately_preceding_equal_window():
    cs, ce = rc.resolve_comparison_period(date(2026, 1, 8), date(2026, 1, 14), "previous_period", None, None)
    assert cs == date(2026, 1, 1) and ce == date(2026, 1, 7)


def test_previous_week_shifts_both_bounds_back_7_days():
    cs, ce = rc.resolve_comparison_period(date(2026, 1, 8), date(2026, 1, 14), "previous_week", None, None)
    assert cs == date(2026, 1, 1) and ce == date(2026, 1, 7)


def test_previous_year_is_leap_safe():
    # Feb 29 2024 -> Feb 28 2023 (2023 is not a leap year).
    cs, ce = rc.resolve_comparison_period(date(2024, 2, 29), date(2024, 2, 29), "previous_year", None, None)
    assert cs == date(2023, 2, 28) and ce == date(2023, 2, 28)


def test_explicit_compare_dates_override_comparison():
    cs, ce = rc.resolve_comparison_period(
        date(2026, 1, 8), date(2026, 1, 14), "previous_period",
        date(2025, 6, 1), date(2025, 6, 7),
    )
    assert cs == date(2025, 6, 1) and ce == date(2025, 6, 7)


def test_explicit_compare_dates_require_both():
    with pytest.raises(rc.ValidationError):
        rc.resolve_comparison_period(date(2026, 1, 8), date(2026, 1, 14), "previous_period", date(2025, 6, 1), None)


def test_explicit_compare_start_after_end_rejected():
    with pytest.raises(rc.ValidationError):
        rc.resolve_comparison_period(
            date(2026, 1, 8), date(2026, 1, 14), "previous_period", date(2025, 6, 8), date(2025, 6, 1)
        )


def test_explicit_compare_range_over_max_days_rejected():
    with pytest.raises(rc.ValidationError):
        rc.resolve_comparison_period(
            date(2026, 1, 8), date(2026, 1, 14), "previous_period",
            date(2024, 1, 1), date(2025, 6, 1),  # > 366 days
        )


def test_invalid_metric_rejected():
    with pytest.raises(rc.ValidationError):
        rc.validate_params("gross_margin", date(2026, 1, 1), date(2026, 1, 7), None, None, None)


def test_invalid_dimension_rejected():
    with pytest.raises(rc.ValidationError):
        rc.validate_params("revenue_aed", date(2026, 1, 1), date(2026, 1, 7), None, "store,region", None)


def test_defaults_and_normalisation():
    norm = rc.validate_params(None, date(2026, 1, 1), date(2026, 1, 7), None, None, None)
    assert norm["metric"] == "revenue_aed"
    assert norm["comparison"] == "previous_period"
    assert norm["dimensions"] == ["store", "category", "item", "day"]
    assert norm["limit"] == 10


def test_limit_clamped_to_max():
    norm = rc.validate_params("units_sold", date(2026, 1, 1), date(2026, 1, 7), None, "day", 999)
    assert norm["limit"] == rc.MAX_LIMIT
    assert norm["dimensions"] == ["day"]


def test_limit_below_one_rejected():
    with pytest.raises(rc.ValidationError):
        rc.validate_params("revenue_aed", date(2026, 1, 1), date(2026, 1, 7), None, None, 0)


def test_start_after_end_rejected():
    with pytest.raises(rc.ValidationError):
        rc.validate_params("revenue_aed", date(2026, 1, 8), date(2026, 1, 1), None, None, None)


def test_range_over_max_days_rejected():
    with pytest.raises(rc.ValidationError):
        rc.validate_params("revenue_aed", date(2025, 1, 1), date(2026, 6, 1), None, None, None)


def test_safe_pct_handles_zero_base():
    assert rc.safe_pct(10.0, 0.0) is None
    assert rc.safe_pct(-5.0, 10.0) == -50.0


def test_share_of_change_handles_zero_total():
    assert rc.share_of_change(5.0, 0.0) is None
    assert rc.share_of_change(-9000.0, -15000.0) == 60.0


# ===========================================================================
# LIVE DB — needs a seeded Postgres (RUN_DB_TESTS=1)
# ===========================================================================

db = pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="needs a seeded Postgres (set RUN_DB_TESTS=1)")


def _recent_window():
    """A 7-day window that has seeded history (history is date-shifted so the
    latest day is 'yesterday')."""
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=6)
    return start, end


@db
@pytest.mark.asyncio
async def test_totals_and_delta_are_self_consistent():
    from sqlalchemy import text
    from app.services.database import async_session
    start, end = _recent_window()
    async with async_session() as s:
        res = await rc.decompose(
            s, 1, [], metric="revenue_aed", start_date=start, end_date=end,
            comparison="previous_period", dimensions=["store", "category", "item", "day"], limit=50,
        )
        # delta == current - comparison
        assert abs(res.delta.absolute - (res.current_period.value - res.comparison_period.value)) < 0.01
        # current_period.value equals an independent SUM(revenue_aed) over the window
        indep = (await s.execute(text(
            "SELECT COALESCE(SUM(revenue_aed),0)::numeric AS v FROM metric_sales_fact "
            "WHERE tenant_id = 1 AND date BETWEEN :a AND :b"
        ), {"a": start, "b": end})).fetchone()
        assert abs(res.current_period.value - float(indep.v)) < 0.01


@db
@pytest.mark.asyncio
async def test_full_partition_contributor_deltas_sum_to_total():
    """With limit high enough to include every group, the store/category/day
    contributor deltas must sum to the total delta (they partition all rows)."""
    from app.services.database import async_session
    start, end = _recent_window()
    async with async_session() as s:
        res = await rc.decompose(
            s, 1, [], metric="units_sold", start_date=start, end_date=end,
            comparison="previous_period", dimensions=["store", "category", "day"], limit=50,
        )
        for dim in ("store", "category", "day"):
            summed = sum(c.delta for c in res.contributors[dim])
            assert abs(summed - res.delta.absolute) < 0.5, f"{dim} deltas do not sum to total"


@db
@pytest.mark.asyncio
async def test_contributors_sorted_by_abs_delta_desc():
    from app.services.database import async_session
    start, end = _recent_window()
    async with async_session() as s:
        res = await rc.decompose(
            s, 1, [], metric="revenue_aed", start_date=start, end_date=end,
            comparison="previous_period", dimensions=["store"], limit=50,
        )
        deltas = [abs(c.delta) for c in res.contributors["store"]]
        assert deltas == sorted(deltas, reverse=True)


@db
@pytest.mark.asyncio
async def test_share_of_change_matches_formula():
    from app.services.database import async_session
    start, end = _recent_window()
    async with async_session() as s:
        res = await rc.decompose(
            s, 1, [], metric="revenue_aed", start_date=start, end_date=end,
            comparison="previous_period", dimensions=["store"], limit=50,
        )
        total = res.delta.absolute
        if total != 0:
            for c in res.contributors["store"]:
                assert abs(c.share_of_change_pct - round(c.delta / total * 100.0, 2)) < 0.01


@db
@pytest.mark.asyncio
async def test_tenant_isolation_no_foreign_store_or_item():
    """Tenant 1's decomposition may only surface tenant-1 stores/items."""
    from sqlalchemy import text
    from app.services.database import async_session
    start, end = _recent_window()
    async with async_session() as s:
        t1_stores = {r.id for r in (await s.execute(text("SELECT id FROM stores WHERE tenant_id = 1"))).fetchall()}
        t1_items = {r.id for r in (await s.execute(text("SELECT id FROM items WHERE tenant_id = 1"))).fetchall()}
        res = await rc.decompose(
            s, 1, [], metric="revenue_aed", start_date=start, end_date=end,
            comparison="previous_period", dimensions=["store", "item"], limit=50,
        )
        for c in res.contributors["store"]:
            assert c.id in t1_stores, f"foreign store {c.id} leaked into tenant-1 result"
        for c in res.contributors["item"]:
            assert c.id in t1_items, f"foreign item {c.id} leaked into tenant-1 result"


@db
@pytest.mark.asyncio
async def test_store_scope_restricts_contributors():
    from sqlalchemy import text
    from app.services.database import async_session
    start, end = _recent_window()
    async with async_session() as s:
        one = (await s.execute(text("SELECT id FROM stores WHERE tenant_id = 1 ORDER BY id LIMIT 1"))).fetchone()
        allowed = [one.id]
        res = await rc.decompose(
            s, 1, allowed, metric="revenue_aed", start_date=start, end_date=end,
            comparison="previous_period", dimensions=["store"], limit=50,
        )
        assert all(c.id in allowed for c in res.contributors["store"])


@db
@pytest.mark.asyncio
async def test_empty_comparison_period_is_safe():
    """A comparison window far in the future has no data: comparison value 0,
    percent None (no div-by-zero), still returns cleanly."""
    from app.services.database import async_session
    start, end = _recent_window()
    async with async_session() as s:
        res = await rc.decompose(
            s, 1, [], metric="revenue_aed", start_date=start, end_date=end,
            comparison="previous_period",
            compare_start_date=date.today() + timedelta(days=3650),
            compare_end_date=date.today() + timedelta(days=3656),
            dimensions=["store"], limit=10,
        )
        assert res.comparison_period.value == 0
        assert res.delta.percent is None  # base is 0
        assert res.delta.absolute == res.current_period.value
