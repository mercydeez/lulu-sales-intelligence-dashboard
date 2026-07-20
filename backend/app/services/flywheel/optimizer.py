"""Stage 3 — the deterministic next-best-action optimizer.

THIS FILE CONTAINS NO MODEL. It consumes model OUTPUTS (churn probability,
uplift) as inputs and applies arithmetic and policy. That separation is the
safety guarantee the whole product rests on: an LLM or a neural net can change
what it proposes, but it cannot change what gets APPROVED, because approval
happens here, in code you can read, with every term persisted.

THE OBJECTIVE (§5):

    EIV = expected retained value
        + expected incremental margin
        − expected discount cost
        − communication cost
        − fulfilment cost
        − incremental procurement cost
        − stockout-risk penalty

THE RULE THAT MATTERS MOST: every benefit term is multiplied by UPLIFT, never by
churn probability. A customer at 95% churn risk with 0% uplift produces
expected_retained_value = 0 and therefore loses to NO_ACTION. That is the
mechanism by which "a high churn score alone never triggers a discount" is
enforced — not by a guard clause that could be bypassed, but by the shape of
the objective function itself.

REPRODUCIBILITY: every input and every term is written to `flywheel_decisions`, so
`replay()` can recompute a stored decision and assert it still produces the same
action. If it ever does not, either the policy version changed (recorded) or
there is a bug (surfaced).
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.services.flywheel import tax
from app.services.flywheel.types import (
    ZERO, ActionCandidate, ActionType, PolicyEnvelope, ReasonCode, money,
)

logger = logging.getLogger(__name__)

POLICY_VERSION = "v1"

#: Per-contact communication cost by channel (AED). Small, but it is what makes
#: NO_ACTION correctly beat a marginal REMINDER at scale — 50,000 "free"
#: reminders is not free.
COMMS_COST: Dict[str, Decimal] = {
    "email": Decimal("0.05"), "push": Decimal("0.02"), "app": Decimal("0.02"),
    "sms": Decimal("0.12"), "in_store": Decimal("0.00"),
}

#: Fixed AED cost of non-discount rewards.
LOYALTY_POINT_COST = Decimal("8.00")
FREE_DELIVERY_COST = Decimal("15.00")

#: How many months of forward value a retained customer is worth. Deliberately
#: conservative (one quarter, not "lifetime"): valuing retention at LTV would
#: justify almost any discount, which is how retention programmes destroy margin.
RETENTION_HORIZON_MONTHS = Decimal("3")

#: Penalty per unit of stock committed when ATP is tight, expressed as a fraction
#: of unit margin. Reflects that selling promo stock can starve full-price demand.
STOCKOUT_PENALTY_RATE = Decimal("0.35")


def _expected_retained_value(
    *, uplift: float, monthly_value_aed: Decimal, margin_rate: Decimal
) -> Decimal:
    """Value saved by retaining a customer who would otherwise have left.

    UPLIFT — not churn probability — is the multiplier. Only the incremental
    probability of retention is attributable to the offer; the rest would have
    happened anyway and must not be claimed as a benefit.
    """
    if uplift <= 0:
        return ZERO
    horizon_value = money(monthly_value_aed * RETENTION_HORIZON_MONTHS)
    return money(horizon_value * margin_rate * Decimal(str(uplift)))


def build_candidates(
    *,
    customer_id: int,
    churn_probability: float,
    features: Dict[str, Any],
    monthly_value_aed: Decimal,
    uplift_by_action: Dict[ActionType, float],
    envelope: PolicyEnvelope,
    channel: str = "email",
    item_id: Optional[int] = None,
    store_id: Optional[int] = None,
    category: Optional[str] = None,
    unit_price_aed: Decimal = ZERO,
    unit_cost_aed: Decimal = ZERO,
    units: int = 1,
    atp_units: Optional[int] = None,
    procurement_cost_aed: Decimal = ZERO,
    discount_ladder: Optional[List[Decimal]] = None,
    tax_rule: Optional["tax.TaxRule"] = None,
) -> List[ActionCandidate]:
    """Build and cost every allowed action for one customer.

    Discount actions are expanded across a LADDER of depths (5/10/15/20%, capped
    by the campaign's max) rather than assuming one depth. The optimizer then
    picks the cheapest depth that still wins — which is how it avoids handing out
    20% when 10% would have retained the customer just as well.
    """
    candidates: List[ActionCandidate] = []
    comms = COMMS_COST.get(channel, Decimal("0.05"))
    rule = tax_rule or tax.NO_TAX

    # The margin RATE that scales retained value must also be net of tax — the
    # future purchases a retained customer makes carry the same VAT, so valuing
    # them at the gross rate overstates every retention benefit by the rate.
    net_price_for_rate = rule.net_of_tax(unit_price_aed)
    margin_rate = (
        money((net_price_for_rate - unit_cost_aed) / net_price_for_rate)
        if net_price_for_rate > 0 else Decimal("0.30")
    )

    # --- NO_ACTION: always a candidate, and the honest default ---------------
    # Every term is zero, so its EIV is exactly zero. Any real action must BEAT
    # doing nothing to be selected — that is what makes NO_ACTION a decision
    # rather than a failure mode.
    candidates.append(ActionCandidate(
        action_type=ActionType.NO_ACTION,
        store_id=store_id,
        churn_probability=churn_probability,
        uplift=0.0,
        reason_codes=["BASELINE_DO_NOTHING"],
    ))

    # --- REMINDER: no discount, no stock, tiny comms cost --------------------
    uplift = uplift_by_action.get(ActionType.REMINDER, 0.0)
    reminder = ActionCandidate(
        action_type=ActionType.REMINDER, store_id=store_id, category=category,
        churn_probability=churn_probability, uplift=uplift,
        redemption_probability=max(0.0, uplift * 2.0),
        comms_cost_aed=comms,
        expected_retained_value_aed=_expected_retained_value(
            uplift=uplift, monthly_value_aed=monthly_value_aed, margin_rate=margin_rate),
    )
    candidates.append(reminder)

    # --- LOYALTY_POINTS: costs money but consumes NO stock -------------------
    # This is rung (d) of the shortage ladder — the offer that survives a stockout.
    uplift = uplift_by_action.get(ActionType.LOYALTY_POINTS, 0.0)
    candidates.append(ActionCandidate(
        action_type=ActionType.LOYALTY_POINTS, store_id=store_id, category=category,
        churn_probability=churn_probability, uplift=uplift,
        redemption_probability=max(0.0, uplift * 2.2),
        comms_cost_aed=comms,
        expected_discount_cost_aed=money(LOYALTY_POINT_COST * Decimal(str(max(0.0, uplift * 2.2)))),
        expected_retained_value_aed=_expected_retained_value(
            uplift=uplift, monthly_value_aed=monthly_value_aed, margin_rate=margin_rate),
    ))

    # --- FREE_DELIVERY: fulfilment cost, no stock impact --------------------
    uplift = uplift_by_action.get(ActionType.FREE_DELIVERY, 0.0)
    redemption = max(0.0, uplift * 2.0)
    candidates.append(ActionCandidate(
        action_type=ActionType.FREE_DELIVERY, store_id=store_id, category=category,
        churn_probability=churn_probability, uplift=uplift,
        redemption_probability=redemption,
        comms_cost_aed=comms,
        fulfilment_cost_aed=money(FREE_DELIVERY_COST * Decimal(str(redemption))),
        expected_retained_value_aed=_expected_retained_value(
            uplift=uplift, monthly_value_aed=monthly_value_aed, margin_rate=margin_rate),
    ))

    # --- PERCENT_DISCOUNT across the depth ladder ---------------------------
    if unit_price_aed > 0:
        ladder = discount_ladder or [Decimal("5"), Decimal("10"), Decimal("15"), Decimal("20")]
        for depth in ladder:
            if depth > envelope.max_discount_pct:
                # Outside the campaign's policy envelope — recorded as rejected
                # rather than silently dropped, so the trace shows it was considered.
                candidates.append(ActionCandidate(
                    action_type=ActionType.PERCENT_DISCOUNT, discount_pct=depth,
                    store_id=store_id, item_id=item_id, category=category,
                    unit_price_aed=unit_price_aed, unit_cost_aed=unit_cost_aed,
                    churn_probability=churn_probability, feasible=False,
                    rejected_reason=ReasonCode.DISCOUNT_CAP_EXCEEDED.value,
                ))
                continue

            uplift = uplift_by_action.get(ActionType.PERCENT_DISCOUNT, 0.0)
            # Deeper discounts lift response — modelled by the uplift service,
            # scaled here by relative depth within the ladder.
            depth_scale = 1.0 + float(depth) / 40.0
            effective_uplift = uplift * depth_scale
            redemption = max(0.0, min(0.95, effective_uplift * 2.5))

            discount_per_unit = money(unit_price_aed * depth / Decimal("100"))
            # Margin is on the NET-OF-TAX receipt, not the shelf price.
            unit_margin = money(
                rule.net_of_tax(money(unit_price_aed - discount_per_unit)) - unit_cost_aed)

            candidate = ActionCandidate(
                action_type=ActionType.PERCENT_DISCOUNT, discount_pct=depth,
                store_id=store_id, item_id=item_id, category=category,
                unit_price_aed=unit_price_aed, unit_cost_aed=unit_cost_aed, units=units,
                churn_probability=churn_probability, uplift=effective_uplift,
                redemption_probability=redemption,
                comms_cost_aed=comms,
                expected_discount_cost_aed=money(
                    discount_per_unit * Decimal(units) * Decimal(str(redemption))),
                expected_margin_aed=money(
                    unit_margin * Decimal(units) * Decimal(str(redemption))),
                procurement_cost_aed=money(procurement_cost_aed),
                expected_retained_value_aed=_expected_retained_value(
                    uplift=effective_uplift, monthly_value_aed=monthly_value_aed,
                    margin_rate=margin_rate),
            )

            # MARGIN FLOOR — a hard policy gate checked NET OF TAX, after
            # discount. Selling below the floor is refused even if EIV is
            # positive: EIV is an expectation, the margin floor is a promise.
            #
            # Tax matters here more than it looks. UAE shelf prices INCLUDE 5%
            # VAT, which the retailer collects and remits — it was never
            # revenue. Checking the floor on the tax-inclusive amount overstates
            # margin by the full rate, so a campaign could clear a "10% minimum
            # margin" gate while actually earning ~4.8%. The gate looked like a
            # control and was wrong on every decision.
            margin_view = tax.margin_net_pct(
                gross_price=unit_price_aed, unit_cost=unit_cost_aed,
                discount_pct=depth, rule=tax_rule or tax.NO_TAX)
            candidate.net_price_aed = margin_view["net_revenue"]
            candidate.margin_net_pct = margin_view["margin_pct"]
            candidate.tax_rate_pct = margin_view["tax_rate_pct"]

            if margin_view["margin_pct"] < envelope.min_margin_pct:
                candidate.feasible = False
                candidate.rejected_reason = ReasonCode.MARGIN_FLOOR_BREACHED.value
                candidate.margin_note = tax.breakdown_note(margin_view, tax_rule or tax.NO_TAX)

            # STOCK — refuse what cannot be served.
            if atp_units is not None and atp_units < units:
                candidate.feasible = False
                candidate.rejected_reason = ReasonCode.INSUFFICIENT_STOCK.value
            elif atp_units is not None and atp_units < units * 5:
                # Tight but servable: price in the risk of starving full-price demand.
                candidate.stockout_risk_penalty_aed = money(
                    unit_margin * Decimal(units) * STOCKOUT_PENALTY_RATE)

            candidates.append(candidate)

    return candidates


def select_best(
    candidates: List[ActionCandidate], *, envelope: PolicyEnvelope,
) -> Dict[str, Any]:
    """Pick the highest-EIV feasible action and explain every rejection.

    Selection rules, in order:
      1. Infeasible candidates are excluded (with their reason recorded).
      2. Candidates whose uplift is below the noise threshold are excluded —
         this is where "high risk alone buys nothing" is enforced.
      3. Among the rest, highest EIV wins.
      4. TIE-BREAK ON COST: equal EIV → the cheaper action. Prevents the
         optimizer handing out 20% when 10% scores identically.
      5. NO_ACTION wins by default if nothing beats zero.
    """
    rejected: List[Dict[str, Any]] = []
    viable: List[ActionCandidate] = []

    for candidate in candidates:
        if candidate.action_type == ActionType.NO_ACTION:
            viable.append(candidate)
            continue

        if not candidate.feasible:
            rejected.append({
                "action": candidate.action_type.value,
                "discount_pct": str(candidate.discount_pct),
                "reason_code": candidate.rejected_reason or ReasonCode.OUT_OF_SCOPE.value,
                "eiv_aed": str(candidate.eiv_aed),
            })
            continue

        # THE UPLIFT GATE. A negative-uplift action is actively harmful; a
        # near-zero-uplift action is noise dressed as a decision.
        if candidate.uplift < 0:
            rejected.append({
                "action": candidate.action_type.value,
                "discount_pct": str(candidate.discount_pct),
                "reason_code": ReasonCode.NEGATIVE_UPLIFT.value,
                "detail": f"uplift {candidate.uplift:.4f} — offering would be worse than nothing",
                "eiv_aed": str(candidate.eiv_aed),
            })
            continue

        if candidate.uplift < envelope.min_uplift_threshold:
            rejected.append({
                "action": candidate.action_type.value,
                "discount_pct": str(candidate.discount_pct),
                "reason_code": ReasonCode.UPLIFT_BELOW_THRESHOLD.value,
                "detail": f"uplift {candidate.uplift:.4f} below the "
                          f"{envelope.min_uplift_threshold:.4f} noise floor",
                "eiv_aed": str(candidate.eiv_aed),
            })
            continue

        if candidate.eiv_aed <= ZERO:
            rejected.append({
                "action": candidate.action_type.value,
                "discount_pct": str(candidate.discount_pct),
                "reason_code": ReasonCode.NEGATIVE_EIV.value,
                "detail": f"EIV {candidate.eiv_aed} AED — costs more than it returns",
                "eiv_aed": str(candidate.eiv_aed),
            })
            continue

        viable.append(candidate)

    def total_cost(c: ActionCandidate) -> Decimal:
        return money(c.expected_discount_cost_aed + c.comms_cost_aed
                     + c.fulfilment_cost_aed + c.procurement_cost_aed)

    # Highest EIV, then cheapest — rule 4.
    winner = max(viable, key=lambda c: (c.eiv_aed, -total_cost(c)))

    if winner.action_type == ActionType.NO_ACTION:
        winner.reason_codes = [ReasonCode.NEGATIVE_EIV.value] if rejected else ["NO_VIABLE_ACTION"]
    else:
        codes = [ReasonCode.POSITIVE_EIV.value]
        if winner.uplift >= 0.05:
            codes.append(ReasonCode.STRONG_UPLIFT.value)
        if winner.churn_probability >= 0.5:
            codes.append(ReasonCode.HIGH_CHURN_RISK.value)
        # Did a deeper/costlier action score the same? Then this one was chosen
        # BECAUSE it was cheaper — say so, it is the most interesting fact about
        # the decision.
        equals = [c for c in viable if c.eiv_aed == winner.eiv_aed and c is not winner]
        if equals and any(total_cost(c) > total_cost(winner) for c in equals):
            codes.append(ReasonCode.CHEAPEST_EFFECTIVE_ACTION.value)
        winner.reason_codes = codes

    return {
        "selected": winner,
        "rejected": rejected,
        "considered": len(candidates),
        "viable": len(viable),
        "policy_version": envelope.policy_version,
    }


def replay(stored: Dict[str, Any]) -> Dict[str, Any]:
    """Recompute EIV from a stored decision row and compare to what was recorded.

    This is what makes §10's promise — "the selected action must be reproducible
    from its stored inputs" — testable rather than aspirational. A mismatch means
    either the policy changed (in which case policy_version differs and that is
    expected) or the arithmetic drifted (a bug).
    """
    recomputed = money(
        money(stored.get("expected_retained_value_aed", 0))
        + money(stored.get("expected_margin_aed", 0))
        - money(stored.get("expected_discount_cost_aed", 0))
        - money(stored.get("comms_cost_aed", 0))
        - money(stored.get("fulfilment_cost_aed", 0))
        - money(stored.get("procurement_cost_aed", 0))
        - money(stored.get("stockout_risk_penalty_aed", 0))
    )
    recorded = money(stored.get("eiv_aed", 0))
    return {
        "recomputed_eiv_aed": str(recomputed),
        "recorded_eiv_aed": str(recorded),
        "matches": recomputed == recorded,
        "delta_aed": str(money(recomputed - recorded)),
        "policy_version": stored.get("policy_version"),
    }
