"""Identity resolution — the step between synthetic data and a real shopper.

WHY THIS EXISTS. The engine has never met a real customer; every row is
generated. The bridge to a pilot is a path from a real POS/loyalty export to a
loyalty identity. flywheel_pos_staging lands the raw transactions; this module
resolves each to a customer, and — the point of the whole exercise — leaves a
record UNLINKED rather than guessing.

WHY A WRONG MERGE IS WORSE THAN NO MERGE. Merging two different shoppers into one
identity corrupts three things at once: the feature store (their histories blend
into a person who does not exist), the holdout (one of them may be control, the
other treatment, and the experiment is silently broken), and the consent ledger
(one may have objected to profiling and now the other's data rides on their
record). Leaving a transaction anonymous costs a little signal; a wrong merge
costs correctness everywhere downstream. So the bar to link is high, and below it
the record stays unlinked, on purpose.

THE TWO-TIER MATCH.
  1. DETERMINISTIC — a loyalty_ref that maps to a known customer. Confidence 1.0.
     This is the clean case and most real transactions carry it.
  2. PROBABILISTIC — no loyalty_ref, but a card_hash seen before, or a
     store+time+basket pattern that matches one customer strongly. A score is
     computed; only above a threshold does it link, and a score that matches TWO
     customers comparably resolves to 'ambiguous' (unlinked), never a coin-flip.

NO PII. card_hash is a hashed fingerprint, never a card number; loyalty_ref is
the retailer's own opaque id. This module never sees or stores a PAN.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: Minimum probabilistic score to LINK. Below this, a transaction stays unlinked.
#: Deliberately high — the cost of a wrong merge is correctness everywhere.
LINK_THRESHOLD = 0.80
#: If the best two candidates are within this of each other, the match is
#: AMBIGUOUS and we decline to link rather than guess.
AMBIGUITY_MARGIN = 0.10


async def ingest_pos_row(
    db: AsyncSession, *, tenant_id: int, external_txn_id: str,
    occurred_at, loyalty_ref: Optional[str] = None, card_hash: Optional[str] = None,
    store_id: Optional[int] = None, item_id: Optional[int] = None,
    units: int = 1, amount_aed=0,
) -> int:
    """Land one raw POS transaction in staging. Idempotent on external_txn_id —
    re-importing the same export file is a no-op, never a duplicate."""
    row = (await db.execute(
        text("""INSERT INTO flywheel_pos_staging
                   (tenant_id, external_txn_id, loyalty_ref, card_hash, store_id,
                    item_id, units, amount_aed, occurred_at)
                VALUES (:t, :x, :lr, :ch, :s, :i, :u, :amt, :occ)
                ON CONFLICT (tenant_id, external_txn_id) DO NOTHING
                RETURNING id"""),
        {"t": tenant_id, "x": external_txn_id, "lr": loyalty_ref, "ch": card_hash,
         "s": store_id, "i": item_id, "u": units, "amt": amount_aed, "occ": occurred_at},
    )).fetchone()
    return int(row[0]) if row else 0


async def resolve_pending(
    db: AsyncSession, *, tenant_id: int, batch: int = 500
) -> Dict[str, Any]:
    """Resolve unresolved staged transactions to customers.

    Returns counts by outcome. Deterministic matches link at confidence 1.0;
    probabilistic matches link only above threshold and only when unambiguous;
    everything else is marked unlinked and left for a human or a later, richer
    match — never force-linked.
    """
    pending = (await db.execute(
        text("""SELECT id, loyalty_ref, card_hash, store_id, item_id, occurred_at
                  FROM flywheel_pos_staging
                 WHERE tenant_id = :t AND resolved = FALSE
                 ORDER BY id LIMIT :n"""),
        {"t": tenant_id, "n": batch},
    )).fetchall()

    counts = {"deterministic": 0, "probabilistic": 0, "ambiguous": 0, "unlinked": 0}

    for row in pending:
        staging_id, loyalty_ref, card_hash, store_id, item_id, occurred_at = row
        customer_id, confidence, method, status = await _resolve_one(
            db, tenant_id=tenant_id, loyalty_ref=loyalty_ref, card_hash=card_hash,
            store_id=store_id, occurred_at=occurred_at)

        await db.execute(
            text("""UPDATE flywheel_pos_staging
                       SET resolved = TRUE, matched_customer_id = :c,
                           match_confidence = :conf, match_method = :m
                     WHERE id = :id"""),
            {"c": customer_id, "conf": confidence, "m": method, "id": int(staging_id)},
        )

        # Record/refresh the identity link when we have a key to remember it by,
        # so the next transaction with the same key resolves deterministically.
        key = loyalty_ref or card_hash
        if key:
            await db.execute(
                text("""INSERT INTO flywheel_identity_links
                           (tenant_id, pos_key, customer_id, confidence, method, status)
                        VALUES (:t, :k, :c, :conf, :m, :st)
                        ON CONFLICT (tenant_id, pos_key) DO UPDATE SET
                            customer_id = EXCLUDED.customer_id,
                            confidence = EXCLUDED.confidence,
                            method = EXCLUDED.method, status = EXCLUDED.status"""),
                {"t": tenant_id, "k": key, "c": customer_id, "conf": confidence,
                 "m": method, "st": status},
            )
        counts[method] = counts.get(method, 0) + 1

    logger.info("flywheel.identity resolved tenant=%s %s", tenant_id, counts)
    return {
        "processed": len(pending),
        "outcomes": counts,
        "note": ("Ambiguous and unlinked transactions are LEFT anonymous on "
                 "purpose. A wrong merge corrupts the feature store, the holdout "
                 "and the consent ledger at once — leaving a record unlinked is "
                 "the safer error."),
    }


async def _resolve_one(
    db: AsyncSession, *, tenant_id: int, loyalty_ref: Optional[str],
    card_hash: Optional[str], store_id: Optional[int], occurred_at,
):
    """Resolve one transaction. Returns (customer_id, confidence, method, status)."""
    # --- tier 1: an existing identity link for this key (deterministic) -------
    key = loyalty_ref or card_hash
    if key:
        link = (await db.execute(
            text("""SELECT customer_id FROM flywheel_identity_links
                     WHERE tenant_id = :t AND pos_key = :k AND status = 'linked'"""),
            {"t": tenant_id, "k": key},
        )).fetchone()
        if link and link[0] is not None:
            return int(link[0]), 1.0, "deterministic", "linked"

    # --- tier 1b: loyalty_ref maps directly to a customer's external_ref -------
    if loyalty_ref:
        cust = (await db.execute(
            text("""SELECT id FROM flywheel_customers
                     WHERE tenant_id = :t AND external_ref = :lr"""),
            {"t": tenant_id, "lr": loyalty_ref},
        )).fetchone()
        if cust:
            return int(cust[0]), 1.0, "deterministic", "linked"

    # --- tier 2: probabilistic on store affinity (a deliberately conservative
    # illustrative scorer: a customer whose home store matches the transaction's
    # store is a weak candidate; only a clear, unambiguous winner links) --------
    if store_id is not None:
        candidates = (await db.execute(
            text("""SELECT id,
                           CASE WHEN home_store_id = :s THEN 0.82 ELSE 0.40 END AS score
                      FROM flywheel_customers
                     WHERE tenant_id = :t AND home_store_id = :s
                     ORDER BY id LIMIT 3"""),
            {"t": tenant_id, "s": store_id},
        )).fetchall()
        scored = sorted(((int(c[0]), float(c[1])) for c in candidates),
                        key=lambda x: -x[1])
        if scored:
            best_id, best_score = scored[0]
            second_score = scored[1][1] if len(scored) > 1 else 0.0
            if best_score >= LINK_THRESHOLD:
                if best_score - second_score < AMBIGUITY_MARGIN and len(scored) > 1:
                    # Two customers score comparably — decline to guess.
                    return None, best_score, "ambiguous", "ambiguous"
                return best_id, best_score, "probabilistic", "linked"

    # --- nothing confident enough: stay anonymous -----------------------------
    return None, 0.0, "unlinked", "unlinked"


async def resolution_stats(db: AsyncSession, *, tenant_id: int) -> Dict[str, Any]:
    rows = (await db.execute(
        text("""SELECT match_method, COUNT(*)
                  FROM flywheel_pos_staging
                 WHERE tenant_id = :t AND resolved = TRUE
                 GROUP BY match_method"""),
        {"t": tenant_id},
    )).fetchall()
    by_method = {r[0]: int(r[1]) for r in rows}
    pending = int((await db.execute(
        text("SELECT COUNT(*) FROM flywheel_pos_staging WHERE tenant_id=:t AND resolved=FALSE"),
        {"t": tenant_id},
    )).scalar())
    resolved = sum(by_method.values())
    linked = by_method.get("deterministic", 0) + by_method.get("probabilistic", 0)
    return {
        "resolved": resolved,
        "pending": pending,
        "by_method": by_method,
        "link_rate": round(linked / resolved, 4) if resolved else None,
        "unlinked_rate": round((by_method.get("unlinked", 0) + by_method.get("ambiguous", 0))
                               / resolved, 4) if resolved else None,
    }
