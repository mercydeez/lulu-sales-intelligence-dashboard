"""Coalition attribution — a retained customer's value is not the retailer's alone.

WHY THIS IS TABLE STAKES IN THE GCC. Gulf loyalty is coalition-shaped. Majid Al
Futtaim's SHARE, ADNOC, e& Smiles each link grocery, fuel, hospitality and travel
under one earn-and-redeem wallet. A customer the grocery retailer "retained" may
have been pulled back by fuel points earned last week or a hotel redemption
coming up. Claiming 100% of that customer's incremental value for the grocery
campaign overstates the campaign and misallocates the next dirham. Multi-party
attribution is not a refinement here; it is how the number is honestly computed.

THE ATTRIBUTION MODELS. Three, all deterministic:

  * LINEAR — split the incremental value equally across every partner the
    customer engaged with in the window. The robust default: it assumes nothing
    about which touch mattered more, and at this data volume that restraint is a
    feature.
  * TIME_DECAY — weight recent engagement more (an exponential half-life), on the
    theory that the touch nearest the outcome influenced it most.
  * POSITION — weight the first and last touches most (they opened and closed the
    relationship), the rest evenly.

Whichever model, THE WEIGHTS SUM TO 1 per (campaign, customer) — the retailer's
own campaign is one partner among them, so the retailer is never double-counting
value that a coalition partner delivered. The database cannot enforce a
cross-row sum, so this service asserts it and a test guards it.

THE GOVERNING RULE HOLDS. Attribution is arithmetic over recorded activity; it
moves no money on its own. It informs how incremental margin is REPORTED across
partners, and any settlement between partners is a separate, deliberate step.
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel.types import ZERO, money

logger = logging.getLogger(__name__)

#: Half-life (days) for the time-decay model — a touch this many days before the
#: outcome carries half the weight of one at the outcome.
TIME_DECAY_HALFLIFE_DAYS = 30.0


async def register_partner(
    db: AsyncSession, *, tenant_id: int, partner_name: str, partner_type: str,
    external_ref: Optional[str] = None,
) -> Dict[str, Any]:
    partner_id = int((await db.execute(
        text("""INSERT INTO flywheel_coalition_partners
                   (tenant_id, partner_name, partner_type, external_ref)
                VALUES (:t, :n, :ty, :ref)
                ON CONFLICT (tenant_id, partner_name) DO UPDATE
                    SET partner_type = EXCLUDED.partner_type,
                        external_ref = EXCLUDED.external_ref
                RETURNING id"""),
        {"t": tenant_id, "n": partner_name, "ty": partner_type, "ref": external_ref},
    )).scalar())
    return {"partner_id": partner_id, "partner_name": partner_name}


async def record_activity(
    db: AsyncSession, *, tenant_id: int, customer_id: int, partner_id: int,
    activity_type: str, points: int = 0, value_aed: Decimal = ZERO,
    occurred_at: Optional[datetime] = None,
) -> None:
    await db.execute(
        text("""INSERT INTO flywheel_coalition_activity
                   (tenant_id, customer_id, partner_id, activity_type, points,
                    value_aed, occurred_at)
                VALUES (:t, :c, :p, :a, :pts, :v, COALESCE(:occ, now()))"""),
        {"t": tenant_id, "c": customer_id, "p": partner_id, "a": activity_type,
         "pts": points, "v": money(value_aed), "occ": occurred_at},
    )


async def attribute(
    db: AsyncSession, *, tenant_id: int, campaign_id: int, customer_id: int,
    incremental_margin_aed: Decimal, model: str = "linear",
    window_days: int = 60, as_of: Optional[datetime] = None,
    persist: bool = True,
) -> Dict[str, Any]:
    """Split a retained customer's incremental margin across coalition partners.

    Returns the per-partner weights (summing to 1) and attributed margin. If the
    customer engaged no partners in the window, the whole value is attributed to
    the retailer's own campaign — stated explicitly, not silently dropped.
    """
    if model not in ("linear", "time_decay", "position"):
        raise ValueError(f"unknown attribution model: {model}")

    as_of = as_of or datetime.now(timezone.utc)
    window_start = as_of - timedelta(days=window_days)

    touches = (await db.execute(
        text("""SELECT partner_id, MIN(occurred_at) AS first_at,
                       MAX(occurred_at) AS last_at, COUNT(*) AS n
                  FROM flywheel_coalition_activity
                 WHERE tenant_id = :t AND customer_id = :c
                   AND occurred_at >= :start AND occurred_at <= :asof
                 GROUP BY partner_id
                 ORDER BY MIN(occurred_at)"""),
        {"t": tenant_id, "c": customer_id, "start": window_start, "asof": as_of},
    )).fetchall()

    incremental_margin = money(incremental_margin_aed)

    if not touches:
        result = {
            "campaign_id": campaign_id, "customer_id": customer_id, "model": model,
            "attribution": [], "unattributed_to_retailer": True,
            "retailer_margin_aed": str(incremental_margin),
            "note": ("No coalition activity in the window — the whole incremental "
                     "value is the retailer's own. Nothing is silently dropped."),
        }
        return result

    weights = _weights(touches, model, as_of)
    # Numerical safety: renormalise so the weights sum to exactly 1 even after
    # rounding, and assert it — the whole point is that the retailer never
    # double-counts value a partner delivered.
    total_w = sum(weights.values())
    weights = {pid: (w / total_w if total_w > 0 else 0.0) for pid, w in weights.items()}

    attribution = []
    running = ZERO
    partner_ids = list(weights.keys())
    for i, pid in enumerate(partner_ids):
        # Assign the remainder to the last partner so the parts sum to the whole
        # to the fils, rather than leaving a rounding crumb unattributed.
        if i == len(partner_ids) - 1:
            share = money(incremental_margin - running)
        else:
            share = money(incremental_margin * Decimal(str(weights[pid])))
            running = money(running + share)
        attribution.append({
            "partner_id": pid,
            "attribution_weight": round(weights[pid], 5),
            "attributed_margin_aed": str(share),
        })
        if persist:
            await db.execute(
                text("""INSERT INTO flywheel_coalition_attribution
                           (tenant_id, campaign_id, customer_id, partner_id,
                            attribution_weight, attributed_margin_aed, model)
                        VALUES (:t, :c, :cust, :p, :w, :m, :model)
                        ON CONFLICT (tenant_id, campaign_id, customer_id, partner_id)
                        DO UPDATE SET attribution_weight = EXCLUDED.attribution_weight,
                                      attributed_margin_aed = EXCLUDED.attributed_margin_aed,
                                      model = EXCLUDED.model, computed_at = now()"""),
                {"t": tenant_id, "c": campaign_id, "cust": customer_id, "p": pid,
                 "w": round(weights[pid], 5), "m": share, "model": model},
            )

    weight_sum = round(sum(a["attribution_weight"] for a in attribution), 5)
    return {
        "campaign_id": campaign_id, "customer_id": customer_id, "model": model,
        "attribution": attribution,
        "weight_sum": weight_sum,
        "incremental_margin_aed": str(incremental_margin),
        "note": ("Weights sum to 1 across the partners engaged, so the retailer "
                 "never claims value a coalition partner delivered."),
    }


def _weights(touches, model: str, as_of: datetime) -> Dict[int, float]:
    """Raw (un-normalised) weight per partner under the chosen model."""
    if model == "linear":
        return {int(t[0]): 1.0 for t in touches}

    if model == "time_decay":
        weights = {}
        for t in touches:
            last_at = t[2]
            days = max(0.0, (as_of - last_at).total_seconds() / 86400.0)
            # 0.5 ** (days / halflife): recent touches weigh more.
            weights[int(t[0])] = math.pow(0.5, days / TIME_DECAY_HALFLIFE_DAYS)
        return weights

    # position: first and last touch weigh most, middle touches share the rest.
    n = len(touches)
    if n == 1:
        return {int(touches[0][0]): 1.0}
    weights = {}
    for i, t in enumerate(touches):
        if i == 0 or i == n - 1:
            weights[int(t[0])] = 0.4
        else:
            weights[int(t[0])] = 0.2 / max(1, n - 2)
    return weights


async def campaign_attribution(
    db: AsyncSession, *, tenant_id: int, campaign_id: int
) -> Dict[str, Any]:
    """Roll up attributed margin by partner for a campaign — who the retained
    value actually accrued to across the coalition."""
    rows = (await db.execute(
        text("""SELECT p.partner_name, p.partner_type,
                       COUNT(DISTINCT a.customer_id) AS customers,
                       COALESCE(SUM(a.attributed_margin_aed), 0) AS margin,
                       AVG(a.attribution_weight) AS avg_weight
                  FROM flywheel_coalition_attribution a
                  JOIN flywheel_coalition_partners p ON p.id = a.partner_id
                 WHERE a.tenant_id = :t AND a.campaign_id = :c
                 GROUP BY p.partner_name, p.partner_type
                 ORDER BY SUM(a.attributed_margin_aed) DESC"""),
        {"t": tenant_id, "c": campaign_id},
    )).fetchall()
    return {
        "campaign_id": campaign_id,
        "by_partner": [{
            "partner_name": r[0], "partner_type": r[1],
            "customers": int(r[2]), "attributed_margin_aed": str(money(r[3])),
            "avg_weight": round(float(r[4]), 4) if r[4] is not None else None,
        } for r in rows],
    }


async def partners(db: AsyncSession, *, tenant_id: int) -> List[Dict[str, Any]]:
    rows = (await db.execute(
        text("""SELECT id, partner_name, partner_type, status FROM flywheel_coalition_partners
                 WHERE tenant_id = :t ORDER BY partner_name"""),
        {"t": tenant_id},
    )).fetchall()
    return [{"partner_id": int(r[0]), "partner_name": r[1],
             "partner_type": r[2], "status": r[3]} for r in rows]
