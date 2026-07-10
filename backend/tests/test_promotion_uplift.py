"""E7-5 — promotion uplift + cannibalisation.

A promo that lifts one SKU 40% while its category peers drop 35% moved sales
sideways and gave away the margin. These tests defend the two things that make
the answer trustworthy:

  * the flag FIRES when peers really are being cannibalised, and
  * it does NOT fire when the peers merely drifted the way they always do.

A flag that never fires is dead code; one that always fires is noise.
"""
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.services import promotion_uplift as pu


def _totals(units: float, revenue: float = 0.0, margin=None) -> dict:
    return {"units": units, "revenue_aed": revenue,
            "margin_aed": margin, "costed_revenue_aed": revenue}


def _windows(*totals_in_call_order):
    """Patch _window_totals to return a scripted sequence of window totals."""
    return patch.object(pu, "_window_totals", new=AsyncMock(side_effect=list(totals_in_call_order)))


# --- percentage helper -------------------------------------------------------

def test_pct_change_returns_none_not_zero_when_there_is_no_base():
    """0.0 would read as 'no change'; the truth is 'unknowable'."""
    assert pu._pct_change(0, 50) is None
    assert pu._pct_change(100, 150) == 50.0
    assert pu._pct_change(100, 50) == -50.0


# --- cannibalisation ---------------------------------------------------------

@pytest.mark.asyncio
async def test_flag_fires_when_peers_collapse_beyond_their_own_noise():
    """Promoted item lifts; peers fall 40% while their natural drift is only 2%."""
    with patch.object(pu, "_peer_items", new=AsyncMock(return_value=[2, 3, 4])), \
         _windows(_totals(600), _totals(1000), _totals(980)):
        #        peer promo=600  peer base=1000  peer prior=980  (drift 1000/980 = +2%)
        result = await pu._cannibalisation(
            AsyncMock(), 1, [1], [1],
            date(2026, 6, 15), date(2026, 6, 21),
            date(2026, 6, 8), date(2026, 6, 14),
            date(2026, 6, 1), date(2026, 6, 7),
            promoted_lifted=True,
        )

    assert result["flag"] is True
    assert result["peer_change_pct"] == -40.0
    assert result["peer_noise_pct"] == 2.0
    assert "exceeds" in result["basis"]
    # Never a bare causal claim.
    assert "Correlation, not proof" in result["basis"]


@pytest.mark.asyncio
async def test_flag_stays_down_when_the_peer_drop_is_within_normal_drift():
    """Peers fell 9%, but they routinely swing 18% between adjacent windows.
    Calling that cannibalisation would be a false accusation."""
    with patch.object(pu, "_peer_items", new=AsyncMock(return_value=[2, 3])), \
         _windows(_totals(910), _totals(1000), _totals(846)):
        #        promo=910  base=1000  prior=846 -> drift = +18.2%
        result = await pu._cannibalisation(
            AsyncMock(), 1, [1], [1],
            date(2026, 6, 15), date(2026, 6, 21),
            date(2026, 6, 8), date(2026, 6, 14),
            date(2026, 6, 1), date(2026, 6, 7),
            promoted_lifted=True,
        )

    assert result["flag"] is False
    assert result["peer_noise_pct"] == 18.2
    assert "within their own" in result["basis"]


@pytest.mark.asyncio
async def test_no_flag_when_the_promoted_item_never_lifted():
    """There is no lift to attribute to anything."""
    with patch.object(pu, "_peer_items", new=AsyncMock(return_value=[2])), \
         _windows(_totals(500), _totals(1000), _totals(1000)):
        result = await pu._cannibalisation(
            AsyncMock(), 1, [1], [1],
            date(2026, 6, 15), date(2026, 6, 21),
            date(2026, 6, 8), date(2026, 6, 14),
            date(2026, 6, 1), date(2026, 6, 7),
            promoted_lifted=False,
        )
    assert result["flag"] is False
    assert "no lift to attribute" in result["basis"]


@pytest.mark.asyncio
async def test_a_small_peer_dip_never_trips_the_flag():
    """Below the floor, whatever the arithmetic says."""
    with patch.object(pu, "_peer_items", new=AsyncMock(return_value=[2])), \
         _windows(_totals(980), _totals(1000), _totals(1000)):
        #        -2% peer change, 0% noise -> still under the 5% floor
        result = await pu._cannibalisation(
            AsyncMock(), 1, [1], [1],
            date(2026, 6, 15), date(2026, 6, 21),
            date(2026, 6, 8), date(2026, 6, 14),
            date(2026, 6, 1), date(2026, 6, 7),
            promoted_lifted=True,
        )
    assert result["flag"] is False
    assert pu.MIN_CANNIBALISATION_PCT == 5.0


@pytest.mark.asyncio
async def test_no_peers_is_stated_not_treated_as_no_cannibalisation():
    with patch.object(pu, "_peer_items", new=AsyncMock(return_value=[])):
        result = await pu._cannibalisation(
            AsyncMock(), 1, [1], [1],
            date(2026, 6, 15), date(2026, 6, 21),
            date(2026, 6, 8), date(2026, 6, 14),
            date(2026, 6, 1), date(2026, 6, 7),
            promoted_lifted=True,
        )
    assert result["status"] == "no_peers"
    assert result["flag"] is False


# --- the honest states -------------------------------------------------------

@pytest.mark.asyncio
async def test_no_baseline_sales_means_no_uplift_number_at_all():
    """The blueprint asks for this state by name: 'insufficient baseline'."""
    with _windows(_totals(500), _totals(0)):   # promo window has sales, baseline none
        result = await pu.measure_promotion_uplift(
            AsyncMock(), 1, item_ids=[1], store_ids=[1],
            start=date(2026, 6, 15), end=date(2026, 6, 21),
        )
    assert result["status"] == "insufficient_baseline"
    assert "nothing to compare against" in result["reason"]
    # And emphatically NO fabricated numbers.
    assert "uplift_units" not in result
    assert "uplift_pct" not in result


@pytest.mark.asyncio
async def test_margin_uplift_is_withheld_when_a_window_cannot_be_costed():
    with patch.object(pu, "_peer_items", new=AsyncMock(return_value=[])), \
         _windows(_totals(1200, 6000, margin=None), _totals(1000, 5000, margin=2000.0)):
        result = await pu.measure_promotion_uplift(
            AsyncMock(), 1, item_ids=[1], store_ids=[1],
            start=date(2026, 6, 15), end=date(2026, 6, 21),
        )
    assert result["status"] == "ready"
    assert result["uplift_units"] == 200.0
    assert result["uplift_margin_aed"] is None          # never 0
    assert "cost" in result["needs"]


@pytest.mark.asyncio
async def test_the_matched_baseline_is_the_equal_window_immediately_before():
    with patch.object(pu, "_peer_items", new=AsyncMock(return_value=[])), \
         _windows(_totals(1200, 1.0, 1.0), _totals(1000, 1.0, 1.0)):
        result = await pu.measure_promotion_uplift(
            AsyncMock(), 1, item_ids=[1], store_ids=[1],
            start=date(2026, 6, 15), end=date(2026, 6, 21),   # 7 days
        )
    assert result["window"]["days"] == 7
    assert result["baseline_window"] == {"start": "2026-06-08", "end": "2026-06-14"}
    assert result["uplift_pct"] == 20.0


@pytest.mark.asyncio
async def test_stores_outside_the_callers_scope_are_dropped():
    """A store manager must not measure a promo across stores they cannot see."""
    result = await pu.measure_promotion_uplift(
        AsyncMock(), 1, item_ids=[1], store_ids=[7, 8],
        start=date(2026, 6, 15), end=date(2026, 6, 21), allowed=[1, 2],
    )
    assert result["status"] == "no_scope"


@pytest.mark.asyncio
async def test_an_inverted_window_is_rejected():
    result = await pu.measure_promotion_uplift(
        AsyncMock(), 1, item_ids=[1], store_ids=[1],
        start=date(2026, 6, 21), end=date(2026, 6, 15),
    )
    assert result["status"] == "invalid_window"


# --- reads the shared metric layer -------------------------------------------

def test_uplift_reads_the_same_views_as_the_kpi_screens():
    """E6-1/E2-3: `units`, `revenue_aed` and margin are each defined exactly once."""
    import inspect
    src = inspect.getsource(pu._window_totals)
    assert "metric_margin_fact" in src
    assert "gross_margin_aed" in src
    # cogs NULL -> margin NULL, not 0.
    assert "FILTER (WHERE m.cogs_aed IS NOT NULL)" in src


# --- security regression: promotions were cross-tenant writable ---------------
#
# `promotions` predates multi-tenancy. Its write endpoints checked only the
# caller's ROLE (`can_manage_promotions`) and then updated by bare id, so a
# promo manager in tenant A could edit, approve or cancel tenant B's promotion.
# Role says WHAT you may do; tenant says WHOSE data. Migration 060 + these guards.

def test_migration_060_tenant_scopes_promotions():
    import os
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(repo, "database", "migrations",
                           "060_krishna_promotion_tenancy.sql"), encoding="utf-8") as fh:
        sql = fh.read()

    assert "ALTER TABLE promotions" in sql and "tenant_id" in sql
    assert "ALTER TABLE promotions ENABLE ROW LEVEL SECURITY" in sql
    assert "tenant_id = current_tenant_id()" in sql
    # Line tables scoped through the parent, matching migration 020's pattern.
    assert "EXISTS (SELECT 1 FROM promotions p" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql


def test_every_promotion_write_is_tenant_filtered_not_just_role_checked():
    import inspect

    from app.routes import promotions as routes

    for fn in (routes.update_promotion, routes.delete_promotion):
        src = inspect.getsource(fn)
        assert "tenant_id = :tenant_id" in src, f"{fn.__name__} updates by bare id"

    created = inspect.getsource(routes.create_promotion)
    assert '"tenant_id": current_user.get("tenant_id")' in created


def test_uplift_by_id_cannot_read_another_tenants_promotion():
    import inspect
    src = inspect.getsource(pu.measure_promotion_by_id)
    assert "WHERE id = :pid AND tenant_id = :tid" in src
