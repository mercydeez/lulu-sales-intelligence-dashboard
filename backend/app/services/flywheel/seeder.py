"""Stage 1 — the honest synthetic customer layer.

WHY SYNTHETIC, AND WHY SAY SO LOUDLY. The underlying dataset (Kaggle store-item
demand) is store×item×day aggregates with no customer identity — there is no
real customer behaviour to learn from. Rather than pretend otherwise, Flywheel
generates a customer layer with a FIXED SEED and stamps every row
`is_synthetic = TRUE`. Every UI surface says so, and the model card refuses to
claim production accuracy. That honesty is the point, not a caveat.

WHAT MAKES IT "HONEST" RATHER THAN NOISE:
  * Ten archetypes with genuinely different generative processes, so churn is
    LEARNABLE from behaviour (recency/gap/drift) rather than from a label leak.
  * Purchase events reference REAL rows in sales_historical via
    flywheel_purchase_attributions — the existing sales facts are never modified.
  * The archetype is stored but deliberately excluded from the feature set; a
    model that could read it would score 1.0 AUC and teach us nothing.
  * No sensitive attributes are generated at all (see the fairness note).

Determinism: every random draw comes from `random.Random(seed)` instances seeded
per customer, so regenerating produces byte-identical data and the treatment/
control split stays stable across runs.
"""
from __future__ import annotations

import logging
import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel.types import money

logger = logging.getLogger(__name__)

DEFAULT_SEED = 42

#: Lowest demand weight any day may carry. A quiet trading day should make a
#: purchase unlikely, not impossible — at zero the acceptance loop below could
#: never place a purchase there and would burn its whole slide budget.
DEMAND_FLOOR = 0.15

#: How many days a proposed purchase may slide forward looking for a busier
#: day. Small on purpose: this is meant to nudge a date onto a realistic
#: trading day, not to relocate it into a different week and corrupt the
#: interpurchase gap the churn model reads.
DEMAND_SLIDE_LIMIT = 4

# ---------------------------------------------------------------------------
# The ten archetypes (§9). Each is a distinct GENERATIVE PROCESS, described by
# the parameters the generator actually uses — not a cosmetic label.
#
#   gap_days        mean days between purchases
#   gap_sigma       volatility of that gap (high = erratic, hard to predict)
#   basket_units    typical units per purchase
#   drift           multiplier applied to spend across the window
#                   (<1 = declining, >1 = growing) — this is what "declining"
#                   customers actually DO, so the feature can detect it
#   promo_affinity  P(redeem | offered) — drives realistic uplift structure
#   return_rate     P(return | purchase)
#   churn_prone     ground-truth propensity to stop; the LABEL derives from
#                   observed behaviour, never from this field directly
#   categories      how many distinct categories they shop
# ---------------------------------------------------------------------------
ARCHETYPES: Dict[str, Dict[str, Any]] = {
    "loyal_frequent":     dict(gap_days=6,  gap_sigma=2,  basket_units=4, drift=1.02,
                               promo_affinity=0.35, return_rate=0.02, churn_prone=0.04, categories=5),
    "high_value":         dict(gap_days=9,  gap_sigma=3,  basket_units=9, drift=1.05,
                               promo_affinity=0.22, return_rate=0.03, churn_prone=0.06, categories=6),
    "declining":          dict(gap_days=14, gap_sigma=7,  basket_units=3, drift=0.62,
                               promo_affinity=0.48, return_rate=0.04, churn_prone=0.46, categories=3),
    "discount_sensitive": dict(gap_days=11, gap_sigma=5,  basket_units=3, drift=0.95,
                               promo_affinity=0.78, return_rate=0.05, churn_prone=0.30, categories=4),
    "promotion_resistant": dict(gap_days=13, gap_sigma=4, basket_units=4, drift=0.97,
                               promo_affinity=0.04, return_rate=0.02, churn_prone=0.24, categories=3),
    "category_loyalist":  dict(gap_days=10, gap_sigma=4,  basket_units=3, drift=0.88,
                               promo_affinity=0.30, return_rate=0.03, churn_prone=0.28, categories=1),
    "seasonal":           dict(gap_days=26, gap_sigma=13, basket_units=6, drift=1.0,
                               promo_affinity=0.34, return_rate=0.03, churn_prone=0.18, categories=4),
    "lapsed":             dict(gap_days=40, gap_sigma=18, basket_units=2, drift=0.38,
                               promo_affinity=0.55, return_rate=0.04, churn_prone=0.72, categories=2),
    "high_return":        dict(gap_days=12, gap_sigma=5,  basket_units=4, drift=0.90,
                               promo_affinity=0.42, return_rate=0.30, churn_prone=0.36, categories=4),
    "near_contact_limit": dict(gap_days=9,  gap_sigma=3,  basket_units=3, drift=0.94,
                               promo_affinity=0.40, return_rate=0.03, churn_prone=0.22, categories=3),
}

#: Population mix. Weighted so at-risk segments are well represented (a demo
#: where 95% of customers are healthy has nothing to decide about) while
#: still leaving a solid loyal majority, as a real retailer would have.
ARCHETYPE_WEIGHTS: List[Tuple[str, int]] = [
    ("loyal_frequent", 22), ("high_value", 10), ("declining", 16),
    ("discount_sensitive", 13), ("promotion_resistant", 7), ("category_loyalist", 7),
    ("seasonal", 7), ("lapsed", 9), ("high_return", 5), ("near_contact_limit", 4),
]

CHANNELS = ("email", "sms", "push", "app")


def _weighted_archetype(rng: random.Random) -> str:
    total = sum(w for _, w in ARCHETYPE_WEIGHTS)
    pick = rng.randint(1, total)
    running = 0
    for name, weight in ARCHETYPE_WEIGHTS:
        running += weight
        if pick <= running:
            return name
    return ARCHETYPE_WEIGHTS[0][0]


async def _reference_data(db: AsyncSession, tenant_id: int) -> Dict[str, Any]:
    """Stores, items (with price) and a pool of real historical sale ids to
    attribute against. Nothing here is written — this is the layer Flywheel
    references rather than modifies."""
    stores = [int(r[0]) for r in (await db.execute(
        text("SELECT id FROM stores ORDER BY id"))).fetchall()]

    items = [
        {"id": int(r[0]), "category": r[1] or "General", "price": money(r[2] or 10)}
        for r in (await db.execute(text(
            "SELECT id, category, unit_price_aed FROM items ORDER BY id"))).fetchall()
    ]

    # Real sale rows to attribute synthetic purchases to, keyed by (store, item).
    # Capped: we only need a pool to draw from, not the whole 900k-row history.
    sale_rows = (await db.execute(
        text("""SELECT id, store_id, item_id, date
                  FROM sales_historical
                 WHERE tenant_id = :t
                 ORDER BY date DESC
                 LIMIT 40000"""),
        {"t": tenant_id},
    )).fetchall()

    sales_index: Dict[Tuple[int, int], List[Tuple[int, date]]] = {}
    for sid, store_id, item_id, sale_date in sale_rows:
        sales_index.setdefault((int(store_id), int(item_id)), []).append((int(sid), sale_date))

    demand = await _demand_index(db, tenant_id)

    return {"stores": stores, "items": items, "sales_index": sales_index,
            "demand": demand}


async def _demand_index(
    db: AsyncSession, tenant_id: int
) -> Dict[int, Dict[date, float]]:
    """Per-store daily demand weight in [DEMAND_FLOOR, 1.0], from the REAL data.

    This is the bridge between the dataset and the synthetic customer layer.
    Without it, purchase dates come from a bare `gauss(gap_days, sigma)` draw —
    statistically tidy but blind to the actual business. The generated
    population then has no weekday rhythm, no seasonality and no store-level
    trend, because none of those exist in a gaussian.

    Each store is normalised against its OWN 95th percentile, not a global
    maximum: store volumes here differ by roughly an order of magnitude, and a
    global scale would pin every smaller store near the floor — effectively
    excluding it. Using p95 rather than the max stops one freak trading day
    flattening the rest of the year.

    Weights are FLOORED, never zeroed. A quiet day should be unlikely, not
    impossible, and a hard zero would make the acceptance loop below spin
    against days it can never accept.
    """
    rows = (await db.execute(
        text("""SELECT store_id, date, SUM(sales)::float AS units
                  FROM sales_historical
                 WHERE tenant_id = :t
                 GROUP BY store_id, date"""),
        {"t": tenant_id},
    )).fetchall()

    by_store: Dict[int, Dict[date, float]] = {}
    for store_id, day, units in rows:
        by_store.setdefault(int(store_id), {})[day] = float(units or 0)

    index: Dict[int, Dict[date, float]] = {}
    for store_id, days in by_store.items():
        if not days:
            continue
        ordered = sorted(days.values())
        p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] or 1.0
        index[store_id] = {
            day: max(DEMAND_FLOOR, min(1.0, units / p95))
            for day, units in days.items()
        }
    return index


async def seed_customers(
    db: AsyncSession,
    *,
    tenant_id: int,
    customer_count: int = 600,
    history_days: int = 365,
    seed: int = DEFAULT_SEED,
    force: bool = False,
) -> Dict[str, Any]:
    """Generate the customer + event + consent layer for a tenant.

    Idempotent by default: if customers already exist this returns without
    touching anything, so a container restart cannot double the population.
    Pass `force=True` to wipe and regenerate (used by tests and the demo reset).

    Does NOT commit — the caller owns the transaction.
    """
    existing = (await db.execute(
        text("SELECT COUNT(*) FROM flywheel_customers WHERE tenant_id = :t"),
        {"t": tenant_id},
    )).scalar() or 0

    if existing and not force:
        return {"created": 0, "skipped": True, "existing": int(existing)}

    if force and existing:
        # CASCADE from customers removes events, consents, attributions, audience
        # rows and predictions — every dependent FK is ON DELETE CASCADE.
        await db.execute(text("DELETE FROM flywheel_customers WHERE tenant_id = :t"),
                         {"t": tenant_id})

    ref = await _reference_data(db, tenant_id)
    if not ref["stores"] or not ref["items"]:
        return {"created": 0, "skipped": True,
                "reason": "no stores/items to generate against"}

    today = date.today()
    window_start = today - timedelta(days=history_days)
    rng = random.Random(seed)

    customers_created = 0
    events_created = 0
    attributions_created = 0

    for n in range(customer_count):
        # Per-customer RNG: adding customer 601 does not perturb customers 1-600.
        crng = random.Random(f"{seed}:{tenant_id}:{n}")
        archetype = _weighted_archetype(crng)
        spec = ARCHETYPES[archetype]

        home_store = crng.choice(ref["stores"])
        enrolled = window_start - timedelta(days=crng.randint(0, 900))

        # Loyalty tier is behavioural: driven by basket size, not demographics.
        tier = ("platinum" if spec["basket_units"] >= 8 else
                "gold" if spec["basket_units"] >= 5 else
                "silver" if spec["basket_units"] >= 3 else "standard")

        cust_row = (await db.execute(
            text("""INSERT INTO flywheel_customers
                       (tenant_id, external_ref, display_name, home_store_id,
                        archetype, enrolled_on, loyalty_tier, status, is_synthetic)
                    VALUES (:t, :ref, :name, :store, :arch, :enrolled, :tier, 'active', TRUE)
                    ON CONFLICT (tenant_id, external_ref) DO NOTHING
                    RETURNING id"""),
            {"t": tenant_id, "ref": f"SYN-{tenant_id}-{n:05d}",
             "name": f"Synthetic Customer {n:05d}", "store": home_store,
             "arch": archetype, "enrolled": enrolled, "tier": tier},
        )).fetchone()
        if cust_row is None:
            continue
        customer_id = int(cust_row[0])
        customers_created += 1

        # --- consent ---------------------------------------------------------
        # near_contact_limit customers get a deliberately tight cap so the
        # contact-frequency guardrail is demonstrable rather than theoretical.
        cap = 1 if archetype == "near_contact_limit" else crng.choice([2, 3, 4])
        for channel in CHANNELS:
            granted = not (archetype == "promotion_resistant" and channel in ("sms", "push"))
            await db.execute(
                text("""INSERT INTO flywheel_customer_consents
                           (tenant_id, customer_id, channel, granted, max_contacts_per_week)
                        VALUES (:t, :c, :ch, :g, :cap)
                        ON CONFLICT (tenant_id, customer_id, channel) DO NOTHING"""),
                {"t": tenant_id, "c": customer_id, "ch": channel, "g": granted, "cap": cap},
            )

        # --- purchase history ------------------------------------------------
        # Walk forward from window_start drawing gaps from the archetype, then
        # stop early for churn-prone customers so their RECENCY is genuinely
        # large — the signal the model must learn.
        categories = [it["category"] for it in ref["items"]]
        preferred = crng.sample(
            sorted(set(categories)), min(spec["categories"], len(set(categories)))
        )

        # The historical treatment arm: 60% of customers were ever exposed to
        # offers, 40% form the control arm the uplift T-learner needs. Decided
        # per customer and derived from the fixed seed, so it is reproducible.
        historically_treated = crng.random() < 0.60

        cursor = window_start + timedelta(days=crng.randint(0, 10))
        # Churn-prone customers go quiet partway through the window.
        stop_at = today
        if crng.random() < spec["churn_prone"]:
            stop_at = today - timedelta(days=crng.randint(35, 150))

        event_batch: List[Dict[str, Any]] = []
        purchase_index = 0

        store_demand = ref["demand"].get(home_store, {})

        while cursor < stop_at:
            gap = max(1, int(crng.gauss(spec["gap_days"], spec["gap_sigma"])))
            cursor += timedelta(days=gap)
            if cursor >= stop_at:
                break

            # ── Bend the date toward when this store is ACTUALLY busy ───────
            #
            # THE CONSTRAINT THAT SHAPES THIS: the archetype's cadence — mean
            # gap, volatility, and the drift that makes a declining customer
            # decline — IS the churn signal the model has to learn. Sampling
            # dates directly from the demand curve would produce beautifully
            # realistic seasonality and destroy that signal entirely, because
            # every customer would then share one arrival process.
            #
            # So the gap process still PROPOSES the date and real demand only
            # NUDGES it, within a SYMMETRIC window around the proposal.
            #
            # The window is symmetric because an earlier forward-only version
            # was measurably biased: a rejected day always slid to the day
            # AFTER it, so mass drained off the weekly trough onto its
            # successor. Measured against the real profile, Monday's shortfall
            # reappeared as a Tuesday surplus of +2.0 points that exists in no
            # real store. Choosing among neighbouring days weighted by their
            # actual demand has no preferred direction, so the rhythm is
            # inherited without inventing that artefact.
            window = [
                cursor + timedelta(days=offset)
                for offset in range(-DEMAND_SLIDE_LIMIT, DEMAND_SLIDE_LIMIT + 1)
            ]
            window = [d for d in window if window_start <= d < stop_at]
            if window:
                weights = [store_demand.get(d, 1.0) for d in window]
                total = sum(weights)
                if total > 0:
                    pick = crng.random() * total
                    running = 0.0
                    for day, weight in zip(window, weights):
                        running += weight
                        if pick <= running:
                            cursor = day
                            break
            if cursor >= stop_at:
                break

            # Spend drift across the window: 0 at start → 1 at end.
            progress = (cursor - window_start).days / max(1, history_days)
            drift_factor = 1 + (spec["drift"] - 1) * progress

            candidates = [it for it in ref["items"] if it["category"] in preferred] or ref["items"]
            item = crng.choice(candidates)
            units = max(1, int(round(crng.gauss(spec["basket_units"], 1.2) * drift_factor)))
            value = money(Decimal(units) * item["price"])
            # Margin assumption for synthetic events: 30% of value. The REAL
            # margin used for money decisions comes from item_costs, never here.
            margin = money(value * Decimal("0.30"))

            event_batch.append({
                "type": "purchase", "at": datetime.combine(cursor, datetime.min.time(),
                                                           tzinfo=timezone.utc),
                "store": home_store, "item": item["id"], "category": item["category"],
                "units": units, "value": value, "margin": margin,
            })
            purchase_index += 1

            # Returns
            if crng.random() < spec["return_rate"]:
                event_batch.append({
                    "type": "return",
                    "at": datetime.combine(cursor + timedelta(days=crng.randint(1, 7)),
                                           datetime.min.time(), tzinfo=timezone.utc),
                    "store": home_store, "item": item["id"], "category": item["category"],
                    "units": 1, "value": item["price"], "margin": money(-item["price"] * Decimal("0.30")),
                })

            # Offer exposure + response — this is what makes uplift learnable.
            #
            # `historically_treated` is decided ONCE PER CUSTOMER, above, not per
            # purchase. Rolling it per purchase (the first version) meant a
            # customer with 20 purchases had a ~99.9% chance of at least one
            # offer, so essentially everyone counted as treated: the T-learner
            # saw 297 treated against 3 control and could not fit at all.
            #
            # A synthetic RANDOMIZED-treatment log needs a genuine holdout, so
            # ~40% of customers never see an offer in their history. Uplift is a
            # difference between two arms; without a control arm there is
            # nothing to difference.
            if historically_treated and crng.random() < 0.30:
                seen_at = datetime.combine(cursor - timedelta(days=1),
                                           datetime.min.time(), tzinfo=timezone.utc)
                event_batch.append({
                    "type": "offer_seen", "at": seen_at, "store": home_store,
                    "item": item["id"], "category": item["category"],
                    "units": 0, "value": Decimal("0"), "margin": Decimal("0"),
                })
                responded = crng.random() < spec["promo_affinity"]
                event_batch.append({
                    "type": "offer_redeemed" if responded else "offer_ignored",
                    "at": seen_at + timedelta(hours=6), "store": home_store,
                    "item": item["id"], "category": item["category"],
                    "units": 0, "value": Decimal("0"), "margin": Decimal("0"),
                })

        # Persist events, attributing purchases to REAL historical sale rows.
        for ev in event_batch:
            ev_row = (await db.execute(
                text("""INSERT INTO flywheel_customer_events
                           (tenant_id, customer_id, event_type, occurred_at, store_id,
                            item_id, category, quantity_units, value_aed, margin_aed, metadata)
                        VALUES (:t, :c, :et, :at, :store, :item, :cat, :units, :val, :margin,
                                CAST(:meta AS JSONB))
                        RETURNING id"""),
                {"t": tenant_id, "c": customer_id, "et": ev["type"], "at": ev["at"],
                 "store": ev["store"], "item": ev["item"], "cat": ev["category"],
                 "units": ev["units"], "val": ev["value"], "margin": ev["margin"],
                 "meta": '{"source": "flywheel_seeder"}'},
            )).fetchone()
            events_created += 1

            if ev["type"] == "purchase":
                pool = ref["sales_index"].get((ev["store"], ev["item"]))
                if pool:
                    sale_id, _ = pool[crng.randrange(len(pool))]
                    await db.execute(
                        text("""INSERT INTO flywheel_purchase_attributions
                                   (tenant_id, event_id, sale_source, sale_id, attributed_units)
                                VALUES (:t, :e, 'historical', :s, :u)"""),
                        {"t": tenant_id, "e": int(ev_row[0]), "s": sale_id,
                         "u": max(1, ev["units"])},
                    )
                    attributions_created += 1

        # Mark customers with no recent activity as dormant, so the status column
        # reflects the generated behaviour instead of claiming everyone is active.
        if stop_at < today - timedelta(days=90):
            await db.execute(
                text("UPDATE flywheel_customers SET status = 'dormant' WHERE id = :c"),
                {"c": customer_id},
            )

    logger.info("flywheel.seed tenant=%s customers=%s events=%s attributions=%s",
                tenant_id, customers_created, events_created, attributions_created)
    return {
        "created": customers_created,
        "events": events_created,
        "attributions": attributions_created,
        "skipped": False,
        "seed": seed,
        "archetypes": sorted(ARCHETYPES.keys()),
    }


async def population_summary(db: AsyncSession, tenant_id: int) -> Dict[str, Any]:
    """Counts by archetype and status — powers the Customer View header and lets
    a reviewer confirm the mix is what the generator claims."""
    rows = (await db.execute(
        text("""SELECT archetype, status, COUNT(*)
                  FROM flywheel_customers WHERE tenant_id = :t
                 GROUP BY archetype, status ORDER BY archetype"""),
        {"t": tenant_id},
    )).fetchall()
    by_archetype: Dict[str, Dict[str, int]] = {}
    total = 0
    for archetype, status, count in rows:
        by_archetype.setdefault(archetype, {})[status] = int(count)
        total += int(count)
    events = (await db.execute(
        text("SELECT COUNT(*) FROM flywheel_customer_events WHERE tenant_id = :t"),
        {"t": tenant_id},
    )).scalar() or 0
    return {
        "total_customers": total,
        "total_events": int(events),
        "by_archetype": by_archetype,
        "is_synthetic": True,
        "disclaimer": "All customers, events and outcomes are synthetic. "
                      "No production accuracy is claimed.",
    }
