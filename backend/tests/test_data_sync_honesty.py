"""B6 — the last fabrication nest, removed.

`services/data_sync.py` used to invent business numbers with the `random`
module — promotion redemption counts and discount totals, promo start/end
dates, alert ages, inventory restock dates — and those numbers were served by
PRODUCTION routes (promotions/alerts/inventory) with no demo gate. "Never
fabricate" is the product's differentiator, so the policy is now:

  1. DERIVE from a real source when one exists (the tenant-scoped `promotions`
     table for the summary; materialization time for request-time alerts).
  2. None + a sibling "data_basis" label when nothing real exists
     ("derived_from_sales" / "derived_from_promotions" / "unavailable").
  3. Demo mode may stay populated, but pseudo-values must be a STABLE function
     of real inputs (crc32 of ids/aggregates) — identical query, identical
     numbers — and be labeled "data_basis": "demo_synthetic".

These tests pin the property at three levels: the module source contains no
`random` use at all; honest mode (demo_mode=False) nulls/labels the formerly
fabricated fields and derives the summary from the real promotions table; and
the demo pseudo-value helpers are deterministic.
"""
import inspect
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.services.data_sync as data_sync
from app.services.data_sync import (
    DataSyncService,
    _stable_choice,
    _stable_hash,
    _stable_range,
)


# --------------------------------------------------------------------------
# Fixtures / fakes
# --------------------------------------------------------------------------

@pytest.fixture
def honest(monkeypatch):
    """Force demo_mode OFF — production honesty rules apply."""
    monkeypatch.setattr(data_sync, "get_settings",
                        lambda: SimpleNamespace(demo_mode=False))


@pytest.fixture
def demo(monkeypatch):
    """Force demo_mode ON — deterministic labeled pseudo-values allowed."""
    monkeypatch.setattr(data_sync, "get_settings",
                        lambda: SimpleNamespace(demo_mode=True))


def _session(fetchall=None, scalar=None):
    """AsyncSession stand-in: every execute() returns the same result."""
    session = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = fetchall or []
    result.fetchone.return_value = None
    result.scalar.return_value = scalar
    session.execute = AsyncMock(return_value=result)
    return session


def _multi_session(result_rows_per_call):
    """AsyncSession stand-in: execute() yields one prepared result per call."""
    session = MagicMock()
    results = []
    for rows in result_rows_per_call:
        r = MagicMock()
        r.fetchall.return_value = rows
        r.fetchone.return_value = None
        r.scalar.return_value = None
        results.append(r)
    session.execute = AsyncMock(side_effect=results)
    return session


def _alert_session(fetchall):
    """Alerts use SAVEPOINTs (begin_nested); give the mock an async CM."""
    session = _session(fetchall=fetchall)
    nested = MagicMock()
    nested.__aenter__ = AsyncMock(return_value=None)
    nested.__aexit__ = AsyncMock(return_value=None)
    session.begin_nested = MagicMock(return_value=nested)
    return session


# Row shapes the mocked queries return (positional, as the service reads them).
INVENTORY_ROW = (1, 10, "Rice 5kg", "Rice & Grains", 2, "Store 2",
                 120, 50, 400, 12.5, 375, date(2026, 7, 10))
SLOW_MOVER_ROW = (10, "Rice 5kg", "Rice & Grains", 100, 3.3, 10, 6.6, "slow_mover")
FAST_MOVER_ROW = (11, "Milk 1L", "Dairy", 900, 30.0, 10, 6.6, "fast_mover")
CATEGORY_PERF_ROW = ("Dairy", 100, 90, 11.1)
LOW_STOCK_ROW = (2, "Store 2", 10, "Rice 5kg", "Rice & Grains", 3, 50)


# --------------------------------------------------------------------------
# 1. Source level: the random module is gone from data_sync entirely.
# --------------------------------------------------------------------------

def _source_without_hash_comments() -> str:
    src = inspect.getsource(data_sync)
    return "\n".join(line.split("#", 1)[0] for line in src.splitlines())


def test_data_sync_source_has_no_random_use():
    src = _source_without_hash_comments()
    assert "import random" not in src, "the random import must be gone"
    assert "random." not in src, "no random-module call may remain"


def test_data_sync_source_has_no_random_even_in_comments():
    # The merge gate greps the raw source stripping only the '# ' marker, so
    # even comment text must not spell a random-module call.
    src = inspect.getsource(data_sync).replace("# ", "")
    assert "random." not in src
    assert "import random" not in src


# --------------------------------------------------------------------------
# 2. Honest mode: formerly fabricated fields are None or carry data_basis.
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inventory_last_restocked_is_none_without_a_restock_source(honest):
    session = _session(fetchall=[INVENTORY_ROW], scalar=1)
    out = await DataSyncService.get_inventory_from_sales(session, tenant_id=1)
    item = out["items"][0]
    assert item["last_restocked"] is None
    assert item["data_basis"] == "derived_from_sales"
    # The real derived figures still flow through untouched.
    assert item["quantity"] == 120
    assert item["total_sold_30d"] == 375


@pytest.mark.asyncio
async def test_honest_mode_returns_no_invented_promotions(honest):
    stored = [("active", 2, 150.0, 30), ("ended", 5, 900.0, 210), ("draft", 1, 0, 0)]
    session = _multi_session([[SLOW_MOVER_ROW, FAST_MOVER_ROW], stored])
    out = await DataSyncService.get_promotions_from_sales(session, tenant_id=1)
    # A promotion nobody created is not data — none are emitted.
    assert out["promotions"] == []
    # The summary is DERIVED from the real promotions table, not invented
    # (was: scheduled/draft hardcoded 3/2, ended a random 20-50 every call).
    s = out["summary"]
    assert s["active_promotions"] == 2
    assert s["scheduled_promotions"] == 0
    assert s["ended_promotions"] == 5
    assert s["draft_promotions"] == 1
    assert s["total_discounts_given"] == 1050.0
    assert s["total_redemptions"] == 240
    assert s["data_basis"] == "derived_from_promotions"


@pytest.mark.asyncio
async def test_promotions_summary_query_is_tenant_scoped(honest):
    session = _multi_session([[], []])
    await DataSyncService.get_promotions_from_sales(session, tenant_id=7)
    summary_sql = str(session.execute.call_args_list[1].args[0])
    assert "FROM promotions" in summary_sql
    assert "tenant_id = :tenant_id" in summary_sql
    assert session.execute.call_args_list[1].args[1] == {"tenant_id": 7}


@pytest.mark.asyncio
async def test_category_performance_reports_no_invented_discount(honest):
    session = _session(fetchall=[CATEGORY_PERF_ROW])
    out = await DataSyncService.get_category_performance(session, tenant_id=1)
    cat = out[0]
    assert cat["avg_discount"] is None
    assert cat["data_basis"] == "derived_from_sales"
    assert cat["total_units"] == 100  # real figures untouched


@pytest.mark.asyncio
async def test_alert_created_at_is_materialization_time_not_backdated(honest):
    session = _alert_session(fetchall=[LOW_STOCK_ROW])
    before = datetime.now() - timedelta(seconds=5)
    alerts = await DataSyncService.generate_alerts_from_sales(session, tenant_id=1)
    after = datetime.now() + timedelta(seconds=5)
    low_stock = [a for a in alerts if a["alert_type"] == "inventory"]
    assert low_stock, "expected a low-stock alert from the mocked row"
    for a in low_stock:
        created = datetime.fromisoformat(a["created_at"])
        # Was: back-dated by a random 1-48 hours to fake history.
        assert before <= created <= after
        assert a["data_basis"] == "derived_from_sales"


# --------------------------------------------------------------------------
# 3. Demo mode: populated, labeled, and DETERMINISTIC — never random.
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_demo_promotions_are_labeled_and_identical_across_calls(demo):
    stored = [("active", 1, 50.0, 5)]

    async def run():
        session = _multi_session([[SLOW_MOVER_ROW, FAST_MOVER_ROW], list(stored)])
        return await DataSyncService.get_promotions_from_sales(session, tenant_id=1)

    first = await run()
    second = await run()
    assert first == second, "identical query must return identical numbers"
    assert first["promotions"], "demo mode keeps the panel populated"
    assert all(p["data_basis"] == "demo_synthetic" for p in first["promotions"])
    assert first["summary"]["data_basis"] == "demo_synthetic"
    # Real stored-promotion counts still participate in the summary.
    assert first["summary"]["active_promotions"] == 1 + len(first["promotions"])


@pytest.mark.asyncio
async def test_demo_inventory_restock_date_is_stable_and_labeled(demo):
    async def run():
        session = _session(fetchall=[INVENTORY_ROW], scalar=1)
        return await DataSyncService.get_inventory_from_sales(session, tenant_id=1)

    a = (await run())["items"][0]
    b = (await run())["items"][0]
    assert a["last_restocked"] == b["last_restocked"]
    assert a["data_basis"] == "demo_synthetic"
    # Anchored to the row's REAL last sale date, 1-7 days back — not "now".
    anchor = date(2026, 7, 10)
    restocked = date.fromisoformat(a["last_restocked"])
    assert anchor - timedelta(days=7) <= restocked <= anchor - timedelta(days=1)


@pytest.mark.asyncio
async def test_demo_category_discount_is_stable_bounded_and_labeled(demo):
    async def run():
        session = _session(fetchall=[CATEGORY_PERF_ROW])
        return await DataSyncService.get_category_performance(session, tenant_id=1)

    a = (await run())[0]
    b = (await run())[0]
    assert a["avg_discount"] == b["avg_discount"]
    assert 5 <= a["avg_discount"] < 15
    assert a["data_basis"] == "demo_synthetic"


# --------------------------------------------------------------------------
# 4. The pseudo-value helpers themselves: pure and deterministic.
# --------------------------------------------------------------------------

def test_stable_helpers_return_identical_output_for_identical_input():
    assert _stable_hash("a", 1, 2) == _stable_hash("a", 1, 2)
    assert _stable_range(5, 15, "x", 42) == _stable_range(5, 15, "x", 42)
    assert _stable_choice([10, 15, 20], "k", 7) == _stable_choice([10, 15, 20], "k", 7)


def test_stable_range_respects_bounds_and_varies_with_input():
    values = {_stable_range(1, 7, "restock", i, i * 3) for i in range(200)}
    assert all(1 <= v <= 7 for v in values)
    assert len(values) == 7, "should spread across the whole range"


def test_stable_choice_only_picks_from_options():
    options = [10, 15, 20, 25]
    picks = {_stable_choice(options, "slow-discount", i) for i in range(100)}
    assert picks.issubset(set(options))
    assert len(picks) > 1, "must not collapse to a constant"
