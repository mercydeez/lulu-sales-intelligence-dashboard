"""
Campaign scenario-pack engine (Commercial Orchestration, Phase 1).

Turns a campaign contract into a department-neutral DECISION PACK that a
reviewer reads before launch: normal (no-campaign) demand, low/expected/high
outcomes across offer depths, category effects (cannibalisation / halo /
forward-buy), inventory & shelf-life risk, PROPOSED procurement options (never
an auto-created PO), finance cash/profit ranges with visible downside, a
risk-adjusted recommendation with reason codes, per-department plain-language
views, and a machine-readable conflict catalogue.

DESIGN RULES honoured here (from the master prompt):
  * NO side effects: everything is a read + pure compute. The only write is
    persisting the pack itself into retention_campaigns.simulation (JSONB) so a
    decision is reproducible from its stored inputs. No money, no stock, no PO.
  * Money is Decimal end-to-end; every recommendation carries low/expected/high,
    confidence and reason codes — never a single optimistic number.
  * Causal estimates (cannibalisation/halo/forward-buy, price response) are
    TRANSPARENT HEURISTICS labelled provisional with confidence='low'. They are
    honest placeholders until randomized history trains them (Phase 4), never
    presented as measured causal effects.
  * Never auto-select the largest procurement order; options are compared and a
    pilot / partial / transfer / substitute / no-buy is preferred.

Reuses: forecast_service.demand_baseline (category baseline), sales_fact_view
(per-SKU baseline), inventory + inventory_batches (ATP + FEFO expiry),
product_suppliers (supplier terms), item_costs/unit_cost_aed (margin),
retention_service.response_prob (audience response).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import logger

CENT = Decimal("0.01")
SCENARIO_MODEL_VERSION = "scenario_heuristic_v1"

# --- Heuristic coefficients (transparent, provisional, confidence='low') -----
# Promoted-SKU lift as a fraction of baseline demand, by discount depth. A
# saturating curve: each extra point of discount buys less lift. Documented,
# not trained — the price/promotion response model (master prompt §11.D) that
# replaces this keeps the same signature.
_LIFT_BY_DISCOUNT = {0: 0.0, 5: 0.10, 10: 0.22, 15: 0.35, 20: 0.45}
# Uncertainty band applied to every demand estimate to yield low/high.
_DEMAND_BAND = 0.40
# Share of promoted lift that is NOT truly incremental at the category level.
_CANNIBAL_FRAC = 0.35   # stolen from same-category substitutes
_HALO_FRAC = 0.15       # added to complementary products
_FORWARD_FRAC = 0.20    # demand pulled forward -> post-promotion dip
# Reminder (no discount) lift — a small nudge, cheaper than any discount.
_REMINDER_LIFT = 0.04
# Communication + media cost per contacted customer (AED).
_COMM_COST = Decimal("0.05")
_MEDIA_COST_PER_CUSTOMER = Decimal("0.10")
# Fraction of recoverable value on expired/marked-down stock.
_SALVAGE_FRAC = Decimal("0.20")


def _d(x) -> Decimal:
    return Decimal(str(x))


def _q(x: Decimal) -> Decimal:
    return x.quantize(CENT, ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Pure decision math (unit-testable without a database)
# ---------------------------------------------------------------------------

def price_response(discount_pct: float) -> float:
    """Promoted-SKU lift fraction of baseline for a discount depth. Linear
    interpolation over the documented saturating curve."""
    d = float(discount_pct)
    keys = sorted(_LIFT_BY_DISCOUNT)
    if d <= keys[0]:
        return _LIFT_BY_DISCOUNT[keys[0]]
    if d >= keys[-1]:
        return _LIFT_BY_DISCOUNT[keys[-1]]
    for lo, hi in zip(keys, keys[1:]):
        if lo <= d <= hi:
            f = (d - lo) / (hi - lo)
            return _LIFT_BY_DISCOUNT[lo] + f * (_LIFT_BY_DISCOUNT[hi] - _LIFT_BY_DISCOUNT[lo])
    return _LIFT_BY_DISCOUNT[keys[-1]]


def demand_range(baseline_units: float, lift_fraction: float) -> Tuple[int, int, int]:
    """(low, expected, high) campaign demand = baseline + promoted lift, with a
    symmetric uncertainty band on the lift."""
    expected_lift = baseline_units * lift_fraction
    low = baseline_units + expected_lift * (1 - _DEMAND_BAND)
    high = baseline_units + expected_lift * (1 + _DEMAND_BAND)
    exp = baseline_units + expected_lift
    return int(round(low)), int(round(exp)), int(round(high))


def category_effects(promoted_lift_units: float) -> Dict:
    """Indirect effects on the category. Transparent rules; confidence low."""
    cannibalized = promoted_lift_units * _CANNIBAL_FRAC
    halo = promoted_lift_units * _HALO_FRAC
    forward = promoted_lift_units * _FORWARD_FRAC
    net = promoted_lift_units - cannibalized + halo - forward
    return {
        "promoted_lift_units": int(round(promoted_lift_units)),
        "cannibalized_units": int(round(cannibalized)),
        "halo_units": int(round(halo)),
        "forward_bought_units": int(round(forward)),
        "post_promo_dip_units": int(round(forward)),
        "net_incremental_category_units": int(round(net)),
        "confidence": "low",
        "basis": "transparent_heuristic_provisional",
    }


def inventory_outlook(atp: int, incoming: int, safety_stock: int,
                      demand_low: int, demand_exp: int, demand_high: int,
                      units_expiring_before_end: int, unit_cost: Optional[Decimal]
                      ) -> Dict:
    """Physical safety of the campaign. Stockout risk from the high-demand case,
    leftover from the low-demand case, expiry loss from FEFO batch data."""
    supply = atp + incoming
    ending_low = supply - demand_high      # worst demand -> lowest ending stock
    ending_high = supply - demand_low       # best-for-stock demand
    stockout = demand_high > supply
    stockout_exp = demand_exp > supply
    leftover = max(0, supply - demand_low)
    # Units that will expire unsold: those expiring before end that the low-
    # demand case will not sell through.
    expiry_units = max(0, min(units_expiring_before_end, leftover))
    expiry_loss = (_q(_d(expiry_units) * unit_cost * (1 - _SALVAGE_FRAC))
                   if unit_cost is not None else None)
    return {
        "available_to_promise": atp,
        "incoming_supply": incoming,
        "safety_stock": safety_stock,
        "ending_stock_low": ending_low,
        "ending_stock_high": ending_high,
        "stockout_expected": stockout_exp,
        "stockout_risk_high_case": stockout,
        "expected_leftover_units": leftover,
        "units_expiring_before_end": units_expiring_before_end,
        "expected_expiry_units": expiry_units,
        "expected_expiry_loss_aed": str(expiry_loss) if expiry_loss is not None else None,
    }


def procurement_options(shortfall: int, supplier_terms: List[Dict], days_left: int,
                        transfer_surplus: Optional[Dict],
                        substitute: Optional[Dict]) -> List[Dict]:
    """Enumerate — and compare — ways to cover a shortfall. NEVER auto-picks the
    largest order. Always includes no_buy; procurement options are flagged with
    their approval requirement and whether they arrive in time."""
    options: List[Dict] = [{
        "option": "no_buy", "units": 0, "cost_aed": "0.00",
        "arrives_in_days": 0, "in_time": True, "residual_stockout_risk": shortfall > 0,
        "requires_approval": False, "note": "accept the shortfall / reduce audience",
    }]
    if shortfall <= 0:
        return options
    if transfer_surplus:
        options.append({
            "option": "transfer", "units": min(shortfall, transfer_surplus["units"]),
            "cost_aed": "0.00", "arrives_in_days": 1, "in_time": True,
            "from_store": transfer_surplus.get("from_store"),
            "residual_stockout_risk": transfer_surplus["units"] < shortfall,
            "requires_approval": True, "approver": "inventory_manager",
            "note": "move existing stock from a surplus store (no cash out)",
        })
    if substitute:
        options.append({
            "option": "substitute", "units": min(shortfall, substitute["available"]),
            "cost_aed": "0.00", "arrives_in_days": 0, "in_time": True,
            "substitute_item": substitute.get("name"),
            "residual_stockout_risk": False, "requires_approval": True,
            "approver": "category_manager",
            "note": "offer an in-stock same-category substitute",
        })
    for s in supplier_terms:
        moq = int(s["moq"])
        lead = int(s["lead_time_days"])
        unit_cost = _d(s["unit_cost"])
        in_time = lead < days_left
        # Partial: exactly the shortfall (if >= MOQ), else MOQ buy.
        partial_qty = shortfall if shortfall >= moq else moq
        options.append({
            "option": "moq_buy" if shortfall < moq else "partial_buy",
            "supplier": s["name"], "units": partial_qty,
            "cost_aed": str(_q(unit_cost * partial_qty)),
            "unit_cost_aed": str(unit_cost),
            "arrives_in_days": lead, "in_time": in_time,
            "leftover_risk_units": max(0, partial_qty - shortfall),
            "residual_stockout_risk": not in_time,
            "requires_approval": True, "approver": "procurement_manager",
            "note": ("MOQ forces over-ordering by "
                     f"{max(0, moq - shortfall)} units" if shortfall < moq
                     else "order exactly the shortfall"),
        })
        # Staged: split into two smaller commitments (safer than one bulk buy).
        if partial_qty >= 2 * moq:
            options.append({
                "option": "staged_buy", "supplier": s["name"],
                "units": partial_qty, "stages": 2,
                "first_stage_units": max(moq, partial_qty // 2),
                "cost_aed": str(_q(unit_cost * partial_qty)),
                "arrives_in_days": lead, "in_time": in_time,
                "requires_approval": True, "approver": "procurement_manager",
                "note": "commit half now, half on confirmed pilot signal",
            })
        if not in_time:
            options.append({
                "option": "delay_campaign", "supplier": s["name"],
                "units": partial_qty, "arrives_in_days": lead,
                "in_time": False, "requires_approval": True,
                "approver": "marketing_approver",
                "note": f"supplier lead time {lead}d exceeds {days_left}d to campaign end",
            })
    return options


def finance_outcomes(demand_low: int, demand_exp: int, demand_high: int,
                     baseline_units: int, price: Decimal, cost: Optional[Decimal],
                     discount_pct: Decimal, contacted: int,
                     committed_procurement_cash: Decimal, expiry_loss: Decimal,
                     campaign_weeks: int) -> Dict:
    """Low/expected/high profit, worst credible loss, weekly cash. Decimal only.
    Incremental units = campaign demand − baseline (the campaign only earns on
    what it adds); discount cost applies to the promoted (incremental) units."""
    d = discount_pct / Decimal(100)
    unit_margin = (price * (1 - d) - cost) if cost is not None else None
    media = _MEDIA_COST_PER_CUSTOMER * contacted
    comm = _COMM_COST * contacted

    def profit(units: int) -> Decimal:
        incr = max(0, units - baseline_units)
        if unit_margin is None:
            return _q(-media - comm - committed_procurement_cash - expiry_loss)
        gross = _d(incr) * unit_margin
        return _q(gross - media - comm - expiry_loss)

    low_p, exp_p, high_p = profit(demand_low), profit(demand_exp), profit(demand_high)
    # Worst credible loss also carries any irreversible procurement cash that the
    # low-demand case cannot recover through sales.
    worst = _q(low_p - committed_procurement_cash) if committed_procurement_cash > 0 else low_p
    discount_liability = (_q(_d(max(0, demand_exp - baseline_units)) * price * d)
                          if cost is not None else Decimal("0.00"))
    weeks = max(1, campaign_weeks)
    weekly_discount = _q(discount_liability / weeks)
    contribution_margin = exp_p
    payback_weeks = None
    if exp_p > 0 and committed_procurement_cash > 0:
        payback_weeks = float((committed_procurement_cash / (exp_p / weeks)).quantize(Decimal("0.1")))
    return {
        "unit_margin_aed": str(_q(unit_margin)) if unit_margin is not None else None,
        "discount_liability_aed": str(discount_liability),
        "media_cost_aed": str(_q(media)),
        "net_profit_low_aed": str(low_p),
        "net_profit_expected_aed": str(exp_p),
        "net_profit_high_aed": str(high_p),
        "worst_credible_loss_aed": str(worst),
        "contribution_margin_aed": str(contribution_margin),
        "committed_procurement_cash_aed": str(_q(committed_procurement_cash)),
        "weekly_discount_cash_aed": str(weekly_discount),
        "expiry_loss_aed": str(_q(expiry_loss)),
        "payback_weeks": payback_weeks,
    }


def risk_adjusted_value(expected_profit: Decimal, worst_loss: Decimal,
                        procurement_cash: Decimal, expiry_loss: Decimal,
                        customer_harm: Decimal) -> Dict:
    """Keep every penalty visible instead of hiding it in one score."""
    downside = _q(max(Decimal("0"), -worst_loss) * Decimal("0.5"))
    cash_strain = _q(procurement_cash * Decimal("0.10"))
    rav = _q(expected_profit - downside - cash_strain - expiry_loss - customer_harm)
    return {
        "expected_profit_aed": str(_q(expected_profit)),
        "downside_penalty_aed": str(downside),
        "cash_strain_penalty_aed": str(cash_strain),
        "expiry_penalty_aed": str(_q(expiry_loss)),
        "customer_harm_penalty_aed": str(_q(customer_harm)),
        "risk_adjusted_value_aed": str(rav),
    }


def detect_conflicts(*, discount_pct: Decimal, budget: Decimal,
                     discount_liability: Decimal, category: Dict,
                     inventory: Dict, data_ready: str, needs_procurement: bool,
                     procurement_in_time: bool, moq_over_order: int,
                     worst_loss: Decimal, overlapping_promo: bool) -> List[Dict]:
    """Machine-readable conflict catalogue (Phase-1 computable subset)."""
    out: List[Dict] = []

    def add(code, dept, evidence, impact, resolution, approver, blocked):
        out.append({"code": code, "department": dept, "evidence": evidence,
                    "impact": impact, "resolution": resolution,
                    "required_approver": approver, "blocks_campaign": blocked})

    if discount_liability > budget:
        add("C1_DISCOUNT_EXCEEDS_BUDGET", "finance",
            f"expected discount liability AED {discount_liability} > budget AED {budget}",
            "campaign cannot be funded at this depth/audience",
            "reduce discount depth or audience, or increase budget",
            "finance_controller", True)
    if category["net_incremental_category_units"] < 0 < category["promoted_lift_units"]:
        add("C7_CANNIBALIZATION_NET_NEGATIVE", "category",
            f"promoted lift {category['promoted_lift_units']} but net category "
            f"{category['net_incremental_category_units']} after cannibalisation",
            "SKU looks positive but the category loses units",
            "target incremental customers only, or pick a less cannibalising SKU",
            "category_manager", False)
    if category["forward_bought_units"] > 0:
        add("C9_FORWARD_BUY_DIP", "category",
            f"~{category['forward_bought_units']} units pulled from future weeks",
            "post-campaign demand dip expected",
            "size the campaign for net-of-dip value; avoid back-to-back promos",
            "category_manager", False)
    if inventory.get("expected_expiry_units", 0) > 0:
        add("C13_SHELF_LIFE_RISK", "inventory",
            f"{inventory['expected_expiry_units']} units expire before sell-through",
            f"expected waste loss AED {inventory.get('expected_expiry_loss_aed')}",
            "prefer near-expiry clearance framing / FEFO allocation",
            "inventory_manager", False)
    if needs_procurement and not procurement_in_time:
        add("C6_SUPPLIER_TOO_LATE", "procurement",
            "cheapest supplier lead time exceeds the campaign window",
            "procurement cannot arrive before campaign end",
            "delay the campaign, expedite, transfer, or drop the SKU",
            "procurement_manager", False)
    if moq_over_order > 0:
        add("C3_MOQ_OVER_DEMAND", "procurement",
            f"MOQ forces {moq_over_order} units above risk-adjusted demand",
            "excess leftover / working-capital exposure",
            "prefer transfer/substitute/partial, or a staged order",
            "procurement_manager", False)
    if data_ready == "NOT_READY":
        add("C26_LOW_CONFIDENCE_FOR_SPEND", "cto_data",
            "data readiness is NOT_READY",
            "irreversible spend on low-confidence inputs",
            "run a pilot or refresh data before committing",
            "cto_data_owner", True)
    if worst_loss < 0:
        add("C28_SEVERE_DOWNSIDE_LOW_CASE", "finance",
            f"low-demand case loses AED {worst_loss}",
            "profitable on average but severe downside if response is weak",
            "pilot first; commit procurement only on confirmed signal",
            "finance_controller", False)
    if overlapping_promo:
        add("C10_OVERLAPPING_PROMOTION", "marketing",
            "an active promotion overlaps this store/item and window",
            "discount stacking / attribution confusion",
            "deconflict dates or exclude the overlapping offer",
            "marketing_approver", False)
    return out


def data_readiness(ctx: Dict) -> Dict:
    """Gate before AI drives a decision. READY / READY_WITH_WARNINGS / NOT_READY
    with blocking reasons — a stale/low-confidence input must not silently drive
    a financial commitment (master prompt §10)."""
    warnings: List[str] = []
    blockers: List[str] = []
    if ctx["sales_age_days"] is None:
        blockers.append("no_sales_history_for_sku")
    elif ctx["sales_age_days"] > 7:
        warnings.append(f"sales_data_stale_{ctx['sales_age_days']}d")
    if ctx["baseline_units"] <= 0:
        blockers.append("baseline_demand_unavailable")
    if ctx["unit_cost"] is None:
        blockers.append("missing_unit_cost")     # cannot compute margin honestly
    if ctx["on_hand"] < 0:
        blockers.append("impossible_negative_inventory")
    if not ctx["supplier_terms"]:
        warnings.append("no_supplier_terms_procurement_limited")
    if ctx["consent_share"] < 0.5:
        warnings.append("low_consent_share_audience")
    if ctx["overlapping_promo"]:
        warnings.append("overlapping_promotion_detected")
    status = "NOT_READY" if blockers else ("READY_WITH_WARNINGS" if warnings else "READY")
    return {"status": status, "blockers": blockers, "warnings": warnings}


def recommend(scenarios: List[Dict], readiness: str, has_irreversible_procurement: bool
              ) -> Dict:
    """Pick the best risk-adjusted scenario and map it to a decision code.
    High churn / big lift never wins on its own — risk-adjusted value decides,
    and low confidence or irreversible spend forces PILOT."""
    if readiness == "NOT_READY":
        return {"decision": "NEEDS_MORE_DATA", "chosen": None,
                "reason_codes": ["data_not_ready"],
                "conditions": ["resolve data blockers before simulating spend"]}
    # Only policy-compliant scenarios are eligible (margin floor, known cost).
    eligible = [s for s in scenarios if s.get("policy_ok", True)] or scenarios
    ranked = sorted(eligible, key=lambda s: _d(s["risk_adjusted"]["risk_adjusted_value_aed"]),
                    reverse=True)
    best = ranked[0]
    rav = _d(best["risk_adjusted"]["risk_adjusted_value_aed"])
    reasons: List[str] = [f"best_risk_adjusted_value_{best['label']}"]
    conditions: List[str] = []

    if rav <= 0:
        # Even the best option destroys risk-adjusted value.
        return {"decision": "REJECT", "chosen": best["label"],
                "reason_codes": reasons + ["no_positive_risk_adjusted_option"],
                "conditions": ["no discount depth clears the downside/expiry/cash penalties"]}

    blocking = any(c["blocks_campaign"] for c in best["conflicts"])
    if blocking:
        return {"decision": "REJECT", "chosen": best["label"],
                "reason_codes": reasons + ["blocking_conflict"],
                "conditions": [c["code"] for c in best["conflicts"] if c["blocks_campaign"]]}

    # Prefer the cheapest effective action: if a no-discount/reminder scenario is
    # within 5% of the best RAV, recommend it instead (don't waste discount).
    cheap = next((s for s in ranked
                  if s["discount_pct"] == "0"
                  and _d(s["risk_adjusted"]["risk_adjusted_value_aed"]) >= rav * Decimal("0.95")), None)
    if cheap and cheap["label"] != best["label"]:
        best = cheap
        reasons.append("cheapest_effective_action_preferred")

    if readiness == "READY_WITH_WARNINGS" or has_irreversible_procurement \
            or best["confidence"] == "low":
        return {"decision": "PILOT", "chosen": best["label"],
                "reason_codes": reasons + ["pilot_before_scale"],
                "conditions": ["run a limited pilot with control group",
                               "commit procurement only on confirmed pilot signal"]}
    if any(best["conflicts"]):
        return {"decision": "APPROVE_WITH_CONDITIONS", "chosen": best["label"],
                "reason_codes": reasons,
                "conditions": [c["code"] for c in best["conflicts"]]}
    return {"decision": "APPROVE", "chosen": best["label"], "reason_codes": reasons,
            "conditions": []}


def department_views(pack: Dict) -> Dict:
    """One shared truth, tailored plain-language views. Each department sees the
    metrics it approves on plus its reason codes."""
    chosen = next((s for s in pack["scenarios"] if s["label"] == pack["recommendation"]["chosen"]),
                  pack["scenarios"][-1] if pack["scenarios"] else None)
    fin = chosen["finance"] if chosen else {}
    inv = chosen["inventory"] if chosen else {}
    cat = chosen["category"] if chosen else {}
    aud = pack["audience"]
    return {
        "marketing": {
            "headline": f"Reach {aud['treatment']} treated / {aud['control']} control; "
                        f"recommended: {pack['recommendation']['decision']}",
            "metrics": {"audience": aud["audience_size"],
                        "expected_redemptions": chosen["expected_redemptions"] if chosen else 0,
                        "offer": chosen["label"] if chosen else None},
            "reason_codes": pack["recommendation"]["reason_codes"],
        },
        "cmo": {
            "headline": "Customer strategy, offer depth and brand/reference-price risk",
            "metrics": {"max_discount_pct": chosen["discount_pct"] if chosen else "0",
                        "net_incremental_category_units": cat.get("net_incremental_category_units")},
            "reason_codes": [c["code"] for c in (chosen["conflicts"] if chosen else [])
                             if c["department"] in ("marketing", "category")],
        },
        "category": {
            "headline": f"Net category effect after cannibalisation/halo/forward-buy",
            "metrics": cat,
            "reason_codes": [c["code"] for c in (chosen["conflicts"] if chosen else [])
                             if c["department"] == "category"],
        },
        "inventory": {
            "headline": "Available-to-promise, stockout, leftover and shelf-life risk",
            "metrics": inv,
            "reason_codes": [c["code"] for c in (chosen["conflicts"] if chosen else [])
                             if c["department"] == "inventory"],
        },
        "operations": {
            "headline": "Store capacity and replenishment load (rules baseline)",
            "metrics": {"expected_units": chosen["demand_expected"] if chosen else 0,
                        "capacity_flag": pack["operations"]["capacity_flag"]},
            "reason_codes": pack["operations"]["reason_codes"],
        },
        "procurement": {
            "headline": "Buy/transfer/substitute options — no PO created in simulation",
            "metrics": {"options": chosen["procurement_options"] if chosen else []},
            "reason_codes": [c["code"] for c in (chosen["conflicts"] if chosen else [])
                             if c["department"] == "procurement"],
        },
        "finance": {
            "headline": f"Profit low/expected/high AED "
                        f"{fin.get('net_profit_low_aed')}/{fin.get('net_profit_expected_aed')}/"
                        f"{fin.get('net_profit_high_aed')}; worst loss AED {fin.get('worst_credible_loss_aed')}",
            "metrics": fin,
            "reason_codes": [c["code"] for c in (chosen["conflicts"] if chosen else [])
                             if c["department"] == "finance"],
        },
        "cto_data": {
            "headline": f"Data readiness {pack['data_readiness']['status']}; "
                        f"model {SCENARIO_MODEL_VERSION} (heuristic, confidence low)",
            "metrics": {"data_readiness": pack["data_readiness"],
                        "model_version": SCENARIO_MODEL_VERSION,
                        "confidence": "low", "synthetic_data": True},
            "reason_codes": pack["data_readiness"]["blockers"] + pack["data_readiness"]["warnings"],
        },
        "compliance": {
            "headline": "Consent, contact-frequency and protected-attribute exclusion",
            "metrics": {"consent_share": pack["audience"]["consent_share"],
                        "protected_attributes_used": False},
            "reason_codes": (["low_consent_share"] if pack["audience"]["consent_share"] < 0.5 else []),
        },
    }


def build_scenario_pack(ctx: Dict, depths: Tuple[int, ...] = (0, 5, 10, 15)) -> Dict:
    """PURE orchestrator: assemble the full decision pack from a gathered
    context. No I/O — deterministic and fully unit-testable."""
    price = ctx["price"]
    cost = ctx["unit_cost"]
    baseline = ctx["baseline_units"]
    days_left = max(0, (ctx["ends_on"] - date.today()).days)
    campaign_weeks = max(1, ((ctx["ends_on"] - ctx["starts_on"]).days + 1) // 7 or 1)
    contacted = ctx["audience"]["treatment"]

    readiness = data_readiness(ctx)
    scenarios: List[Dict] = []
    has_irreversible = False

    # Scenario 0 is always "reminder" (no discount) as the cheap baseline action;
    # the rest are discount depths.
    labelled: List[Tuple[str, int]] = [("reminder", 0)] + [(f"{d}pct", d) for d in depths if d > 0]

    for label, depth in labelled:
        lift_frac = _REMINDER_LIFT if label == "reminder" else price_response(depth)
        d_low, d_exp, d_high = demand_range(baseline, lift_frac)
        promoted_lift = d_exp - baseline
        cat = category_effects(promoted_lift)

        # Inventory & shelf-life.
        inv = inventory_outlook(ctx["atp"], ctx["incoming"], ctx["safety_stock"],
                                d_low, d_exp, d_high, ctx["units_expiring_before_end"], cost)
        expiry_loss = _d(inv["expected_expiry_loss_aed"]) if inv["expected_expiry_loss_aed"] else Decimal("0")

        # Procurement options for the high-demand shortfall (compared, never auto-bought).
        shortfall = max(0, d_high - (ctx["atp"] + ctx["incoming"]))
        opts = procurement_options(shortfall, ctx["supplier_terms"], days_left,
                                   ctx["transfer_surplus"], ctx["substitute"])
        cheapest_buy = next((o for o in opts if o.get("approver") == "procurement_manager"), None)
        needs_procurement = shortfall > 0 and ctx["allow_procurement"]
        procurement_in_time = bool(cheapest_buy and cheapest_buy.get("in_time"))
        moq_over = cheapest_buy.get("leftover_risk_units", 0) if cheapest_buy else 0
        # Simulation never commits cash; committed cash is 0 here by design.
        committed_cash = Decimal("0")

        disc = Decimal(str(depth))
        # Margin-floor guardrail: a depth selling below min_margin_pct (or with
        # unknown cost) is policy-blocked and excluded from the recommendation.
        policy_ok, policy_reason = True, None
        if depth > 0:
            if cost is None:
                policy_ok, policy_reason = False, "cost_unknown_cannot_discount"
            else:
                margin_pct = (price * (1 - disc / Decimal(100)) - cost) / price * Decimal(100)
                if margin_pct < ctx["min_margin_pct"]:
                    policy_ok, policy_reason = False, "below_min_margin_floor"
        fin = finance_outcomes(d_low, d_exp, d_high, baseline, price, cost, disc,
                               contacted, committed_cash, expiry_loss, campaign_weeks)
        # Customer-harm penalty: deep discounts on discount-conditioned audiences.
        harm = _d(fin["discount_liability_aed"]) * Decimal("0.05") if depth >= 15 else Decimal("0")
        rav = risk_adjusted_value(_d(fin["net_profit_expected_aed"]),
                                  _d(fin["worst_credible_loss_aed"]),
                                  committed_cash, expiry_loss, harm)

        conflicts = detect_conflicts(
            discount_pct=disc, budget=ctx["discount_budget"],
            discount_liability=_d(fin["discount_liability_aed"]),
            category=cat, inventory=inv, data_ready=readiness["status"],
            needs_procurement=needs_procurement, procurement_in_time=procurement_in_time,
            moq_over_order=moq_over, worst_loss=_d(fin["worst_credible_loss_aed"]),
            overlapping_promo=ctx["overlapping_promo"])

        # Response/redemption estimate from the audience's promo affinity.
        from app.services.retention_service import response_prob
        resp = response_prob(ctx["audience"]["avg_churn"], float(depth), ctx["audience"]["avg_promo_rate"])
        expected_redemptions = int(round(contacted * resp)) if depth > 0 else int(round(contacted * resp * 0.5))

        scenarios.append({
            "label": label, "discount_pct": str(disc),
            "demand_low": d_low, "demand_expected": d_exp, "demand_high": d_high,
            "baseline_units": baseline, "category": cat, "inventory": inv,
            "procurement_options": opts, "finance": fin, "risk_adjusted": rav,
            "conflicts": conflicts, "expected_redemptions": expected_redemptions,
            "response_prob": resp, "confidence": "low",
            "policy_ok": policy_ok, "policy_reason": policy_reason,
        })

    rec = recommend(scenarios, readiness["status"], has_irreversible)

    pack = {
        "campaign_id": ctx["campaign_id"],
        "objective": ctx["objective"],
        "guardrails": {"max_discount_pct": str(ctx["max_discount_pct"]),
                       "min_margin_pct": str(ctx["min_margin_pct"]),
                       "discount_budget_aed": str(ctx["discount_budget"]),
                       "safety_stock_units": ctx["safety_stock"],
                       "control_pct": str(ctx["control_pct"])},
        "data_readiness": readiness,
        "baseline_no_campaign": {"units_over_horizon": baseline,
                                 "daily_avg": ctx["baseline_daily_avg"],
                                 "source": ctx["baseline_source"]},
        "audience": ctx["audience"],
        "operations": ctx["operations"],
        "scenarios": scenarios,
        "recommendation": rec,
        "input_snapshot": ctx["input_snapshot"],
        "model_version": SCENARIO_MODEL_VERSION,
        "confidence": "low",
        "synthetic_data": True,
        "assumptions": [
            "price response, cannibalisation, halo and forward-buy are transparent "
            "provisional heuristics (confidence low) until randomized history trains them",
            "baseline demand from trailing store/SKU sales; category baseline from the forecast engine",
            "no financial or inventory side effect occurs during simulation",
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    pack["department_views"] = department_views(pack)
    return pack


# ---------------------------------------------------------------------------
# Async context gathering + persistence (the only DB touch — reads + one JSONB write)
# ---------------------------------------------------------------------------

async def gather_context(db: AsyncSession, tenant_id: int, campaign: Dict) -> Dict:
    """Collect every input the pure engine needs. Reads only."""
    store_id, item_id = campaign["store_id"], campaign["item_id"]
    starts, ends = campaign["starts_on"], campaign["ends_on"]
    horizon_days = max(1, (ends - starts).days + 1)

    item = (await db.execute(text("""
        SELECT name, category, unit_price_aed, unit_cost_aed
        FROM items WHERE id = :i AND tenant_id = :t
    """), {"i": item_id, "t": tenant_id})).mappings().fetchone()
    price = _d(item["unit_price_aed"])
    cost = _d(item["unit_cost_aed"]) if item["unit_cost_aed"] is not None else None

    # Per-SKU baseline: trailing 84-day mean daily units at this store/item.
    base = (await db.execute(text("""
        SELECT COALESCE(SUM(sales), 0) AS units,
               COUNT(DISTINCT date) AS days,
               MAX(date) AS last_date
        FROM sales_fact_view
        WHERE tenant_id = :t AND store_id = :s AND item_id = :i
          AND date >= CURRENT_DATE - 84
    """), {"t": tenant_id, "s": store_id, "i": item_id})).mappings().fetchone()
    daily_avg = (float(base["units"]) / base["days"]) if base["days"] else 0.0
    baseline_units = int(round(daily_avg * horizon_days))
    sales_age = (date.today() - base["last_date"]).days if base["last_date"] else None

    inv = (await db.execute(text("""
        SELECT COALESCE(current_stock, 0) AS on_hand,
               COALESCE(available_stock, 0) AS available,
               COALESCE(reorder_point, 0) AS reorder_point
        FROM inventory WHERE store_id = :s AND item_id = :i
    """), {"s": store_id, "i": item_id})).mappings().fetchone() or {
        "on_hand": 0, "available": 0, "reorder_point": 0}
    safety_stock = campaign["safety_stock_units"]
    atp = max(0, int(inv["available"]) - safety_stock)

    # Incoming supply = open POs for this item (approved/sent, not received).
    incoming = int((await db.execute(text("""
        SELECT COALESCE(SUM(l.quantity), 0)
        FROM purchase_order_lines l JOIN purchase_orders p ON p.id = l.po_id
        WHERE p.tenant_id = :t AND l.item_id = :i
          AND p.status IN ('approved', 'sent', 'partially_received')
    """), {"t": tenant_id, "i": item_id})).scalar() or 0)

    # FEFO shelf-life: units in active batches expiring before campaign end.
    units_expiring = int((await db.execute(text("""
        SELECT COALESCE(SUM(quantity), 0) FROM inventory_batches
        WHERE store_id = :s AND item_id = :i AND status = 'active'
          AND expiry_date IS NOT NULL AND expiry_date <= :ends
    """), {"s": store_id, "i": item_id, "ends": ends})).scalar() or 0)

    supplier_terms = [dict(r) for r in (await db.execute(text("""
        SELECT s.name, ps.unit_cost, ps.moq, ps.lead_time_days
        FROM product_suppliers ps JOIN suppliers s ON s.id = ps.supplier_id
        WHERE ps.tenant_id = :t AND ps.item_id = :i
        ORDER BY ps.unit_cost ASC
    """), {"t": tenant_id, "i": item_id})).mappings().fetchall()]

    # Transfer surplus + in-stock substitute (both recommend-only).
    surplus = (await db.execute(text("""
        SELECT inv.store_id, st.name, inv.available_stock
        FROM inventory inv JOIN stores st ON st.id = inv.store_id
        WHERE inv.item_id = :i AND inv.store_id <> :s AND st.tenant_id = :t
          AND inv.available_stock - :ss > 0
        ORDER BY inv.available_stock DESC LIMIT 1
    """), {"i": item_id, "s": store_id, "t": tenant_id, "ss": safety_stock})).mappings().fetchone()
    transfer_surplus = ({"from_store": surplus["name"],
                         "units": int(surplus["available_stock"]) - safety_stock}
                        if surplus else None)
    sub = (await db.execute(text("""
        SELECT i.name, inv.available_stock
        FROM items i JOIN inventory inv ON inv.item_id = i.id AND inv.store_id = :s
        WHERE i.tenant_id = :t AND i.category = :cat AND i.id <> :i
          AND inv.available_stock - :ss > 0
        ORDER BY inv.available_stock DESC LIMIT 1
    """), {"s": store_id, "t": tenant_id, "cat": item["category"], "i": item_id,
           "ss": safety_stock})).mappings().fetchone()
    substitute = ({"name": sub["name"], "available": int(sub["available_stock"])} if sub else None)

    # Overlapping promotion on this store+item+window.
    overlap = int((await db.execute(text("""
        SELECT COUNT(*) FROM promotions pr
        LEFT JOIN promotion_items pi ON pi.promotion_id = pr.id
        LEFT JOIN promotion_stores psx ON psx.promotion_id = pr.id
        WHERE pr.tenant_id = :t AND pr.status IN ('active', 'scheduled')
          AND (pi.item_id = :i OR pi.item_id IS NULL)
          AND (psx.store_id = :s OR psx.store_id IS NULL)
          AND pr.start_date <= :ends AND pr.end_date >= :starts
    """), {"t": tenant_id, "i": item_id, "s": store_id,
           "starts": starts, "ends": ends})).scalar() or 0)

    # Audience summary from the built offers (churn, promo affinity, consent).
    aud = (await db.execute(text("""
        SELECT COUNT(*) FILTER (WHERE cohort = 'treatment') AS treatment,
               COUNT(*) FILTER (WHERE cohort = 'control') AS control,
               COUNT(*) AS total,
               COALESCE(AVG(churn_score), 0) AS avg_churn
        FROM campaign_offers WHERE campaign_id = :c AND tenant_id = :t
    """), {"c": campaign["id"], "t": tenant_id})).mappings().fetchone()
    consent = (await db.execute(text("""
        SELECT AVG(CASE WHEN consent_marketing THEN 1.0 ELSE 0.0 END) AS share
        FROM customers WHERE tenant_id = :t AND home_store_id = :s
    """), {"t": tenant_id, "s": store_id})).scalar()
    promo_rate = (await db.execute(text("""
        SELECT COALESCE(AVG(CASE WHEN was_promo THEN 1.0 ELSE 0.0 END), 0)
        FROM customer_purchases WHERE tenant_id = :t
    """), {"t": tenant_id})).scalar()

    # Operations capacity — simple rules baseline: flag if expected daily units
    # exceed a per-store handling ceiling.
    daily_expected = daily_avg * (1 + 0.22)
    capacity_flag = "ok" if daily_expected < 500 else "review_labour"

    return {
        "campaign_id": campaign["id"],
        "objective": campaign["objective"],
        "starts_on": starts, "ends_on": ends,
        "max_discount_pct": _d(campaign["max_discount_pct"]),
        "min_margin_pct": _d(campaign["min_margin_pct"]),
        "discount_budget": _d(campaign["discount_budget_aed"]),
        "control_pct": _d(campaign["control_pct"]),
        "safety_stock": safety_stock,
        "allow_procurement": True,
        "price": price, "unit_cost": cost,
        "item_name": item["name"], "category": item["category"],
        "baseline_units": baseline_units, "baseline_daily_avg": round(daily_avg, 2),
        "baseline_source": "trailing_84d_store_sku_mean",
        "sales_age_days": sales_age,
        "on_hand": int(inv["on_hand"]), "atp": atp, "incoming": incoming,
        "units_expiring_before_end": units_expiring,
        "supplier_terms": supplier_terms,
        "transfer_surplus": transfer_surplus, "substitute": substitute,
        "overlapping_promo": overlap > 0,
        "consent_share": float(consent or 0),
        "audience": {
            "audience_size": int(aud["total"]), "treatment": int(aud["treatment"]),
            "control": int(aud["control"]), "avg_churn": float(aud["avg_churn"]),
            "avg_promo_rate": float(promo_rate or 0),
            "consent_share": round(float(consent or 0), 3),
        },
        "operations": {"capacity_flag": capacity_flag,
                       "expected_daily_units": round(daily_expected, 1),
                       "reason_codes": ([] if capacity_flag == "ok" else ["labour_capacity_review"])},
        "input_snapshot": {
            "price_aed": str(price), "unit_cost_aed": str(cost) if cost is not None else None,
            "baseline_units": baseline_units, "atp": atp, "incoming": incoming,
            "units_expiring_before_end": units_expiring,
            "supplier_terms": [{"name": s["name"], "unit_cost": str(s["unit_cost"]),
                                "moq": s["moq"], "lead_time_days": s["lead_time_days"]}
                               for s in supplier_terms],
            "captured_at": datetime.now(timezone.utc).isoformat(),
        },
    }


async def run_scenario(db: AsyncSession, tenant_id: int, campaign: Dict,
                       actor: Optional[int], persist: bool = True) -> Dict:
    """Gather → build → (persist). The persist is the pack JSON only; no money,
    no stock, no PO. Reproducible from input_snapshot."""
    ctx = await gather_context(db, tenant_id, campaign)
    pack = build_scenario_pack(ctx)
    if persist:
        # Merge the pack UNDER simulation.scenario_pack (never clobber the whole
        # simulation object) so both this endpoint and simulate() expose it at the
        # same path the UI reads.
        await db.execute(text("""
            UPDATE retention_campaigns
            SET simulation = COALESCE(simulation, '{}'::jsonb)
                             || jsonb_build_object('scenario_pack', CAST(:sim AS jsonb)),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :id AND tenant_id = :t
        """), {"sim": json.dumps(pack, default=str), "id": campaign["id"], "t": tenant_id})
        try:
            await db.execute(text("""
                INSERT INTO retention_events
                    (tenant_id, event_type, entity_type, entity_id, actor_user_id, summary, metadata)
                VALUES (:t, 'scenario_built', 'campaign', :id, :actor, :summary, CAST(:meta AS jsonb))
            """), {"t": tenant_id, "id": campaign["id"], "actor": actor,
                   "summary": f"Scenario pack: {pack['recommendation']['decision']}",
                   "meta": json.dumps({"decision": pack["recommendation"]["decision"],
                                       "chosen": pack["recommendation"]["chosen"]})})
        except Exception as e:  # pragma: no cover
            logger.warning(f"scenario audit log failed: {e}")
    return pack
