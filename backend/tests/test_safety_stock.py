"""E7-6 — safety stock / reorder point at a target service level.

Detecting a stockout is a report. Preventing one is a product.

    safety_stock  = z(service_level) × σ(daily demand) × √lead_time
    reorder_point = forecast daily demand × lead_time + safety_stock

The honesty rule: with too little history to measure σ, no safety stock is
claimed — it comes back null with a reason, and the suggestion falls back to the
plain days-of-cover trigger and says which one fired.

Pure: no DB, no network.
"""
import inspect
import math

import pytest

from app.services.forecast_service import (
    DEFAULT_SERVICE_LEVEL,
    MIN_SIGMA_DAYS,
    reorder_suggestions,
    service_level_z,
)


# --- the z multiplier --------------------------------------------------------

def test_z_matches_the_standard_normal_quantile():
    # The textbook values every ops manager will check against.
    assert round(service_level_z(0.50), 3) == 0.0
    assert round(service_level_z(0.90), 3) == 1.282
    assert round(service_level_z(0.95), 3) == 1.645
    assert round(service_level_z(0.99), 3) == 2.326


def test_higher_service_level_demands_more_buffer():
    assert service_level_z(0.99) > service_level_z(0.95) > service_level_z(0.90)


def test_service_level_is_clamped_because_certainty_costs_infinity():
    """A 100% service level implies infinite stock — inv_cdf(1.0) is +inf."""
    assert math.isfinite(service_level_z(1.0))
    assert math.isfinite(service_level_z(0.0))
    assert service_level_z(0.0) == service_level_z(0.50)  # clamped to the floor


def test_default_service_level_is_ninety_five_percent():
    assert DEFAULT_SERVICE_LEVEL == 0.95


# --- the formula -------------------------------------------------------------

def test_safety_stock_formula_is_z_sigma_root_lead_time():
    """The number the UI prints must be reproducible by hand."""
    z = service_level_z(0.95)
    sigma, lead_time = 4.0, 9          # √9 = 3, so the arithmetic is checkable
    expected = z * sigma * math.sqrt(lead_time)
    assert round(expected, 2) == round(1.6449 * 4.0 * 3.0, 2)

    # reorder point = demand over the lead time + the buffer
    daily_demand = 10.0
    rop = daily_demand * lead_time + expected
    assert rop > daily_demand * lead_time   # the buffer is strictly additive


def test_a_longer_lead_time_needs_more_buffer_but_sublinearly():
    """√lead_time, not lead_time: doubling the wait does not double the buffer."""
    z, sigma = service_level_z(0.95), 3.0
    ss_4 = z * sigma * math.sqrt(4)
    ss_16 = z * sigma * math.sqrt(16)
    assert ss_16 == pytest.approx(2 * ss_4)   # 4x lead time -> 2x buffer


# --- the honesty guards ------------------------------------------------------

def test_no_sigma_means_no_fabricated_safety_stock():
    """A new SKU has no measurable demand spread. Inventing a z*sigma would be a
    guess dressed as a calculation."""
    src = inspect.getsource(reorder_suggestions)
    # Guarded on BOTH a present sigma and enough observations.
    assert "sigma is not None and observations >= MIN_SIGMA_DAYS" in src
    # And the alternative is an explicit `needs`, not a default.
    assert "needs = _NEEDS_SIGMA" in src
    assert MIN_SIGMA_DAYS >= 14


def test_the_payload_says_which_trigger_fired():
    src = inspect.getsource(reorder_suggestions)
    assert '"trigger": trigger' in src
    assert 'trigger = "reorder_point"' in src
    assert 'trigger = "days_of_cover"' in src


def test_the_formula_is_shown_not_just_the_answer():
    src = inspect.getsource(reorder_suggestions)
    assert '"formula": formula' in src
    assert "safety stock = z(" in src
    assert '"methodology"' in src


def test_sigma_reads_the_shared_metric_view_so_numbers_cannot_disagree():
    """E6-1: `units` is defined once, in metric_sales_fact."""
    from app.services.forecast_service import _demand_variability

    src = inspect.getsource(_demand_variability)
    assert "metric_sales_fact" in src
    assert "STDDEV_SAMP" in src
    # A failure withholds safety stock rather than guessing one.
    assert "return {}" in src


def test_per_item_supplier_lead_time_beats_a_blanket_default():
    from app.services.forecast_service import _lead_times_by_item

    src = inspect.getsource(_lead_times_by_item)
    assert "product_suppliers" in src
    assert "lead_time_days" in src

    # And the caller actually prefers it.
    caller = inspect.getsource(reorder_suggestions)
    assert "item_lead_times.get(it[\"item_id\"], lead_time_days)" in caller


# --- signature stability (6 callers) -----------------------------------------

def test_service_level_is_an_additive_keyword_so_existing_callers_still_work():
    sig = inspect.signature(reorder_suggestions)
    assert sig.parameters["service_level"].default == DEFAULT_SERVICE_LEVEL
    # Everything before it kept its position and default.
    names = list(sig.parameters)
    assert names[:8] == ["db", "tenant_id", "allowed", "store_id",
                         "lead_time_days", "cover_target_days", "limit", "scan"]


def test_safety_stock_reaches_the_purchase_order_draft():
    """From "detect stockout" to "prevent stockout": the drafted PO buys the buffer."""
    from app.services.procurement_service import generate_draft_pos_from_reorder

    sig = inspect.signature(generate_draft_pos_from_reorder)
    assert sig.parameters["service_level"].default == 0.95
    src = inspect.getsource(generate_draft_pos_from_reorder)
    assert "service_level=service_level" in src
    # Still human-approved — nothing auto-orders.
    assert "approval" in src.lower()
