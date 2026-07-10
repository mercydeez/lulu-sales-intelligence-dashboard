"""E8-2 — payment gateway routes. Mounted at /api/payments.

Creating an intent is tenant-admin authenticated. The webhook is PUBLIC (the
gateway posts it with no session) and authenticated by its signature instead — an
unverified webhook is recorded but never settles anything.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db, async_session
from app.routes.auth import get_current_user
from app.services import payments
from app.config import logger

router = APIRouter(tags=["Payments"])


def _require_admin(user: dict) -> None:
    if user.get("role") not in ("super_admin", "admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin role required")


class IntentRequest(BaseModel):
    invoice_id: int
    provider: str = Field("mock", pattern="^(mock|telr|paytabs)$")
    return_url: Optional[str] = None


@router.get("/providers")
async def providers(user: dict = Depends(get_current_user)):
    """Which gateways are recognised / configured / usable — honest status."""
    _require_admin(user)
    return {"providers": payments.provider_status()}


@router.post("/intents", status_code=201)
async def create_intent(body: IntentRequest, user: dict = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    """Create a hosted-checkout payment intent for an invoice. Returns a checkout
    URL. Never settles — settlement is webhook-only."""
    _require_admin(user)
    tenant_id = user.get("tenant_id") or 1
    intent, err = await payments.create_payment_session(
        db, tenant_id=tenant_id, invoice_id=body.invoice_id, provider=body.provider,
        created_by=user.get("email") or "admin", return_url=body.return_url)
    if err:
        # A refused/unconfigured provider is a 422 (well-formed request, not usable);
        # a missing invoice is a 404.
        code = 404 if "not found" in err.lower() else 422
        raise HTTPException(status_code=code, detail=err)
    from app.services.security_events import record_event
    await record_event("payment_intent_created", category="audit", severity="low",
                       tenant_id=tenant_id, actor_user_id=user.get("id"),
                       actor_email=user.get("email"),
                       detail=f"Payment intent {intent['intent_id']} via {body.provider} for invoice {body.invoice_id}")
    return intent


@router.get("/intents/{intent_id}")
async def get_intent(intent_id: int, user: dict = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    _require_admin(user)
    tenant_id = user.get("tenant_id") or 1
    row = (await db.execute(text("""
        SELECT id, invoice_id, provider, amount_aed, currency, status, external_ref,
               checkout_url, failure_reason, created_at, updated_at
          FROM payment_intents WHERE id = :id AND tenant_id = :t
    """), {"id": intent_id, "t": tenant_id})).mappings().fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Payment intent not found")
    d = dict(row)
    for k in ("created_at", "updated_at"):
        d[k] = d[k].isoformat() if d.get(k) else None
    d["amount_aed"] = float(d["amount_aed"]) if d["amount_aed"] is not None else None
    return d


@router.post("/webhook/{provider}")
async def webhook(provider: str, request: Request):
    """Gateway webhook receiver — PUBLIC, authenticated by signature, not a session.

    The signature is verified inside handle_webhook; an unverified event is recorded
    for audit but never settles a payment. Always returns 200 with a status so the
    gateway does not retry-storm on our processing outcome.
    """
    if provider not in payments.ALL_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown payment provider")
    raw = await request.body()
    signature = (request.headers.get("X-Signature")
                 or request.headers.get("Signature")
                 or request.headers.get("X-PayTabs-Signature"))
    async with async_session() as db:
        try:
            result = await payments.handle_webhook(db, provider, raw, signature)
        except Exception as e:
            logger.error(f"[payments] webhook processing error ({provider}): {e}")
            raise HTTPException(status_code=500, detail="Webhook processing failed")
    return result
