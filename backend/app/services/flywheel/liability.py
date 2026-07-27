"""Offer liability, breakage, and returns claw-back.

THREE THINGS v1 GOT WRONG, all of them the same mistake in different clothes:
treating a moment as final when it is provisional.

1. AN ISSUED OFFER IS A LIABILITY, NOT A NON-EVENT.
   v1 recorded nothing when an offer went out. But the customer may redeem it,
   so the business is exposed from the moment of issue. A CFO needs to see
   committed-but-unspent exposure — that is the difference between "we have
   spent 60k" and "we have spent 60k and are on the hook for another 200k".

2. AN EXPIRED OFFER PRODUCES BREAKAGE, WHICH IS NOT A SAVING.
   The unredeemed remainder is real and reportable, and it is the single
   easiest number in loyalty accounting to double-count: once as released
   budget (headroom returning to the pool) and again as a "saving" credited to
   the campaign. It is neither spend nor profit — it is liability that expired.
   Recorded once, under its own ledger type, and never added to margin.

3. A REDEMPTION IS REVERSIBLE.
   If the item comes back, the discount was not earned and the margin was not
   made. Both must be clawed back with COMPENSATING entries — never by editing
   the original rows. An editable ledger is not a ledger; the whole point is
   that history is append-only and the correction is itself auditable.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel import budget as budget_service, outbox
from app.services.flywheel.types import ZERO, BudgetType, LedgerEntry, money

logger = logging.getLogger(__name__)


async def record_liability(
    db: AsyncSession, *, tenant_id: int, offer_id: int, amount: Decimal,
) -> None:
    """Stamp the exposure an offer creates at issue time.

    Deliberately NOT a budget ledger entry: the reservation already happened at
    campaign activation, and writing a second RESERVED row per offer would
    double-count the same exposure. This records liability at the OFFER grain
    so breakage can be computed per offer later.
    """
    await db.execute(
        text("UPDATE flywheel_offers SET liability_aed = :a WHERE id = :o AND tenant_id = :t"),
        {"a": money(amount), "o": offer_id, "t": tenant_id},
    )


async def expire_and_record_breakage(
    db: AsyncSession, *, tenant_id: int, campaign_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Expire lapsed offers, release their reservation, and record breakage.

    Returns the breakage figure and rate. Called by the nightly sweep and at
    campaign completion.
    """
    clause = "AND campaign_id = :c" if campaign_id else ""
    params: Dict[str, Any] = {"t": tenant_id}
    if campaign_id:
        params["c"] = campaign_id

    expired = (await db.execute(
        text(f"""UPDATE flywheel_offers
                    SET status = 'expired',
                        liability_released = TRUE,
                        -- The whole liability broke: it was never redeemed.
                        breakage_aed = liability_aed
                  WHERE tenant_id = :t
                    AND status = 'issued'
                    AND expires_at < now()
                    AND liability_released = FALSE
                    {clause}
                  RETURNING id, campaign_id, liability_aed"""),
        params,
    )).fetchall()

    if not expired:
        return {"expired": 0, "breakage_aed": "0.00", "released_aed": "0.00"}

    by_campaign: Dict[int, Decimal] = {}
    for _oid, camp, liability in expired:
        by_campaign[int(camp)] = money(by_campaign.get(int(camp), ZERO) + money(liability))

    total_breakage = money(sum(by_campaign.values()))

    budget_id = await budget_service.active_budget_id(
        db, tenant_id=tenant_id, budget_type=BudgetType.DISCOUNT)

    released_total = ZERO
    if budget_id:
        for camp_id, amount in by_campaign.items():
            if amount <= ZERO:
                continue
            # Two DISTINCT facts, recorded separately on purpose:
            #  * RELEASED — headroom genuinely returns to the pool and can fund
            #    another campaign;
            #  * BREAKAGE — a reporting fact about what was promised and never
            #    taken. Collapsing them into one entry is exactly how breakage
            #    gets counted twice.
            result = await budget_service.release(
                db, tenant_id=tenant_id, budget_id=budget_id, amount=amount,
                campaign_id=camp_id, source_type="offer_expiry_breakage",
                reason=f"{len(expired)} offer(s) expired unredeemed")
            if result.get("applied"):
                released_total = money(released_total + money(result["released"]))

            await _write_breakage_entry(
                db, tenant_id=tenant_id, budget_id=budget_id,
                campaign_id=camp_id, amount=amount)

        await db.execute(
            text("""UPDATE flywheel_budgets SET breakage_aed = breakage_aed + :b
                     WHERE id = :id AND tenant_id = :t"""),
            {"b": total_breakage, "id": budget_id, "t": tenant_id},
        )

    logger.info("flywheel.breakage tenant=%s expired=%s breakage=%s",
                tenant_id, len(expired), total_breakage)
    return {
        "expired": len(expired),
        "breakage_aed": str(total_breakage),
        "released_aed": str(released_total),
        "note": "Breakage is liability that expired unredeemed. It is neither "
                "spend nor saving and is never added to margin.",
    }


async def _write_breakage_entry(
    db: AsyncSession, *, tenant_id: int, budget_id: int, campaign_id: int,
    amount: Decimal,
) -> None:
    """A zero-balance-delta ledger row: breakage is a MEMO, not a movement.

    balance_before == balance_after because the money already moved via the
    RELEASED entry. Recording it as a movement would inflate the budget.
    """
    balance = money((await db.execute(
        text("SELECT reserved_aed FROM flywheel_budgets WHERE id = :b"),
        {"b": budget_id},
    )).scalar() or 0)

    await db.execute(
        text("""INSERT INTO flywheel_budget_ledger
                   (tenant_id, budget_id, campaign_id, entry_type, amount_aed,
                    source_type, balance_before, balance_after, reason)
                VALUES (:t, :b, :c, 'BREAKAGE', :amt, 'offer_expiry',
                        :bal, :bal, :reason)"""),
        {"t": tenant_id, "b": budget_id, "c": campaign_id, "amt": money(amount),
         "bal": balance,
         "reason": "Memo: offers expired unredeemed. Balance unchanged — the "
                   "money returned to the pool via the RELEASED entry."},
    )


async def process_return(
    db: AsyncSession, *, tenant_id: int, redemption_id: int, units_returned: int,
    idempotency_key: str, reason: Optional[str] = None, restock: bool = True,
    actor_user_id: Optional[int] = None, request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Claw back discount spend and credited margin when goods come back.

    ONE TRANSACTION, and idempotent on the same key as redemption — a retried
    return must not claw back twice. Everything is a COMPENSATING entry; the
    original redemption row is never edited.
    """
    existing = (await db.execute(
        text("""SELECT id, units_returned, discount_clawed_back_aed
                  FROM flywheel_returns
                 WHERE tenant_id = :t AND idempotency_key = :k"""),
        {"t": tenant_id, "k": idempotency_key},
    )).fetchone()
    if existing:
        return {"return_id": int(existing[0]), "replayed": True, "applied": False,
                "units_returned": int(existing[1]),
                "discount_clawed_back_aed": str(money(existing[2])),
                "detail": "Idempotent replay — nothing was clawed back twice"}

    redemption = (await db.execute(
        text("""SELECT campaign_id, customer_id, store_id, item_id, units,
                       gross_value_aed, discount_aed, net_value_aed, margin_aed
                  FROM flywheel_redemptions
                 WHERE id = :r AND tenant_id = :t
                 FOR UPDATE"""),
        {"r": redemption_id, "t": tenant_id},
    )).fetchone()
    if not redemption:
        raise ValueError(f"Redemption {redemption_id} not found")

    (campaign_id, customer_id, store_id, item_id, units,
     gross, discount, net, margin) = redemption

    already = int((await db.execute(
        text("""SELECT COALESCE(SUM(units_returned), 0) FROM flywheel_returns
                 WHERE tenant_id = :t AND redemption_id = :r"""),
        {"t": tenant_id, "r": redemption_id},
    )).scalar() or 0)

    if already + units_returned > int(units):
        raise ValueError(
            f"Cannot return {units_returned} units: only {int(units) - already} "
            f"of the original {int(units)} remain unreturned")

    # Pro-rata: return 1 of 3 units and exactly a third of the discount and
    # margin is reversed. Reversing the whole discount on a partial return is
    # a common and expensive error.
    share = Decimal(units_returned) / Decimal(int(units))
    discount_back = money(money(discount) * share)
    margin_back = money(money(margin) * share)
    refund = money(money(net) * share)

    row = (await db.execute(
        text("""INSERT INTO flywheel_returns
                   (tenant_id, redemption_id, campaign_id, customer_id,
                    units_returned, refund_aed, discount_clawed_back_aed,
                    margin_clawed_back_aed, restocked, reason,
                    idempotency_key, request_id)
                VALUES (:t, :r, :c, :cust, :u, :refund, :disc, :margin,
                        :restock, :reason, :key, :rid)
                RETURNING id"""),
        {"t": tenant_id, "r": redemption_id, "c": campaign_id, "cust": customer_id,
         "u": units_returned, "refund": refund, "disc": discount_back,
         "margin": margin_back, "restock": restock, "reason": reason,
         "key": idempotency_key, "rid": request_id},
    )).fetchone()
    return_id = int(row[0])

    # --- put the stock back ------------------------------------------------
    if restock and store_id and item_id:
        inv = (await db.execute(
            text("""SELECT id, current_stock FROM inventory
                     WHERE store_id = :s AND item_id = :i FOR UPDATE"""),
            {"s": store_id, "i": item_id},
        )).fetchone()
        if inv:
            inv_id, on_hand = int(inv[0]), int(inv[1])
            await db.execute(
                text("""UPDATE inventory
                           SET current_stock = current_stock + :u, updated_at = now()
                         WHERE id = :id"""),
                {"u": units_returned, "id": inv_id},
            )
            await db.execute(
                text("""INSERT INTO inventory_transactions
                           (inventory_id, store_id, item_id, transaction_type, quantity,
                            stock_before, stock_after, reference_type, reference_id,
                            notes, performed_by)
                        VALUES (:inv, :s, :i, 'return', :q, :before, :after,
                                'flywheel_return', :ref, :notes, :actor)"""),
                {"inv": inv_id, "s": store_id, "i": item_id, "q": units_returned,
                 "before": on_hand, "after": on_hand + units_returned,
                 "ref": str(return_id),
                 "notes": f"Flywheel return against redemption {redemption_id}",
                 "actor": actor_user_id},
            )

    # --- claw the discount back off the budget -----------------------------
    budget_id = await budget_service.active_budget_id(
        db, tenant_id=tenant_id, budget_type=BudgetType.DISCOUNT)
    clawed: Dict[str, Any] = {"applied": False}
    if budget_id and discount_back > ZERO:
        clawed = await _claw_back(
            db, tenant_id=tenant_id, budget_id=budget_id, amount=discount_back,
            campaign_id=int(campaign_id), source_id=str(return_id),
            actor_user_id=actor_user_id, request_id=request_id,
            idempotency_key=f"clawback:{idempotency_key}")

    # The customer event keeps the loop honest: a return is behaviour, and the
    # next feature snapshot must see it (it raises return_ratio, which raises
    # churn risk and lowers uplift — exactly right for someone who sends
    # things back).
    await db.execute(
        text("""INSERT INTO flywheel_customer_events
                   (tenant_id, customer_id, event_type, occurred_at, store_id,
                    item_id, quantity_units, value_aed, margin_aed, metadata)
                VALUES (:t, :c, 'return', now(), :s, :i, :u, :v, :m,
                        CAST(:meta AS JSONB))"""),
        {"t": tenant_id, "c": customer_id, "s": store_id, "i": item_id,
         "u": units_returned, "v": refund, "m": -margin_back,
         "meta": f'{{"return_id": {return_id}, "redemption_id": {redemption_id}}}'},
    )

    await outbox.emit(
        db, tenant_id=tenant_id, channel=outbox.CHANNEL_BUDGET,
        event_type="redemption.returned",
        payload={"return_id": return_id, "redemption_id": redemption_id,
                 "units": units_returned, "discount_clawed_back": str(discount_back),
                 "margin_clawed_back": str(margin_back)},
        store_id=store_id, campaign_id=int(campaign_id))

    logger.info("flywheel.return id=%s units=%s discount_back=%s margin_back=%s",
                return_id, units_returned, discount_back, margin_back)
    return {
        "return_id": return_id, "replayed": False, "applied": True,
        "units_returned": units_returned,
        "refund_aed": str(refund),
        "discount_clawed_back_aed": str(discount_back),
        "margin_clawed_back_aed": str(margin_back),
        "restocked": restock,
        "budget": clawed,
        "note": "Compensating entries only — the original redemption row is "
                "unchanged, so the correction is itself auditable.",
    }


async def _claw_back(
    db: AsyncSession, *, tenant_id: int, budget_id: int, amount: Decimal,
    campaign_id: int, source_id: str, actor_user_id: Optional[int],
    request_id: Optional[str], idempotency_key: str,
) -> Dict[str, Any]:
    """Reverse spend. Reduces `spent_aed` and records a CLAWED_BACK entry.

    Clamped at the amount actually spent so a claw-back can never drive spend
    negative — which would silently manufacture budget.
    """
    row = (await db.execute(
        text("""SELECT spent_aed, clawed_back_aed FROM flywheel_budgets
                 WHERE id = :b AND tenant_id = :t FOR UPDATE"""),
        {"b": budget_id, "t": tenant_id},
    )).fetchone()
    if not row:
        return {"applied": False, "reason": "budget_not_found"}

    spent, clawed = money(row[0]), money(row[1])
    amount = min(money(amount), spent)
    if amount <= ZERO:
        return {"applied": False, "reason": "nothing_to_claw_back"}

    new_spent = money(spent - amount)
    await db.execute(
        text("""UPDATE flywheel_budgets
                   SET spent_aed = :s, clawed_back_aed = :c, updated_at = now()
                 WHERE id = :b AND tenant_id = :t"""),
        {"s": new_spent, "c": money(clawed + amount), "b": budget_id, "t": tenant_id},
    )
    try:
        await db.execute(
            text("""INSERT INTO flywheel_budget_ledger
                       (tenant_id, budget_id, campaign_id, entry_type, amount_aed,
                        source_type, source_id, balance_before, balance_after,
                        actor_user_id, request_id, idempotency_key, reason)
                    VALUES (:t, :b, :c, 'CLAWED_BACK', :amt, 'return', :sid,
                            :before, :after, :actor, :rid, :idem, :reason)"""),
            {"t": tenant_id, "b": budget_id, "c": campaign_id, "amt": amount,
             "sid": source_id, "before": spent, "after": new_spent,
             "actor": actor_user_id, "rid": request_id, "idem": idempotency_key,
             "reason": f"Discount reversed — goods returned (return {source_id})"},
        )
    except IntegrityError:
        raise ValueError("This claw-back has already been applied")

    return {"applied": True, "clawed_back": str(amount), "spent_after": str(new_spent)}


async def campaign_liability(
    db: AsyncSession, *, tenant_id: int, campaign_id: int
) -> Dict[str, str]:
    """Outstanding liability, breakage and claw-backs — the CFO's exposure view."""
    row = (await db.execute(
        text("""SELECT
                  COALESCE(SUM(liability_aed) FILTER (WHERE status = 'issued'), 0),
                  COALESCE(SUM(breakage_aed), 0),
                  COUNT(*) FILTER (WHERE status = 'issued'),
                  COUNT(*) FILTER (WHERE status = 'expired'),
                  COUNT(*) FILTER (WHERE status = 'redeemed'),
                  COALESCE(SUM(liability_aed), 0)
                  FROM flywheel_offers
                 WHERE tenant_id = :t AND campaign_id = :c"""),
        {"t": tenant_id, "c": campaign_id},
    )).fetchone()

    outstanding, breakage, issued, expired, redeemed, total_issued = (
        money(row[0]), money(row[1]), int(row[2]), int(row[3]), int(row[4]), money(row[5]))

    clawed = money((await db.execute(
        text("""SELECT COALESCE(SUM(discount_clawed_back_aed), 0)
                  FROM flywheel_returns WHERE tenant_id = :t AND campaign_id = :c"""),
        {"t": tenant_id, "c": campaign_id},
    )).scalar() or 0)

    settled = expired + redeemed
    breakage_rate = (Decimal(expired) / Decimal(settled)) if settled else ZERO

    return {
        "outstanding_liability_aed": str(outstanding),
        "breakage_aed": str(breakage),
        "breakage_rate": str(round(breakage_rate, 5)),
        "clawed_back_aed": str(clawed),
        "offers_issued": str(issued),
        "offers_expired": str(expired),
        "offers_redeemed": str(redeemed),
        "total_issued_liability_aed": str(total_issued),
    }
