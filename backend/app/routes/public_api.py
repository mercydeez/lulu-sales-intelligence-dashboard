"""
Public REST API (B4) + embeddable, tenant-scoped AI assistant (B5).

Every endpoint here is authenticated by a per-tenant API key (Authorization:
Bearer lsk_... or X-API-Key), and the key *is* the tenant scope — a caller can
only ever read its own tenant's data. The same forecasting/KPI engines that
power the dashboard are exposed here so customers can embed the intelligence
(and the AI assistant) in their own apps with zero paid LLM keys (Ollama →
rule-based fallback).
"""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db, tenant_context
from app.services import api_key_service as keys
from app.config import logger

router = APIRouter()


async def get_api_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> dict:
    """Authenticate a public request by API key and bind the tenant scope."""
    key = x_api_key
    if not key:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            key = auth[len("Bearer "):].strip()
    if not key:
        raise HTTPException(status_code=401, detail="API key required (X-API-Key or Bearer)")

    ctx = await keys.authenticate(db, key)
    if not ctx:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    # Bind the tenant for this request so RLS + helpers scope correctly.
    tenant_context.set(ctx["tenant_id"])
    return ctx


def _require_scope(ctx: dict, scope: str) -> None:
    if scope not in ctx.get("scopes", []) and "*" not in ctx.get("scopes", []):
        raise HTTPException(status_code=403, detail=f"API key missing '{scope}' scope")


class AskRequest(BaseModel):
    question: str
    horizon: int = 14


@router.get("/v1/branding")
async def public_branding(
    ctx: dict = Depends(get_api_context),
    db: AsyncSession = Depends(get_db),
):
    """White-label branding for the authenticated tenant (B4) — so an embedded
    widget can theme itself (name, logo, accent colour) without a dashboard login."""
    from sqlalchemy import text
    row = (await db.execute(text("""
        SELECT name, brand_name, logo_url, accent_color
        FROM tenants WHERE id = :tid
    """), {"tid": ctx["tenant_id"]})).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {
        "tenant_id": ctx["tenant_id"],
        "name": row.name,
        "brand_name": row.brand_name or row.name,
        "logo_url": row.logo_url,
        "accent_color": row.accent_color or "#0f766e",
    }


@router.get("/v1/kpis")
async def public_kpis(
    ctx: dict = Depends(get_api_context),
    db: AsyncSession = Depends(get_db),
):
    """Tenant-scoped KPIs for the authenticated key's tenant."""
    _require_scope(ctx, "read")
    from app.routes.kpis import compute_and_cache_kpis, _serialize_kpi_dates
    data = await compute_and_cache_kpis(db, allowed=None, tenant_id=ctx["tenant_id"])
    return _serialize_kpi_dates(data)


@router.get("/v1/forecast/projection")
async def public_projection(
    horizon: int = 14,
    ctx: dict = Depends(get_api_context),
    db: AsyncSession = Depends(get_db),
):
    """Tenant-scoped forward revenue projection."""
    _require_scope(ctx, "read")
    from app.services.forecast_service import revenue_projection
    horizon = max(7, min(horizon, 60))
    return await revenue_projection(db, tenant_id=ctx["tenant_id"], allowed=None, horizon=horizon)


@router.get("/v1/inventory/reorder-suggestions")
async def public_reorder(
    lead_time_days: int = 7,
    ctx: dict = Depends(get_api_context),
    db: AsyncSession = Depends(get_db),
):
    """Tenant-scoped, forecast-driven reorder suggestions."""
    _require_scope(ctx, "read")
    from app.services.forecast_service import reorder_suggestions
    return await reorder_suggestions(
        db, tenant_id=ctx["tenant_id"], allowed=None,
        lead_time_days=max(1, min(lead_time_days, 60)),
    )


@router.post("/v1/ai/ask")
async def public_ai_ask(
    body: AskRequest,
    ctx: dict = Depends(get_api_context),
    db: AsyncSession = Depends(get_db),
):
    """Embeddable, tenant-scoped AI answer. Uses the configured LLM provider
    (Ollama → OpenAI) when available and always falls back to a data-grounded
    rule-based answer, so it works with zero paid keys."""
    _require_scope(ctx, "read")
    from app.services.ai_assistant import detect_intent
    from app.services.forecast_service import forecast_narrative, revenue_projection

    tenant_id = ctx["tenant_id"]
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    intents = detect_intent(question).get("intents", [])
    horizon = max(7, min(body.horizon, 60))

    # Tenant-scoped, deterministic answers (no cross-tenant leakage).
    if "prediction" in intents:
        answer = await forecast_narrative(db, tenant_id=tenant_id, allowed=None, horizon=horizon)
    else:
        proj = await revenue_projection(db, tenant_id=tenant_id, allowed=None, horizon=horizon)
        if proj.get("status") == "ready":
            answer = (
                f"Over the next {horizon} days this tenant is projected to sell "
                f"~{proj['projected_units']:,} units (~AED {proj['projected_revenue']:,.0f}), "
                f"averaging {proj['avg_daily_units']:,.0f} units/day."
            )
        else:
            answer = ("Not enough history yet to answer quantitatively for this tenant. "
                      "Connect more sales data to unlock forecasts.")

    return {
        "question": question,
        "answer": answer,
        "tenant_id": tenant_id,
        "intents": intents,
    }
