"""
Webhook management (B4). Authenticated, tenant-scoped CRUD for outbound webhook
endpoints, plus a test-ping. Admin role only; a tenant manages only its own
endpoints. The signing secret is returned at creation so the receiver can be
configured to verify deliveries.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db
from app.services import webhook_service as wh
from app.routes.auth import get_current_user

router = APIRouter()


class WebhookCreate(BaseModel):
    url: str = Field(..., min_length=8, max_length=2000)
    events: Optional[List[str]] = None
    description: Optional[str] = Field(None, max_length=200)


def _require_admin(user: dict) -> None:
    if user.get("role") not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Admin role required to manage webhooks")


def _validate_url(url: str) -> None:
    if not (url.startswith("https://") or url.startswith("http://")):
        raise HTTPException(status_code=400, detail="Webhook URL must be http(s)")


@router.post("")
async def create_webhook(
    body: WebhookCreate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    _validate_url(body.url)
    return await wh.create_webhook(
        db, user.get("tenant_id") or 1, body.url,
        events=body.events, description=body.description, created_by=user.get("id"),
    )


@router.get("")
async def list_webhooks(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    return {"webhooks": await wh.list_webhooks(db, user.get("tenant_id") or 1)}


@router.get("/{webhook_id}/deliveries")
async def webhook_deliveries(
    webhook_id: int,
    limit: int = 20,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Recent delivery attempts for one webhook — the delivery log the Developer
    Portal shows for debugging integrations."""
    _require_admin(user)
    return {"deliveries": await wh.list_deliveries(db, user.get("tenant_id") or 1, webhook_id, limit)}


@router.delete("/{webhook_id}")
async def delete_webhook(
    webhook_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    ok = await wh.delete_webhook(db, user.get("tenant_id") or 1, webhook_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return {"success": True, "webhook_id": webhook_id}


@router.post("/test")
async def test_webhooks(
    user: dict = Depends(get_current_user),
):
    """Send a signed `webhook.test` event to the tenant's active endpoints."""
    _require_admin(user)
    tenant_id = user.get("tenant_id") or 1
    attempted = await wh.dispatch_event(
        tenant_id, "webhook.test", {"message": "Hello from Retail IQ"}
    )
    return {"dispatched_to": attempted}
