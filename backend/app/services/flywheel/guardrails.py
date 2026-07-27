"""Stage 5 — automatic guardrails: auto-pause before damage, not after.

WHY AUTOMATIC. A budget breach discovered on Monday's report has already spent
the money. These checks run on every redemption and on a periodic sweep, and they
PAUSE the campaign — a reversible action with a recorded reason — rather than
cancel it. Pausing is safe to get wrong; cancelling is not.

WHAT WOULD BE WRONG: silently degrading (issuing weaker offers), or continuing
and alerting. If a hard limit is breached the correct behaviour is to stop
issuing offers and tell a human why, which is what `pause_reason` carries.

Every breach writes a campaign transition with `actor_kind='guardrail'`, so the
audit trail distinguishes "a person paused this" from "the system did".
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel import budget as budget_service, campaign_state, outbox
from app.services.flywheel.types import (
    ZERO, BudgetType, CampaignStatus, GuardrailBreach, money,
)

logger = logging.getLogger(__name__)

#: Pause when this share of the reserved discount exposure has been burned.
#: Below 1.0 deliberately: stopping AT the limit means the limit was reached.
BUDGET_BURN_PAUSE_RATIO = Decimal("0.95")

#: Redemption rate this many times the modelled expectation is an anomaly —
#: usually a leaked offer code or a pricing error, both of which cost money fast.
REDEMPTION_ANOMALY_MULTIPLE = Decimal("3.0")


async def check_campaign(
    db: AsyncSession, *, tenant_id: int, campaign_id: int,
    auto_pause: bool = True,
) -> Dict[str, Any]:
    """Run every guardrail against one campaign; pause on the first hard breach.

    Returns the full breach list even when pausing, so the operator sees
    everything that is wrong, not just whichever check ran first.
    """
    campaign = (await db.execute(
        text("""SELECT status, discount_budget_aed, min_margin_pct, safety_stock_pct,
                       starts_on, ends_on
                  FROM flywheel_campaigns WHERE id = :c AND tenant_id = :t"""),
        {"c": campaign_id, "t": tenant_id},
    )).fetchone()
    if not campaign:
        return {"checked": False, "detail": "Campaign not found"}

    status, discount_budget, min_margin, safety_pct, starts_on, ends_on = campaign
    if CampaignStatus(status) != CampaignStatus.ACTIVE:
        return {"checked": False, "status": status,
                "detail": "Guardrails only apply to ACTIVE campaigns"}

    breaches: List[Dict[str, Any]] = []

    # --- 1. budget burn ---------------------------------------------------
    exposure = await budget_service.campaign_exposure(
        db, tenant_id=tenant_id, campaign_id=campaign_id)
    reserved = money(exposure["reserved_aed"])
    spent = money(exposure["spent_aed"])
    if reserved > ZERO:
        burn_ratio = spent / reserved
        if burn_ratio >= BUDGET_BURN_PAUSE_RATIO:
            breaches.append({
                "breach": GuardrailBreach.BUDGET_EXHAUSTED.value,
                "severity": "hard",
                "detail": f"Spent {spent} of {reserved} AED reserved "
                          f"({burn_ratio:.0%} of the approved exposure)",
            })

    # Absolute cap: spend beyond the campaign's own declared budget.
    if money(discount_budget) > ZERO and spent > money(discount_budget):
        breaches.append({
            "breach": GuardrailBreach.PROJECTED_BUDGET_EXCEEDED.value,
            "severity": "hard",
            "detail": f"Spend {spent} AED exceeds the campaign budget of "
                      f"{money(discount_budget)} AED",
        })

    # --- 2. safety stock --------------------------------------------------
    # ONLY counts SKUs THIS CAMPAIGN DEPLETED (consumed_units > 0).
    #
    # Without that predicate the rule is self-contradictory and it fired in
    # practice: the shortage ladder deliberately places allocations on SKUs that
    # are ALREADY short (that is what makes them shortages), so a campaign
    # auto-paused itself the moment it went live, killing dozens of healthy
    # offers over one pre-existing low SKU it had not touched.
    #
    # A SKU that was already below safety at activation is not a campaign
    # failure and does not need a pause: available-to-promise returns 0 for it,
    # so the per-offer check already refuses to sell it. Pausing the WHOLE
    # campaign for that is disproportionate. The breach we actually care about
    # is depletion we CAUSED.
    low_stock = (await db.execute(
        text("""SELECT a.store_id, a.item_id, inv.current_stock,
                       inv.reorder_point, a.consumed_units
                  FROM flywheel_inventory_allocations a
                  JOIN inventory inv ON inv.store_id = a.store_id AND inv.item_id = a.item_id
                 WHERE a.tenant_id = :t AND a.campaign_id = :c AND a.status = 'soft'
                   AND a.consumed_units > 0
                   AND inv.current_stock <= COALESCE(inv.reorder_point, 0)"""),
        {"t": tenant_id, "c": campaign_id},
    )).fetchall()
    if low_stock:
        breaches.append({
            "breach": GuardrailBreach.SAFETY_STOCK_REACHED.value,
            "severity": "hard",
            "detail": f"{len(low_stock)} SKU(s) driven to or below safety stock "
                      f"by this campaign's own redemptions",
            "skus": [{"store_id": int(r[0]), "item_id": int(r[1]),
                      "on_hand": int(r[2]), "reorder_point": int(r[3] or 0),
                      "consumed_by_campaign": int(r[4])}
                     for r in low_stock[:10]],
        })

    # --- 3. realised margin ----------------------------------------------
    margin_row = (await db.execute(
        text("""SELECT COALESCE(SUM(margin_aed), 0), COALESCE(SUM(net_value_aed), 0),
                       COUNT(*)
                  FROM flywheel_redemptions
                 WHERE tenant_id = :t AND campaign_id = :c"""),
        {"t": tenant_id, "c": campaign_id},
    )).fetchone()
    total_margin, total_net, redemption_count = (money(margin_row[0]),
                                                 money(margin_row[1]),
                                                 int(margin_row[2]))
    if total_net > ZERO:
        realised_margin_pct = (total_margin / total_net) * Decimal("100")
        if realised_margin_pct < money(min_margin):
            breaches.append({
                "breach": GuardrailBreach.MARGIN_BELOW_FLOOR.value,
                "severity": "hard",
                "detail": f"Realised margin {realised_margin_pct:.1f}% is below the "
                          f"{money(min_margin)}% floor across {redemption_count} redemptions",
            })

    # --- 4. redemption anomaly -------------------------------------------
    expectation = (await db.execute(
        text("""SELECT COALESCE(SUM(redemption_probability), 0), COUNT(*)
                  FROM flywheel_decisions
                 WHERE tenant_id = :t AND campaign_id = :c
                   AND action_type <> 'NO_ACTION'"""),
        {"t": tenant_id, "c": campaign_id},
    )).fetchone()
    expected_redemptions = Decimal(str(expectation[0] or 0))
    if expected_redemptions >= 5 and Decimal(redemption_count) > (
            expected_redemptions * REDEMPTION_ANOMALY_MULTIPLE):
        breaches.append({
            "breach": GuardrailBreach.REDEMPTION_ANOMALY.value,
            "severity": "hard",
            "detail": f"{redemption_count} redemptions against an expected "
                      f"{expected_redemptions:.1f} — possible leaked offer code",
        })

    # --- 5. expired approval ---------------------------------------------
    expired = (await db.execute(
        text("""SELECT COUNT(*) FROM flywheel_approval_requests
                 WHERE tenant_id = :t AND campaign_id = :c AND status = 'expired'"""),
        {"t": tenant_id, "c": campaign_id},
    )).scalar() or 0
    if int(expired):
        breaches.append({
            "breach": GuardrailBreach.APPROVAL_EXPIRED.value, "severity": "hard",
            "detail": "The campaign's approval has expired and must be re-sought",
        })

    hard_breaches = [b for b in breaches if b["severity"] == "hard"]
    paused = False

    if hard_breaches and auto_pause:
        reason = "; ".join(b["detail"] for b in hard_breaches[:3])
        await campaign_state.transition(
            db, tenant_id=tenant_id, campaign_id=campaign_id,
            target=CampaignStatus.PAUSED, actor_kind="guardrail",
            reason=f"Auto-paused: {reason}", pause_reason=f"Auto-paused: {reason}")
        await outbox.emit(
            db, tenant_id=tenant_id, channel=outbox.CHANNEL_CAMPAIGN,
            event_type="campaign.auto_paused",
            payload={"campaign_id": campaign_id,
                     "breaches": [b["breach"] for b in hard_breaches],
                     "reason": reason},
            campaign_id=campaign_id)
        paused = True
        logger.warning("flywheel.guardrail auto-paused campaign=%s breaches=%s",
                       campaign_id, [b["breach"] for b in hard_breaches])

    return {
        "checked": True, "campaign_id": campaign_id,
        "breaches": breaches, "hard_breaches": len(hard_breaches),
        "auto_paused": paused,
        "exposure": exposure,
        "detail": "All guardrails clear" if not breaches
                  else f"{len(hard_breaches)} hard breach(es) detected",
    }


async def sweep(db: AsyncSession, *, tenant_id: Optional[int] = None) -> Dict[str, Any]:
    """Check every ACTIVE campaign. Run periodically from the app lifespan."""
    clause = "AND tenant_id = :t" if tenant_id else ""
    params = {"t": tenant_id} if tenant_id else {}
    rows = (await db.execute(
        text(f"""SELECT id, tenant_id FROM flywheel_campaigns
                  WHERE status = 'ACTIVE' {clause}"""),
        params,
    )).fetchall()

    paused, checked = 0, 0
    for campaign_id, campaign_tenant in rows:
        try:
            result = await check_campaign(
                db, tenant_id=int(campaign_tenant), campaign_id=int(campaign_id))
            checked += 1
            if result.get("auto_paused"):
                paused += 1
        except Exception as exc:
            # One bad campaign must not stop the sweep for every other tenant.
            logger.warning("flywheel.guardrail sweep failed campaign=%s (%s)",
                           campaign_id, exc)
    return {"checked": checked, "auto_paused": paused}
