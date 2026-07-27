"""Stage 5 — the transactional outbox.

THE PROBLEM IT SOLVES. Consider redeeming an offer: decrement stock, convert
reserved budget to spend, write the redemption row, then publish to Redis so the
live dashboard updates. If the process dies between COMMIT and PUBLISH, the money
moved and nobody was told — the dashboard shows stale numbers forever and no
retry exists, because nothing recorded that a publish was owed.

THE FIX. The event is INSERTed in the SAME transaction as the money move. Either
both are committed or neither is. A relay then polls unpublished rows and pushes
them to Redis. A crash means the row is still there, unpublished, and the next
relay pass delivers it.

DELIVERY SEMANTICS: at-least-once. The relay may deliver twice if it dies after
publishing but before marking the row published. That is the correct trade for
dashboard events (a duplicate SSE update is harmless) and is why the FINANCIAL
record lives in `flywheel_budget_ledger`, never in the event stream.

Redis is cache and transport here. It is never the record.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Flywheel's own SSE channels, following the existing `<domain>:stream` convention
# from services/redis_client.py.
CHANNEL_CAMPAIGN = "flywheel:campaign"
CHANNEL_APPROVAL = "flywheel:approval"
CHANNEL_BUDGET = "flywheel:budget"
CHANNEL_OFFER = "flywheel:offer"
CHANNEL_INVENTORY = "flywheel:inventory"
CHANNEL_PROCUREMENT = "flywheel:procurement"

ALL_CHANNELS = (CHANNEL_CAMPAIGN, CHANNEL_APPROVAL, CHANNEL_BUDGET,
                CHANNEL_OFFER, CHANNEL_INVENTORY, CHANNEL_PROCUREMENT)


async def emit(
    db: AsyncSession, *, tenant_id: int, channel: str, event_type: str,
    payload: Dict[str, Any], store_id: Optional[int] = None,
    campaign_id: Optional[int] = None,
) -> int:
    """Record an event for later publication. Call INSIDE the business
    transaction — that co-commit is the entire point of this module.

    `store_id` and `campaign_id` are stored as columns (not just inside the
    payload) so the relay can filter by scope without parsing JSON, and so a
    subscriber can never receive an event for a store they cannot access.
    """
    # Carry the active trace onto the event so the async tail of a decision (the
    # relayed event) joins back to its origin in the decision timeline. Imported
    # locally to avoid a module-load cycle (trace has no outbox dependency).
    from app.services.flywheel import trace
    row = (await db.execute(
        text("""INSERT INTO flywheel_outbox
                   (tenant_id, channel, event_type, payload, store_id, campaign_id,
                    trace_id)
                VALUES (:t, :ch, :et, CAST(:p AS JSONB), :s, :c, :trace)
                RETURNING id"""),
        {"t": tenant_id, "ch": channel, "et": event_type,
         "p": json.dumps(payload, default=str), "s": store_id, "c": campaign_id,
         "trace": trace.current_trace_id()},
    )).fetchone()
    return int(row[0])


async def relay_once(db: AsyncSession, *, batch_size: int = 100) -> Dict[str, Any]:
    """Publish one batch of pending events.

    `FOR UPDATE SKIP LOCKED` lets several relay workers run concurrently without
    publishing the same row twice — each grabs a disjoint batch instead of
    blocking on the same head-of-queue rows.

    A publish failure is recorded on the row (attempts, last_error) and left
    unpublished so the next pass retries it, rather than being dropped.
    """
    rows = (await db.execute(
        text("""SELECT id, tenant_id, channel, event_type, payload, store_id, campaign_id
                  FROM flywheel_outbox
                 WHERE published = FALSE
                 ORDER BY id
                 LIMIT :n
                 FOR UPDATE SKIP LOCKED"""),
        {"n": batch_size},
    )).fetchall()

    if not rows:
        return {"published": 0, "failed": 0}

    from app.services import redis_client

    published: List[int] = []
    failed = 0

    for row_id, tenant_id, channel, event_type, payload, store_id, campaign_id in rows:
        envelope = {
            "event": event_type,
            "tenant_id": int(tenant_id),
            "store_id": store_id,
            "campaign_id": campaign_id,
            "data": payload,
        }
        try:
            client = getattr(redis_client, "redis_client", None)
            if client is None:
                # Redis is down. Leave the row pending — this is exactly the
                # case the outbox exists for. Do NOT mark it published.
                failed += 1
                continue
            await client.publish(channel, json.dumps(envelope, default=str))
            published.append(int(row_id))
        except Exception as exc:
            failed += 1
            await db.execute(
                text("""UPDATE flywheel_outbox
                           SET attempts = attempts + 1, last_error = :e
                         WHERE id = :i"""),
                {"e": str(exc)[:500], "i": int(row_id)},
            )
            logger.warning("flywheel.outbox publish failed id=%s (%s)", row_id, exc)

    if published:
        await db.execute(
            text("""UPDATE flywheel_outbox
                       SET published = TRUE, published_at = now()
                     WHERE id = ANY(:ids)"""),
            {"ids": published},
        )

    return {"published": len(published), "failed": failed}


async def relay_loop(interval_seconds: float = 2.0) -> None:
    """Background relay, started from the app lifespan.

    Owns its own session per pass (`async_session`, the owner engine) because it
    is cross-tenant infrastructure, not a request. Never raises: a relay that
    dies on a transient DB error would silently stop all live updates, so every
    pass is individually guarded and the loop continues.
    """
    from app.services.database import async_session

    logger.info("flywheel.outbox relay started (interval=%ss)", interval_seconds)
    while True:
        try:
            async with async_session() as db:
                result = await relay_once(db)
                await db.commit()
            if result["published"]:
                logger.debug("flywheel.outbox relayed %s event(s)", result["published"])
        except asyncio.CancelledError:
            logger.info("flywheel.outbox relay stopping")
            raise
        except Exception as exc:
            logger.warning("flywheel.outbox relay pass failed (%s) — continuing", exc)
        await asyncio.sleep(interval_seconds)


async def pending_count(db: AsyncSession, tenant_id: Optional[int] = None) -> int:
    """Unpublished events — a health signal. A number that climbs means the
    relay is stuck or Redis is down, and live dashboards are lying."""
    clause = "AND tenant_id = :t" if tenant_id else ""
    params = {"t": tenant_id} if tenant_id else {}
    return int((await db.execute(
        text(f"SELECT COUNT(*) FROM flywheel_outbox WHERE published = FALSE {clause}"),
        params,
    )).scalar() or 0)
