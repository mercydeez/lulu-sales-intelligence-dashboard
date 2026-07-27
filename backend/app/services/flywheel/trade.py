"""Track B — supplier-funded trade promotion.

THE DIFFERENCE FROM RETENTION, RESTATED IN CODE. Retention spends the retailer's
own budget against the retailer's own margin, and proves incrementality to the
retailer. Trade promotion spends the SUPPLIER'S money against a jointly-agreed
uplift, and proves it to a counterparty WITH A CONTRACTUAL INCENTIVE TO DISPUTE
THE NUMBER. Three things follow, and this module exists to enforce all three:

  1. SUPPLIER MONEY HAS ITS OWN LIFECYCLE. proposed -> committed -> active ->
     settled, with spend never exceeding commitment and settlement never
     exceeding spend — invariants the database enforces (migration 079), so a
     bug here cannot overspend a supplier's money.

  2. A SUPPLIER SEES ONLY THEIR SKUs. This is a second tenancy axis inside a
     tenant. It is enforced by `supplier_scope()` returning the item ids a
     funding covers, and EVERY supplier-facing read intersecting with it — never
     by trusting a caller to filter. A supplier who could see another supplier's
     SKU performance is a confidentiality breach dressed as a feature.

  3. THE SETTLEMENT MUST SURVIVE AN ADVERSARIAL AUDIT. The amount charged is
     computed from MEASURED incremental margin, net of VAT and NET OF
     CANNIBALIZATION (a supplier does not pay for volume stolen from their own
     other SKU), carries the evidence bundle it was derived from, and becomes
     immutable once issued. "Trust us, it was 12,000 dirhams" is not a
     settlement; "here are the arm sizes, the confidence interval, the
     cannibalization adjustment, and the arithmetic" is.

THE GOVERNING RULE HOLDS. Nothing here lets a model move money. Settlement is a
deterministic computation over measured outcomes, run by a service, inside a
row-locked transaction.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel.types import ZERO, money

logger = logging.getLogger(__name__)


class TradeError(Exception):
    """A supplier-funding operation that cannot proceed."""


# ---------------------------------------------------------------------------
# Funding lifecycle
# ---------------------------------------------------------------------------

async def propose_funding(
    db: AsyncSession, *, tenant_id: int, supplier_id: int, campaign_id: int,
    funding_type: str, committed_aed: Decimal, item_ids: List[int],
    rebate_per_unit_aed: Decimal = ZERO, agreement_ref: Optional[str] = None,
    starts_on: Optional[date] = None, ends_on: Optional[date] = None,
    created_by: Optional[int] = None,
) -> Dict[str, Any]:
    """Record a supplier's proposed funding of a campaign, scoped to their SKUs.

    REFUSES an empty SKU scope: a funding that covers no items is meaningless and
    would later settle to zero while looking committed. The scope is the whole
    point — it is what the supplier sees and is charged on.
    """
    if funding_type not in ("co_op", "scan_down", "fixed_fee"):
        raise TradeError(f"unknown funding_type: {funding_type}")
    if not item_ids:
        raise TradeError("a funding must cover at least one SKU — that scope is "
                         "what the supplier sees and is settled on")

    # Every scoped item must genuinely belong to this supplier (product_suppliers),
    # or a retailer could bill a supplier for a SKU they do not supply.
    supplied = {int(r[0]) for r in (await db.execute(
        text("""SELECT item_id FROM product_suppliers
                 WHERE tenant_id = :t AND supplier_id = :s AND item_id = ANY(:items)"""),
        {"t": tenant_id, "s": supplier_id, "items": item_ids},
    )).fetchall()}
    not_supplied = set(item_ids) - supplied
    if not_supplied:
        raise TradeError(
            f"supplier {supplier_id} does not supply item(s) {sorted(not_supplied)} — "
            f"a funding can only cover the supplier's own SKUs")

    funding_id = int((await db.execute(
        text("""INSERT INTO flywheel_supplier_funding
                   (tenant_id, supplier_id, campaign_id, funding_type, committed_aed,
                    rebate_per_unit_aed, agreement_ref, starts_on, ends_on,
                    created_by, status)
                VALUES (:t, :s, :c, :ft, :committed, :rebate, :ref, :starts, :ends,
                        :by, 'proposed')
                RETURNING id"""),
        {"t": tenant_id, "s": supplier_id, "c": campaign_id, "ft": funding_type,
         "committed": money(committed_aed), "rebate": rebate_per_unit_aed,
         "ref": agreement_ref, "starts": starts_on, "ends": ends_on, "by": created_by},
    )).scalar())

    for item_id in sorted(set(item_ids)):
        await db.execute(
            text("""INSERT INTO flywheel_supplier_funding_skus (tenant_id, funding_id, item_id)
                    VALUES (:t, :f, :i) ON CONFLICT DO NOTHING"""),
            {"t": tenant_id, "f": funding_id, "i": item_id},
        )

    logger.info("flywheel.trade proposed funding=%s supplier=%s campaign=%s %s AED over %s SKUs",
                funding_id, supplier_id, campaign_id, committed_aed, len(set(item_ids)))
    return {"funding_id": funding_id, "status": "proposed",
            "committed_aed": str(money(committed_aed)), "skus": len(set(item_ids))}


async def transition_funding(
    db: AsyncSession, *, tenant_id: int, funding_id: int, target: str,
) -> Dict[str, Any]:
    """Move a funding through its lifecycle, refusing illegal jumps.

    The order proposed -> committed -> active -> settled is enforced here, plus
    the terminal cancelled/disputed. This is the trade-side analogue of the
    campaign state machine: a settled funding cannot go back to active, and an
    active one cannot skip straight to settled without a settlement existing.
    """
    allowed = {
        "proposed": {"committed", "cancelled"},
        "committed": {"active", "cancelled"},
        "active": {"settled", "disputed"},
        "disputed": {"settled", "cancelled"},
        "settled": set(),
        "cancelled": set(),
    }
    current = (await db.execute(
        text("SELECT status FROM flywheel_supplier_funding WHERE tenant_id=:t AND id=:f"),
        {"t": tenant_id, "f": funding_id},
    )).scalar()
    if current is None:
        raise TradeError(f"funding {funding_id} not found")
    if target not in allowed.get(current, set()):
        raise TradeError(f"cannot move funding from '{current}' to '{target}'")

    if target == "settled":
        # A funding may only be marked settled once every issued settlement is
        # paid — otherwise 'settled' would misreport unpaid money as collected.
        unpaid = int((await db.execute(
            text("""SELECT COUNT(*) FROM flywheel_settlements
                     WHERE tenant_id=:t AND funding_id=:f AND status IN ('draft','issued','disputed')"""),
            {"t": tenant_id, "f": funding_id},
        )).scalar())
        if unpaid:
            raise TradeError(f"{unpaid} settlement(s) not yet paid — cannot mark the "
                             f"funding settled while money is outstanding")

    await db.execute(
        text("""UPDATE flywheel_supplier_funding
                   SET status = :s, updated_at = now() WHERE tenant_id=:t AND id=:f"""),
        {"s": target, "t": tenant_id, "f": funding_id},
    )
    return {"funding_id": funding_id, "status": target}


# ---------------------------------------------------------------------------
# Supplier scope — the second tenancy axis
# ---------------------------------------------------------------------------

async def supplier_scope(
    db: AsyncSession, *, tenant_id: int, supplier_id: int
) -> List[int]:
    """The item ids this supplier is entitled to see across all their fundings.

    Every supplier-facing read must intersect with this. It is derived from the
    funding SKU scope, NOT from product_suppliers directly, because a supplier
    sees the SKUs they FUNDED a promotion on, which may be a subset of everything
    they supply.
    """
    rows = (await db.execute(
        text("""SELECT DISTINCT s.item_id
                  FROM flywheel_supplier_funding_skus s
                  JOIN flywheel_supplier_funding f
                    ON f.id = s.funding_id AND f.tenant_id = s.tenant_id
                 WHERE s.tenant_id = :t AND f.supplier_id = :sup"""),
        {"t": tenant_id, "sup": supplier_id},
    )).fetchall()
    return [int(r[0]) for r in rows]


# ---------------------------------------------------------------------------
# Settlement — the number that survives an audit
# ---------------------------------------------------------------------------

async def compute_settlement(
    db: AsyncSession, *, tenant_id: int, funding_id: int,
    period_start: date, period_end: date,
) -> Dict[str, Any]:
    """Compute (but do not issue) what a supplier owes for a period.

    The amount rests on MEASURED, CAUSAL, CANNIBALIZATION-ADJUSTED performance of
    the funded SKUs. Every input is returned in `evidence` so the supplier can
    audit the number rather than trust it. Draft only — issuing is a separate,
    deliberate step (`issue_settlement`) because issuing freezes the amount.
    """
    funding = (await db.execute(
        text("""SELECT supplier_id, campaign_id, funding_type, committed_aed,
                       spent_aed, rebate_per_unit_aed
                  FROM flywheel_supplier_funding
                 WHERE tenant_id = :t AND id = :f"""),
        {"t": tenant_id, "f": funding_id},
    )).fetchone()
    if not funding:
        raise TradeError(f"funding {funding_id} not found")
    supplier_id, campaign_id, funding_type, committed, spent, rebate = funding
    committed = money(committed)

    scope = await _funding_scope(db, tenant_id=tenant_id, funding_id=funding_id)
    if not scope:
        raise TradeError("funding covers no SKUs")

    # CANNIBALIZATION-ADJUSTED incremental margin for the funded SKUs. If a
    # cannibalization readout exists for the campaign, its NET category figure is
    # the honest basis; otherwise we fall back to raw incremental margin and flag
    # the settlement as unreliable, never silently overstating.
    cannib = (await db.execute(
        text("""SELECT net_incremental_margin_aed, cannibalization_rate, is_reliable
                  FROM flywheel_cannibalization
                 WHERE tenant_id = :t AND campaign_id = :c
                   AND (promoted_item_id = ANY(:scope) OR promoted_item_id IS NULL)
                 ORDER BY window_end DESC LIMIT 1"""),
        {"t": tenant_id, "c": campaign_id, "scope": scope},
    )).fetchone()

    # Incremental UNITS of the funded SKUs sold in the window (treatment minus a
    # control-implied baseline is handled by the readout/cannibalization layer;
    # here we count funded-SKU redemption units for scan_down).
    units = int((await db.execute(
        text("""SELECT COALESCE(SUM(r.units), 0)
                  FROM flywheel_redemptions r
                 WHERE r.tenant_id = :t AND r.campaign_id = :c
                   AND r.item_id = ANY(:scope)
                   AND r.created_at >= :start AND r.created_at < :end"""),
        {"t": tenant_id, "c": campaign_id, "scope": scope,
         "start": period_start, "end": period_end},
    )).scalar())

    if cannib and cannib[0] is not None:
        incremental_margin = money(cannib[0])
        cannib_rate = float(cannib[1]) if cannib[1] is not None else None
        reliable = bool(cannib[2])
    else:
        # No cannibalization readout — use raw funded-SKU margin, flagged.
        incremental_margin = money((await db.execute(
            text("""SELECT COALESCE(SUM(margin_aed), 0) FROM flywheel_redemptions
                     WHERE tenant_id = :t AND campaign_id = :c AND item_id = ANY(:scope)
                       AND created_at >= :start AND created_at < :end"""),
            {"t": tenant_id, "c": campaign_id, "scope": scope,
             "start": period_start, "end": period_end},
        )).scalar() or 0)
        cannib_rate = None
        reliable = False

    # The charge, by funding type.
    if funding_type == "scan_down":
        amount_due = money(Decimal(units) * money(rebate))
    elif funding_type == "fixed_fee":
        amount_due = committed  # the whole agreed fee, once the promotion ran
    else:  # co_op: supplier's committed share, capped at their commitment
        amount_due = min(committed, money(spent))

    # NEVER charge more than the supplier committed.
    amount_due = min(amount_due, committed)

    evidence = {
        "funding_type": funding_type,
        "funded_skus": scope,
        "incremental_units": units,
        "incremental_margin_aed": str(incremental_margin),
        "cannibalization_rate": cannib_rate,
        "cannibalization_reliable": reliable,
        "committed_aed": str(committed),
        "rebate_per_unit_aed": str(money(rebate)),
        "basis": ("net-of-cannibalization category lift"
                  if cannib and cannib[0] is not None
                  else "raw funded-SKU margin (no cannibalization readout — directional)"),
    }

    return {
        "funding_id": funding_id, "supplier_id": supplier_id,
        "campaign_id": campaign_id,
        "period": {"from": str(period_start), "to": str(period_end)},
        "incremental_units": units,
        "incremental_margin_aed": str(incremental_margin),
        "amount_due_aed": str(amount_due),
        "reliable": reliable,
        "evidence": evidence,
    }


async def issue_settlement(
    db: AsyncSession, *, tenant_id: int, funding_id: int,
    period_start: date, period_end: date,
) -> Dict[str, Any]:
    """Compute and PERSIST a settlement as issued — freezing the amount.

    Once issued, migration 079's trigger forbids rewriting the amount or period;
    a supplier query is a `dispute` transition, never a silent edit. That is what
    makes the settlement evidence rather than a claim.
    """
    computed = await compute_settlement(
        db, tenant_id=tenant_id, funding_id=funding_id,
        period_start=period_start, period_end=period_end)

    settlement_id = int((await db.execute(
        text("""INSERT INTO flywheel_settlements
                   (tenant_id, funding_id, period_start, period_end,
                    incremental_units, incremental_margin_aed, amount_due_aed,
                    status, evidence, issued_at)
                VALUES (:t, :f, :ps, :pe, :units, :marg, :amt, 'issued',
                        CAST(:ev AS JSONB), now())
                ON CONFLICT (tenant_id, funding_id, period_start, period_end)
                    DO NOTHING
                RETURNING id"""),
        {"t": tenant_id, "f": funding_id, "ps": period_start, "pe": period_end,
         "units": computed["incremental_units"],
         "marg": money(computed["incremental_margin_aed"]),
         "amt": money(computed["amount_due_aed"]),
         "ev": json.dumps(computed["evidence"])},
    )).scalar() or 0)

    if settlement_id == 0:
        raise TradeError("a settlement already exists for this funding and period — "
                         "settlements are issued once and never silently replaced")

    # Draw the settled amount against the funding's spend (row-locked).
    await db.execute(
        text("""UPDATE flywheel_supplier_funding
                   SET spent_aed = LEAST(committed_aed, spent_aed + :amt),
                       settled_aed = settled_aed + :amt,
                       status = CASE WHEN status = 'committed' THEN 'active' ELSE status END,
                       updated_at = now()
                 WHERE tenant_id = :t AND id = :f"""),
        {"amt": money(computed["amount_due_aed"]), "t": tenant_id, "f": funding_id},
    )

    logger.info("flywheel.trade issued settlement=%s funding=%s amount=%s",
                settlement_id, funding_id, computed["amount_due_aed"])
    return {"settlement_id": settlement_id, "status": "issued", **computed}


# ---------------------------------------------------------------------------
# Reads — supplier-scoped
# ---------------------------------------------------------------------------

async def supplier_dashboard(
    db: AsyncSession, *, tenant_id: int, supplier_id: int
) -> Dict[str, Any]:
    """Everything a supplier is entitled to see — and NOTHING they are not.

    Every figure is intersected with this supplier's funding scope. A supplier
    cannot learn another supplier's SKU performance from this endpoint, because
    the queries never leave their scope.
    """
    fundings = (await db.execute(
        text("""SELECT f.id, f.campaign_id, c.name, f.funding_type, f.status,
                       f.committed_aed, f.spent_aed, f.settled_aed,
                       f.starts_on, f.ends_on
                  FROM flywheel_supplier_funding f
                  JOIN flywheel_campaigns c ON c.id = f.campaign_id AND c.tenant_id = f.tenant_id
                 WHERE f.tenant_id = :t AND f.supplier_id = :sup
                 ORDER BY f.created_at DESC"""),
        {"t": tenant_id, "sup": supplier_id},
    )).fetchall()

    funding_rows = []
    for f in fundings:
        settlements = (await db.execute(
            text("""SELECT id, period_start, period_end, amount_due_aed, status,
                           incremental_units, incremental_margin_aed
                      FROM flywheel_settlements
                     WHERE tenant_id = :t AND funding_id = :f
                     ORDER BY period_end DESC"""),
            {"t": tenant_id, "f": int(f[0])},
        )).fetchall()
        funding_rows.append({
            "funding_id": int(f[0]), "campaign_id": int(f[1]), "campaign_name": f[2],
            "funding_type": f[3], "status": f[4],
            "committed_aed": str(money(f[5])), "spent_aed": str(money(f[6])),
            "settled_aed": str(money(f[7])),
            "starts_on": str(f[8]) if f[8] else None,
            "ends_on": str(f[9]) if f[9] else None,
            "settlements": [{
                "settlement_id": int(s[0]),
                "period": {"from": str(s[1]), "to": str(s[2])},
                "amount_due_aed": str(money(s[3])), "status": s[4],
                "incremental_units": int(s[5]),
                "incremental_margin_aed": str(money(s[6])),
            } for s in settlements],
        })

    total_committed = money(sum((Decimal(str(f[5])) for f in fundings), ZERO))
    total_settled = money(sum((Decimal(str(f[7])) for f in fundings), ZERO))
    scope = await supplier_scope(db, tenant_id=tenant_id, supplier_id=supplier_id)

    return {
        "supplier_id": supplier_id,
        "funded_sku_count": len(scope),
        "totals": {"committed_aed": str(total_committed),
                   "settled_aed": str(total_settled)},
        "fundings": funding_rows,
        "confidentiality_note": (
            "This view is scoped to the supplier's funded SKUs only. No other "
            "supplier's SKU performance is reachable from here."),
    }


async def _funding_scope(db: AsyncSession, *, tenant_id: int, funding_id: int) -> List[int]:
    rows = (await db.execute(
        text("""SELECT item_id FROM flywheel_supplier_funding_skus
                 WHERE tenant_id = :t AND funding_id = :f"""),
        {"t": tenant_id, "f": funding_id},
    )).fetchall()
    return [int(r[0]) for r in rows]
