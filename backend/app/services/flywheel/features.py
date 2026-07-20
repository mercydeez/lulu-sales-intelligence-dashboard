"""Stage 1→2 — point-in-time feature engineering, with explicit leakage control.

THE LEAKAGE RULE (§8.4), stated once and enforced everywhere in this file:

    FEATURE WINDOW   [as_of - FEATURE_WINDOW_DAYS, as_of)   — what we may look at
    OUTCOME WINDOW   [as_of, as_of + OUTCOME_WINDOW_DAYS)   — what we predict

    Nothing on or after `as_of` may enter a feature. Nothing before `as_of` may
    define the label.

That boundary is the difference between a model and a fortune teller. Every
query below carries `occurred_at < :as_of`; the label query below carries
`occurred_at >= :as_of`. They are written next to each other deliberately so a
reviewer can see that they cannot overlap.

The `archetype` column is NEVER selected here. It is the generative ground truth;
a model given it would score near-perfectly and prove nothing.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel.types import money

logger = logging.getLogger(__name__)

#: How far back a feature may look.
FEATURE_WINDOW_DAYS = 180
#: How far forward the label looks. A customer who makes no purchase in this
#: window after `as_of` is labelled churned.
OUTCOME_WINDOW_DAYS = 60

#: The exact feature vector, in order. Persisted onto every model_version row so
#: a stored model can be matched to the features it was trained on.
FEATURE_NAMES: List[str] = [
    "recency_days", "frequency_90d", "monetary_90d_aed", "avg_basket_aed",
    "spend_drift_ratio", "interpurchase_gap_days", "gap_volatility",
    "category_diversity", "return_ratio", "promo_response_rate",
    "tenure_days", "events_90d",
]


async def build_snapshots(
    db: AsyncSession, *, tenant_id: int, as_of: Optional[date] = None,
    customer_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Compute and persist a feature snapshot per customer as of a cutoff date.

    Implemented as ONE set-based SQL statement rather than a Python loop over
    customers: at 600 customers × 200 events the row-by-row version issued tens
    of thousands of round-trips and took minutes. This runs in a single pass.

    Upserts on (tenant, customer, as_of) so re-running is idempotent.
    """
    as_of = as_of or date.today()
    window_start = as_of - timedelta(days=FEATURE_WINDOW_DAYS)
    recent_start = as_of - timedelta(days=90)
    # Spend drift compares the most recent 90 days against the 90 before it.
    baseline_start = as_of - timedelta(days=180)

    filter_clause = ""
    params: Dict[str, Any] = {
        "t": tenant_id, "as_of": as_of, "win": window_start,
        "recent": recent_start, "base": baseline_start,
    }
    if customer_ids:
        filter_clause = "AND c.id = ANY(:cids)"
        params["cids"] = customer_ids

    # One statement, several CTEs. Every event CTE is bounded by
    # `occurred_at < :as_of` — the leakage boundary.
    sql = f"""
    WITH purchases AS (
        SELECT e.customer_id,
               e.occurred_at,
               e.value_aed,
               e.category,
               ROW_NUMBER() OVER (PARTITION BY e.customer_id ORDER BY e.occurred_at) AS rn
          FROM flywheel_customer_events e
          JOIN flywheel_customers c ON c.id = e.customer_id
         WHERE e.tenant_id = :t
           AND e.event_type = 'purchase'
           AND e.occurred_at >= :win
           AND e.occurred_at <  :as_of        -- LEAKAGE BOUNDARY
           {filter_clause}
    ),
    gaps AS (
        -- Days between consecutive purchases, per customer.
        SELECT p.customer_id,
               EXTRACT(EPOCH FROM (p.occurred_at - LAG(p.occurred_at)
                        OVER (PARTITION BY p.customer_id ORDER BY p.occurred_at))) / 86400.0 AS gap_days
          FROM purchases p
    ),
    gap_stats AS (
        SELECT customer_id,
               COALESCE(AVG(gap_days), 0)          AS mean_gap,
               COALESCE(STDDEV_POP(gap_days), 0)   AS gap_sd
          FROM gaps WHERE gap_days IS NOT NULL
         GROUP BY customer_id
    ),
    recent AS (
        SELECT customer_id,
               COUNT(*)                    AS freq_90d,
               COALESCE(SUM(value_aed), 0) AS monetary_90d,
               COALESCE(AVG(value_aed), 0) AS avg_basket,
               COUNT(DISTINCT category)    AS categories,
               MAX(occurred_at)            AS last_purchase
          FROM purchases WHERE occurred_at >= :recent
         GROUP BY customer_id
    ),
    baseline AS (
        -- The 90 days BEFORE the recent window, for drift.
        SELECT customer_id, COALESCE(SUM(value_aed), 0) AS monetary_prior
          FROM purchases
         WHERE occurred_at >= :base AND occurred_at < :recent
         GROUP BY customer_id
    ),
    lifetime AS (
        SELECT customer_id, MAX(occurred_at) AS last_any_purchase
          FROM purchases GROUP BY customer_id
    ),
    returns AS (
        SELECT e.customer_id, COUNT(*) AS n_returns
          FROM flywheel_customer_events e
         WHERE e.tenant_id = :t AND e.event_type = 'return'
           AND e.occurred_at >= :win AND e.occurred_at < :as_of
         GROUP BY e.customer_id
    ),
    offers AS (
        SELECT e.customer_id,
               COUNT(*) FILTER (WHERE e.event_type = 'offer_redeemed') AS redeemed,
               COUNT(*) FILTER (WHERE e.event_type IN ('offer_redeemed','offer_ignored')) AS presented
          FROM flywheel_customer_events e
         WHERE e.tenant_id = :t
           AND e.event_type IN ('offer_redeemed', 'offer_ignored')
           AND e.occurred_at >= :win AND e.occurred_at < :as_of
         GROUP BY e.customer_id
    ),
    all_events AS (
        SELECT e.customer_id, COUNT(*) AS n_events
          FROM flywheel_customer_events e
         WHERE e.tenant_id = :t
           AND e.occurred_at >= :recent AND e.occurred_at < :as_of
         GROUP BY e.customer_id
    )
    INSERT INTO flywheel_feature_snapshots
        (tenant_id, customer_id, as_of_date, recency_days, frequency_90d,
         monetary_90d_aed, avg_basket_aed, spend_drift_ratio,
         interpurchase_gap_days, gap_volatility, category_diversity,
         return_ratio, promo_response_rate, tenure_days, events_90d)
    SELECT
        :t,
        c.id,
        :as_of,
        -- Recency: days since last purchase. A customer who never purchased in
        -- the window gets the full window length, not NULL — "never" is the
        -- most extreme form of "long ago", and NULL would drop the row.
        -- Casts here use CAST(... AS type), never the postfix double-colon
        -- form. SQLAlchemy's bind-parameter regex has a negative lookahead on
        -- the colon, so a bind immediately followed by a postfix cast is NOT
        -- recognised as a bind and is sent to Postgres literally, producing
        -- "syntax error at or near". (And note: that regex scans SQL comments
        -- too, so a comment must never contain a colon-prefixed word either.)
        LEAST({FEATURE_WINDOW_DAYS},
              COALESCE(EXTRACT(DAY FROM (CAST(:as_of AS timestamptz) - l.last_any_purchase)),
                       {FEATURE_WINDOW_DAYS}))::int,
        COALESCE(r.freq_90d, 0)::int,
        COALESCE(r.monetary_90d, 0),
        COALESCE(r.avg_basket, 0),
        -- Drift: recent spend / prior spend. No prior spend → 1.0 (neutral),
        -- because a brand-new customer is not "declining".
        CASE WHEN COALESCE(b.monetary_prior, 0) > 0
             THEN LEAST(9.9999, COALESCE(r.monetary_90d, 0) / b.monetary_prior)
             ELSE 1.0 END,
        COALESCE(g.mean_gap, 0),
        COALESCE(g.gap_sd, 0),
        COALESCE(r.categories, 0)::int,
        -- Return ratio guarded against divide-by-zero.
        CASE WHEN COALESCE(r.freq_90d, 0) > 0
             THEN LEAST(1.0, COALESCE(ret.n_returns, 0)::numeric / r.freq_90d)
             ELSE 0 END,
        CASE WHEN COALESCE(o.presented, 0) > 0
             THEN o.redeemed::numeric / o.presented
             ELSE 0 END,
        GREATEST(0, EXTRACT(DAY FROM (CAST(:as_of AS timestamptz)
                                      - CAST(c.enrolled_on AS timestamptz))))::int,
        COALESCE(ae.n_events, 0)::int
      FROM flywheel_customers c
      LEFT JOIN recent     r   ON r.customer_id  = c.id
      LEFT JOIN baseline   b   ON b.customer_id  = c.id
      LEFT JOIN lifetime   l   ON l.customer_id  = c.id
      LEFT JOIN gap_stats  g   ON g.customer_id  = c.id
      LEFT JOIN returns    ret ON ret.customer_id = c.id
      LEFT JOIN offers     o   ON o.customer_id  = c.id
      LEFT JOIN all_events ae  ON ae.customer_id = c.id
     WHERE c.tenant_id = :t {filter_clause}
    ON CONFLICT (tenant_id, customer_id, as_of_date) DO UPDATE SET
        recency_days           = EXCLUDED.recency_days,
        frequency_90d          = EXCLUDED.frequency_90d,
        monetary_90d_aed       = EXCLUDED.monetary_90d_aed,
        avg_basket_aed         = EXCLUDED.avg_basket_aed,
        spend_drift_ratio      = EXCLUDED.spend_drift_ratio,
        interpurchase_gap_days = EXCLUDED.interpurchase_gap_days,
        gap_volatility         = EXCLUDED.gap_volatility,
        category_diversity     = EXCLUDED.category_diversity,
        return_ratio           = EXCLUDED.return_ratio,
        promo_response_rate    = EXCLUDED.promo_response_rate,
        tenure_days            = EXCLUDED.tenure_days,
        events_90d             = EXCLUDED.events_90d
    """

    result = await db.execute(text(sql), params)
    written = result.rowcount or 0
    logger.info("flywheel.features tenant=%s as_of=%s snapshots=%s", tenant_id, as_of, written)
    return {
        "as_of": str(as_of),
        "snapshots": int(written),
        "feature_window_days": FEATURE_WINDOW_DAYS,
        "outcome_window_days": OUTCOME_WINDOW_DAYS,
        "features": FEATURE_NAMES,
    }


async def load_snapshot(
    db: AsyncSession, *, tenant_id: int, customer_id: int, as_of: date
) -> Optional[Dict[str, Any]]:
    """One customer's feature row as a plain dict (ordered per FEATURE_NAMES)."""
    row = (await db.execute(
        text(f"""SELECT {', '.join(FEATURE_NAMES)}
                   FROM flywheel_feature_snapshots
                  WHERE tenant_id = :t AND customer_id = :c AND as_of_date = :d"""),
        {"t": tenant_id, "c": customer_id, "d": as_of},
    )).fetchone()
    if not row:
        return None
    return {name: row[i] for i, name in enumerate(FEATURE_NAMES)}


async def latest_snapshot_date(db: AsyncSession, tenant_id: int) -> Optional[date]:
    return (await db.execute(
        text("SELECT MAX(as_of_date) FROM flywheel_feature_snapshots WHERE tenant_id = :t"),
        {"t": tenant_id},
    )).scalar()


async def build_training_frame(
    db: AsyncSession, *, tenant_id: int, as_of: date,
) -> Dict[str, Any]:
    """Features (before `as_of`) joined to labels (after `as_of`).

    THE LABEL: 1 if the customer made NO purchase in
    [as_of, as_of + OUTCOME_WINDOW_DAYS). This is computed here — in the same
    place as the features — precisely so the two windows are visibly disjoint.

    Returns column-oriented lists rather than a DataFrame so this module never
    imports pandas; the training script (which legitimately depends on pandas,
    lightgbm and torch) does the conversion.
    """
    outcome_end = as_of + timedelta(days=OUTCOME_WINDOW_DAYS)

    rows = (await db.execute(
        text(f"""
        WITH future_purchases AS (
            SELECT DISTINCT customer_id
              FROM flywheel_customer_events
             WHERE tenant_id = :t
               AND event_type = 'purchase'
               AND occurred_at >= :as_of          -- OUTCOME WINDOW starts here
               AND occurred_at <  :outcome_end
        )
        SELECT f.customer_id,
               {', '.join('f.' + n for n in FEATURE_NAMES)},
               CASE WHEN fp.customer_id IS NULL THEN 1 ELSE 0 END AS churned
          FROM flywheel_feature_snapshots f
          LEFT JOIN future_purchases fp ON fp.customer_id = f.customer_id
         WHERE f.tenant_id = :t AND f.as_of_date = :as_of
         ORDER BY f.customer_id
        """),
        {"t": tenant_id, "as_of": as_of, "outcome_end": outcome_end},
    )).fetchall()

    customer_ids = [int(r[0]) for r in rows]
    features = [[float(r[i + 1]) for i in range(len(FEATURE_NAMES))] for r in rows]
    labels = [int(r[-1]) for r in rows]

    positives = sum(labels)
    return {
        "customer_ids": customer_ids,
        "features": features,
        "labels": labels,
        "feature_names": FEATURE_NAMES,
        "as_of": str(as_of),
        "outcome_end": str(outcome_end),
        "n_rows": len(labels),
        "n_positive": positives,
        "base_rate": round(positives / len(labels), 4) if labels else 0.0,
    }


async def build_sequences(
    db: AsyncSession, *, tenant_id: int, as_of: date, max_len: int = 32,
) -> Dict[str, Any]:
    """Ordered event sequences per customer — the input the GRU/Transformer needs.

    This is the structure a flattened tabular snapshot DISCARDS, and the honest
    reason deep learning has a claim here at all (§8.2): the ORDER of purchases
    and the pattern of gaps between them, not just their averages.

    Each event becomes a 4-tuple: (days_before_as_of, log1p(units), log1p(value),
    event_type_index). Sequences are right-aligned and left-padded to `max_len`.
    """
    window_start = as_of - timedelta(days=FEATURE_WINDOW_DAYS)
    type_index = {"purchase": 1, "return": 2, "offer_seen": 3,
                  "offer_redeemed": 4, "offer_ignored": 5, "visit": 6,
                  "complaint": 7, "support_contact": 8}

    rows = (await db.execute(
        text("""SELECT customer_id, event_type, occurred_at, quantity_units, value_aed
                  FROM flywheel_customer_events
                 WHERE tenant_id = :t
                   AND occurred_at >= :win
                   AND occurred_at <  :as_of      -- LEAKAGE BOUNDARY
                 ORDER BY customer_id, occurred_at"""),
        {"t": tenant_id, "win": window_start, "as_of": as_of},
    )).fetchall()

    import math
    by_customer: Dict[int, List[List[float]]] = {}
    for cid, etype, occurred, units, value in rows:
        days_before = (as_of - occurred.date()).days
        by_customer.setdefault(int(cid), []).append([
            float(days_before),
            math.log1p(float(units or 0)),
            math.log1p(float(value or 0)),
            float(type_index.get(etype, 0)),
        ])

    customer_ids: List[int] = []
    sequences: List[List[List[float]]] = []
    lengths: List[int] = []
    pad = [0.0, 0.0, 0.0, 0.0]

    for cid in sorted(by_customer):
        events = by_customer[cid][-max_len:]  # keep the most RECENT max_len
        lengths.append(len(events))
        padded = [pad] * (max_len - len(events)) + events  # left-pad
        customer_ids.append(cid)
        sequences.append(padded)

    return {
        "customer_ids": customer_ids,
        "sequences": sequences,
        "lengths": lengths,
        "max_len": max_len,
        "n_features": 4,
        "as_of": str(as_of),
    }
