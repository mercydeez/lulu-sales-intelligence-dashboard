"""
Outbound webhook service (B4).

Tenants register HTTPS endpoints + the events they want; `dispatch_event` POSTs
a signed JSON payload to every active, subscribed endpoint for a tenant. Each
delivery carries an HMAC-SHA256 signature (`X-Webhook-Signature: sha256=<hex>`) over
the exact request body so receivers can verify authenticity with their secret.

Delivery is best-effort and fire-and-forget — a slow or failing receiver must
never block the request/stream path that produced the event.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import logger
from app.services.database import async_session

SIGNATURE_HEADER = "X-Webhook-Signature"
DELIVERY_TIMEOUT = 5.0


def generate_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def sign_payload(secret: str, body: bytes) -> str:
    """HMAC-SHA256 of the raw body, hex-encoded — the value receivers recompute."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, body: bytes, signature: str) -> bool:
    """Constant-time check a receiver would run. Accepts the bare hex or the
    `sha256=<hex>` header form."""
    expected = sign_payload(secret, body)
    sig = signature.split("=", 1)[1] if signature.startswith("sha256=") else signature
    return hmac.compare_digest(expected, sig)


def _subscribed(events: List[str], event: str) -> bool:
    return "*" in events or event in events


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
async def create_webhook(
    db: AsyncSession, tenant_id: int, url: str,
    events: Optional[List[str]] = None, description: Optional[str] = None,
    created_by: Optional[int] = None,
) -> Dict:
    secret = generate_secret()
    row = (await db.execute(text("""
        INSERT INTO tenant_webhooks (tenant_id, url, secret, events, description, created_by)
        VALUES (:tenant_id, :url, :secret, :events, :description, :created_by)
        RETURNING id, created_at
    """), {
        "tenant_id": tenant_id, "url": url, "secret": secret,
        "events": events or ["*"], "description": description, "created_by": created_by,
    })).fetchone()
    await db.commit()
    return {
        "id": row.id, "url": url, "events": events or ["*"],
        "description": description,
        "secret": secret,   # shown so the receiver can be configured to verify
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def list_webhooks(db: AsyncSession, tenant_id: int) -> List[Dict]:
    rows = (await db.execute(text("""
        SELECT id, url, events, description, active, last_delivery_at,
               last_status, failure_count, created_at
        FROM tenant_webhooks WHERE tenant_id = :tid ORDER BY created_at DESC
    """), {"tid": tenant_id})).fetchall()
    return [{
        "id": r.id, "url": r.url, "events": list(r.events) if r.events else [],
        "description": r.description, "active": r.active,
        "last_delivery_at": r.last_delivery_at.isoformat() if r.last_delivery_at else None,
        "last_status": r.last_status, "failure_count": int(r.failure_count or 0),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]


async def delete_webhook(db: AsyncSession, tenant_id: int, webhook_id: int) -> bool:
    res = await db.execute(text(
        "DELETE FROM tenant_webhooks WHERE id = :id AND tenant_id = :tid"
    ), {"id": webhook_id, "tid": tenant_id})
    await db.commit()
    return (res.rowcount or 0) > 0


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------
async def _deliver(url: str, secret: str, body: bytes) -> int:
    import httpx
    headers = {
        "Content-Type": "application/json",
        SIGNATURE_HEADER: f"sha256={sign_payload(secret, body)}",
        "User-Agent": "Foresia-Webhooks/1.0",
    }
    async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT) as client:
        resp = await client.post(url, content=body, headers=headers)
        return resp.status_code


async def dispatch_event(tenant_id: int, event: str, data: Dict) -> int:
    """POST a signed `{event, tenant_id, data, sent_at}` payload to every active,
    subscribed endpoint for the tenant. Returns the number of endpoints attempted.
    Best-effort: per-endpoint failures are logged, never raised."""
    async with async_session() as db:
        rows = (await db.execute(text("""
            SELECT id, url, secret, events FROM tenant_webhooks
            WHERE tenant_id = :tid AND active = TRUE
        """), {"tid": tenant_id})).fetchall()

        targets = [r for r in rows if _subscribed(list(r.events) if r.events else ["*"], event)]
        if not targets:
            return 0

        payload = {
            "event": event,
            "tenant_id": tenant_id,
            "data": data,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }
        body = json.dumps(payload, default=str).encode("utf-8")

        attempted = 0
        for r in targets:
            attempted += 1
            try:
                status = await _deliver(r.url, r.secret, body)
                await db.execute(text("""
                    UPDATE tenant_webhooks
                    SET last_delivery_at = :now, last_status = :status,
                        failure_count = CASE WHEN :status >= 400
                                             THEN failure_count + 1 ELSE 0 END
                    WHERE id = :id
                """), {"now": datetime.now(timezone.utc), "status": status, "id": r.id})
            except Exception as e:
                logger.warning(f"Webhook delivery to {r.url} failed: {e}")
                await db.execute(text("""
                    UPDATE tenant_webhooks
                    SET last_delivery_at = :now, failure_count = failure_count + 1
                    WHERE id = :id
                """), {"now": datetime.now(timezone.utc), "id": r.id})
        await db.commit()
        return attempted


def dispatch_event_background(tenant_id: int, event: str, data: Dict) -> None:
    """Fire-and-forget dispatch for domain events (procurement, alerts).

    Preferred path: enqueue a durable `webhook` job so the Node worker fans out
    to subscribed endpoints and retries each delivery with exponential backoff.
    Fallback (queue disabled/unavailable, or no running loop): the original
    in-process best-effort delivery, so producers still work without the worker.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # no running loop (sync context) — skip

    async def _enqueue_or_inprocess() -> None:
        from app.services.queue import enqueue, Q_WEBHOOK
        job_id = await enqueue(
            Q_WEBHOOK, "dispatch",
            {"tenant_id": tenant_id, "event": event, "data": data},
        )
        if job_id is None:
            # Queue off/unavailable — deliver in-process so nothing is lost.
            await dispatch_event(tenant_id, event, data)

    loop.create_task(_enqueue_or_inprocess())
