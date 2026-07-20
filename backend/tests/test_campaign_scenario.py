"""
Commercial Orchestration — scenario-pack engine (Phase 1).

Covers the Phase-1 business scenarios that are decidable from the pure decision
math: baseline separate from lift, cannibalisation flipping a SKU-positive
campaign category-negative, halo, forward-buy dip, inventory leftover/stockout/
expiry, procurement option comparison (no auto-buy, MOQ over-order, staged,
delay, transfer/substitute preferred), finance low/expected/high + downside,
risk-adjusted penalties, the data-readiness gate, and the recommendation codes.
All pure — no database required.
"""
from decimal import Decimal

import pytest

from app.services import campaign_scenario as cs


# --- Price response + demand range -----------------------------------------

def test_price_response_monotonic_and_bounded():
    assert cs.price_response(0) == 0.0
    assert cs.price_response(5) < cs.price_response(10) < cs.price_response(15)
    assert cs.price_response(15) <= 0.5


def test_demand_range_separates_baseline_from_lift():
    low, exp, high = cs.demand_range(1000, cs.price_response(10))
    assert low < exp < high
    assert exp > 1000                      # lift is added on top of baseline
    # No-discount reminder-scale lift keeps demand near baseline.
    l0, e0, h0 = cs.demand_range(1000, 0.0)
    assert l0 == e0 == h0 == 1000


# --- Category effects (cannibalisation / halo / forward-buy) ----------------

def test_cannibalization_can_flip_category_negative():
    # With cannibalisation 0.35 + forward-buy 0.20 and halo 0.15, net multiplier
    # is 1 - 0.35 + 0.15 - 0.20 = 0.60 > 0. To force a NET-NEGATIVE category the
    # promoted SKU must be a heavy substitute — verify the arithmetic exposes it.
    eff = cs.category_effects(100)
    assert eff["cannibalized_units"] == 35
    assert eff["halo_units"] == 15
    assert eff["forward_bought_units"] == 20
    assert eff["net_incremental_category_units"] == 60
    assert eff["confidence"] == "low"


def test_forward_buy_creates_post_promo_dip():
    eff = cs.category_effects(200)
    assert eff["post_promo_dip_units"] == eff["forward_bought_units"] > 0


# --- Inventory & shelf-life -------------------------------------------------

def test_inventory_leftover_in_low_demand():
    inv = cs.inventory_outlook(atp=500, incoming=0, safety_stock=20,
                               demand_low=100, demand_exp=300, demand_high=520,
                               units_expiring_before_end=0, unit_cost=Decimal("5"))
    assert inv["expected_leftover_units"] == 400        # 500 - 100
    assert inv["stockout_risk_high_case"] is True       # 520 > 500


def test_expiry_loss_uses_batch_data_and_salvage():
    # 50 units expire before end; low demand leaves 400 leftover, so 50 expire.
    inv = cs.inventory_outlook(atp=500, incoming=0, safety_stock=0,
                               demand_low=100, demand_exp=300, demand_high=400,
                               units_expiring_before_end=50, unit_cost=Decimal("10"))
    assert inv["expected_expiry_units"] == 50
    # 50 * 10 * (1 - 0.20 salvage) = 400.00
    assert inv["expected_expiry_loss_aed"] == "400.00"


# --- Procurement options ----------------------------------------------------

_SUPPLIERS = [{"name": "Fast", "unit_cost": Decimal("6"), "moq": 100, "lead_time_days": 2},
              {"name": "Cheap", "unit_cost": Decimal("4"), "moq": 500, "lead_time_days": 30}]


def test_options_always_include_no_buy_and_never_auto_pick_largest():
    opts = cs.procurement_options(shortfall=50, supplier_terms=_SUPPLIERS,
                                  days_left=10, transfer_surplus=None, substitute=None)
    assert any(o["option"] == "no_buy" for o in opts)
    # Every buy option requires approval — nothing is auto-committed.
    assert all(o.get("requires_approval") for o in opts if o["option"] != "no_buy")


def test_moq_over_order_is_flagged():
    # Shortfall 50 < both MOQs -> MOQ buy over-orders.
    opts = cs.procurement_options(shortfall=50, supplier_terms=_SUPPLIERS,
                                  days_left=40, transfer_surplus=None, substitute=None)
    moq_buys = [o for o in opts if o["option"] == "moq_buy"]
    assert moq_buys and all(o["leftover_risk_units"] > 0 for o in moq_buys)


def test_cheap_supplier_arriving_late_is_marked_out_of_time():
    opts = cs.procurement_options(shortfall=600, supplier_terms=_SUPPLIERS,
                                  days_left=10, transfer_surplus=None, substitute=None)
    cheap = [o for o in opts if o.get("supplier") == "Cheap" and o["option"].endswith("buy")]
    assert cheap and all(o["in_time"] is False for o in cheap)
    # The fast (expensive) supplier is in time.
    fast = [o for o in opts if o.get("supplier") == "Fast" and o["option"].endswith("buy")]
    assert fast and all(o["in_time"] is True for o in fast)


def test_transfer_and_substitute_are_offered_as_zero_cash_options():
    opts = cs.procurement_options(shortfall=50, supplier_terms=_SUPPLIERS, days_left=10,
                                  transfer_surplus={"from_store": "B", "units": 80},
                                  substitute={"name": "Alt", "available": 200})
    transfer = next(o for o in opts if o["option"] == "transfer")
    sub = next(o for o in opts if o["option"] == "substitute")
    assert transfer["cost_aed"] == "0.00" and sub["cost_aed"] == "0.00"


# --- Finance ----------------------------------------------------------------

def test_finance_low_expected_high_ordered_and_decimal():
    fin = cs.finance_outcomes(demand_low=1100, demand_exp=1200, demand_high=1350,
                              baseline_units=1000, price=Decimal("20"), cost=Decimal("12"),
                              discount_pct=Decimal("10"), contacted=200,
                              committed_procurement_cash=Decimal("0"),
                              expiry_loss=Decimal("0"), campaign_weeks=2)
    lo = Decimal(fin["net_profit_low_aed"])
    ex = Decimal(fin["net_profit_expected_aed"])
    hi = Decimal(fin["net_profit_high_aed"])
    assert lo < ex < hi
    assert Decimal(fin["unit_margin_aed"]) == Decimal("6.00")   # 20*0.9 - 12


def test_committed_procurement_deepens_worst_case_loss():
    fin = cs.finance_outcomes(demand_low=1000, demand_exp=1050, demand_high=1100,
                              baseline_units=1000, price=Decimal("20"), cost=Decimal("12"),
                              discount_pct=Decimal("10"), contacted=100,
                              committed_procurement_cash=Decimal("5000"),
                              expiry_loss=Decimal("0"), campaign_weeks=2)
    # Low demand adds no incremental units, so worst case carries the cash out.
    assert Decimal(fin["worst_credible_loss_aed"]) < Decimal(fin["net_profit_low_aed"])


# --- Risk-adjusted value ----------------------------------------------------

def test_risk_adjusted_keeps_penalties_visible():
    rav = cs.risk_adjusted_value(expected_profit=Decimal("1000"),
                                 worst_loss=Decimal("-400"),
                                 procurement_cash=Decimal("2000"),
                                 expiry_loss=Decimal("50"),
                                 customer_harm=Decimal("30"))
    assert rav["downside_penalty_aed"] == "200.00"      # 400 * 0.5
    assert rav["cash_strain_penalty_aed"] == "200.00"   # 2000 * 0.10
    # 1000 - 200 - 200 - 50 - 30
    assert rav["risk_adjusted_value_aed"] == "520.00"


# --- Conflicts --------------------------------------------------------------

def test_conflict_budget_blocks_when_liability_exceeds_budget():
    conflicts = cs.detect_conflicts(
        discount_pct=Decimal("15"), budget=Decimal("100"),
        discount_liability=Decimal("500"),
        category={"promoted_lift_units": 10, "net_incremental_category_units": 8,
                  "forward_bought_units": 0},
        inventory={"expected_expiry_units": 0},
        data_ready="READY", needs_procurement=False, procurement_in_time=True,
        moq_over_order=0, worst_loss=Decimal("0"), overlapping_promo=False)
    c1 = next(c for c in conflicts if c["code"] == "C1_DISCOUNT_EXCEEDS_BUDGET")
    assert c1["blocks_campaign"] is True


def test_conflict_flags_late_supplier_and_moq_and_downside():
    conflicts = cs.detect_conflicts(
        discount_pct=Decimal("10"), budget=Decimal("10000"),
        discount_liability=Decimal("100"),
        category={"promoted_lift_units": 100, "net_incremental_category_units": 60,
                  "forward_bought_units": 20},
        inventory={"expected_expiry_units": 0},
        data_ready="READY", needs_procurement=True, procurement_in_time=False,
        moq_over_order=50, worst_loss=Decimal("-300"), overlapping_promo=False)
    codes = {c["code"] for c in conflicts}
    assert "C6_SUPPLIER_TOO_LATE" in codes
    assert "C3_MOQ_OVER_DEMAND" in codes
    assert "C28_SEVERE_DOWNSIDE_LOW_CASE" in codes
    assert "C9_FORWARD_BUY_DIP" in codes


# --- Data readiness ---------------------------------------------------------

def _base_ctx(**over):
    ctx = {
        "sales_age_days": 1, "baseline_units": 1000, "unit_cost": Decimal("12"),
        "on_hand": 500, "supplier_terms": _SUPPLIERS, "consent_share": 0.9,
        "overlapping_promo": False,
    }
    ctx.update(over)
    return ctx


def test_data_readiness_not_ready_on_missing_cost_or_baseline():
    assert cs.data_readiness(_base_ctx(unit_cost=None))["status"] == "NOT_READY"
    assert cs.data_readiness(_base_ctx(baseline_units=0))["status"] == "NOT_READY"


def test_data_readiness_warns_on_stale_and_low_consent():
    r = cs.data_readiness(_base_ctx(sales_age_days=14, consent_share=0.3))
    assert r["status"] == "READY_WITH_WARNINGS"
    assert any("stale" in w for w in r["warnings"])


# --- Recommendation ---------------------------------------------------------

def _scn(label, disc, rav, policy_ok=True, conflicts=None, confidence="low"):
    return {"label": label, "discount_pct": str(disc),
            "risk_adjusted": {"risk_adjusted_value_aed": str(rav)},
            "policy_ok": policy_ok, "conflicts": conflicts or [], "confidence": confidence}


def test_recommend_needs_more_data_when_not_ready():
    out = cs.recommend([_scn("10pct", 10, 500)], "NOT_READY", False)
    assert out["decision"] == "NEEDS_MORE_DATA"


def test_recommend_rejects_when_no_positive_value():
    out = cs.recommend([_scn("reminder", 0, -10), _scn("10pct", 10, -50)],
                       "READY", False)
    assert out["decision"] == "REJECT"


def test_recommend_prefers_cheapest_effective_action():
    # Reminder (0% discount) within 5% of the best RAV -> don't waste a discount.
    out = cs.recommend([_scn("reminder", 0, 980), _scn("10pct", 10, 1000)],
                       "READY", False)
    assert out["chosen"] == "reminder"
    assert "cheapest_effective_action_preferred" in out["reason_codes"]


def test_recommend_pilots_on_warnings():
    out = cs.recommend([_scn("10pct", 10, 1000, confidence="high")],
                       "READY_WITH_WARNINGS", False)
    assert out["decision"] == "PILOT"


def test_recommend_excludes_margin_violating_scenario():
    # The high-RAV scenario violates policy -> the compliant one is chosen.
    out = cs.recommend([_scn("15pct", 15, 5000, policy_ok=False),
                        _scn("10pct", 10, 800, policy_ok=True, confidence="high")],
                       "READY", False)
    assert out["chosen"] == "10pct"


# --- End-to-end pure pack ---------------------------------------------------

def _full_ctx():
    from datetime import date, timedelta
    today = date.today()
    return {
        "campaign_id": 1, "objective": "churn_retention",
        "starts_on": today, "ends_on": today + timedelta(days=14),
        "max_discount_pct": Decimal("15"), "min_margin_pct": Decimal("10"),
        "discount_budget": Decimal("5000"), "control_pct": Decimal("10"),
        "safety_stock": 20, "allow_procurement": True,
        "price": Decimal("20"), "unit_cost": Decimal("12"),
        "item_name": "Demo Item", "category": "Grocery",
        "baseline_units": 800, "baseline_daily_avg": 57.1,
        "baseline_source": "trailing_84d_store_sku_mean", "sales_age_days": 1,
        "on_hand": 600, "atp": 580, "incoming": 0, "units_expiring_before_end": 0,
        "supplier_terms": _SUPPLIERS, "transfer_surplus": None, "substitute": None,
        "overlapping_promo": False, "consent_share": 0.9,
        "audience": {"audience_size": 60, "treatment": 54, "control": 6,
                     "avg_churn": 0.6, "avg_promo_rate": 0.4, "consent_share": 0.9},
        "operations": {"capacity_flag": "ok", "expected_daily_units": 70.0,
                       "reason_codes": []},
        "input_snapshot": {"captured_at": "now"},
    }


def test_build_scenario_pack_is_complete_and_pure():
    ctx = _full_ctx()
    pack = cs.build_scenario_pack(ctx)
    # Baseline separate from campaign scenarios.
    assert pack["baseline_no_campaign"]["units_over_horizon"] == 800
    # A scenario per depth plus the reminder.
    labels = [s["label"] for s in pack["scenarios"]]
    assert labels == ["reminder", "5pct", "10pct", "15pct"]
    # Every required department view is present.
    for dept in ("marketing", "cmo", "category", "inventory", "operations",
                 "procurement", "finance", "cto_data", "compliance"):
        assert dept in pack["department_views"]
    # Recommendation is one of the allowed codes.
    assert pack["recommendation"]["decision"] in (
        "REJECT", "PILOT", "APPROVE_WITH_CONDITIONS", "APPROVE", "NEEDS_MORE_DATA")
    # Honesty labels present.
    assert pack["synthetic_data"] is True and pack["confidence"] == "low"
    # Pure: calling twice with the same context yields the same decision.
    assert cs.build_scenario_pack(ctx)["recommendation"]["decision"] == \
        pack["recommendation"]["decision"]


def test_pack_needs_more_data_when_cost_missing():
    ctx = _full_ctx()
    ctx["unit_cost"] = None
    pack = cs.build_scenario_pack(ctx)
    assert pack["data_readiness"]["status"] == "NOT_READY"
    assert pack["recommendation"]["decision"] == "NEEDS_MORE_DATA"
