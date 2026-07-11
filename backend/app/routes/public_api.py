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
from app.services import api_versioning
from app.config import logger, get_settings


def _ai_evidence(tenant_id: int, row_count: int, grounded: bool) -> dict:
    """Non-sensitive provenance for an AI answer. Never includes raw SQL."""
    s = get_settings()
    return {
        "tenant_scope": tenant_id,
        "rows_examined": row_count,
        "confidence": "high" if grounded and row_count else ("medium" if grounded else "low"),
        "data_disclosure": (
            "Sample/synthetic demo data — not real customer data"
            if s.demo_mode else "This tenant's own data"
        ),
    }


def _expose_sql() -> bool:
    """Raw generated SQL is exposed only in development — never in prod/staging
    (schema/info disclosure on a public, API-key surface)."""
    return get_settings().environment.lower() not in ("production", "prod", "staging")

# E6-6: every route on this router passes through the version lifecycle first.
# Today it is a no-op (v1 is current); once v1 is deprecated it adds Deprecation/
# Sunset headers, and after the sunset date it answers 410 Gone. Discovery
# (`/versions`) carries no version segment and is exempt.
router = APIRouter(dependencies=[Depends(api_versioning.public_api_lifecycle)])


@router.get("/versions")
async def public_api_versions() -> dict:
    """Version discovery — unauthenticated and deliberately unversioned.

    An integrator needs this most at the moment their version stops answering, so
    it must not require the retired version, nor an API key they may have let
    lapse. It exposes no tenant data.
    """
    return {
        "current": api_versioning.PUBLIC_API_VERSION,
        "supported": api_versioning.supported_versions(),
        "policy": get_settings().public_api_policy_url,
    }


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
        from app.services.security_events import record_event
        prefix = key.rsplit("_", 1)[0] if key and "_" in key else None
        await record_event("api_key_invalid", request=request,
                           detail="Public API call with an invalid or revoked API key",
                           evidence={"key_prefix": prefix})
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    # Bind the tenant for this request so RLS + helpers scope correctly.
    tenant_context.set(ctx["tenant_id"])

    # E10-2: the login path refuses an unsupported isolation tier; an API key is
    # the other way into the same data, so it refuses here too. Closing one door
    # and leaving the other open would make the guarantee decorative.
    from app.services import isolation
    await isolation.enforce_tenant_isolation(db, ctx["tenant_id"])

    # B7: per-tenant kill-switch for the whole public API surface. Fail-open when
    # the flag engine is unavailable (a customization must never take the surface
    # down by accident); checked in this shared dependency so every public
    # endpoint inherits it, and BEFORE metering so a refused request does not
    # consume the quota that refused it.
    from app.services.flag_enforcement import flag_allows
    if not await flag_allows(ctx["tenant_id"], "integrations.public_api"):
        raise HTTPException(status_code=403, detail="The public API is disabled for this workspace")

    # E8-3: every authenticated public call is one metered `api_request`. This is
    # the only place the dimension can be counted exactly once per request, and it
    # was previously advertised in the usage summary while nothing ever recorded
    # it — a limit of 10,000 next to a permanent 0.
    #
    # Enforce BEFORE recording: a refused request must not consume the quota that
    # refused it. `/versions` never reaches here, so discovery stays free.
    from app.services.usage_metering import enforce_quota, record_usage
    await enforce_quota(db, ctx["tenant_id"], "api_request")
    await record_usage(ctx["tenant_id"], "api_request",
                       metadata={"path": request.url.path})
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
    from app.services.kpi_service import compute_and_cache_kpis, _serialize_kpi_dates
    data = await compute_and_cache_kpis(db, None, tenant_id=ctx["tenant_id"])
    return _serialize_kpi_dates(data)


@router.get("/v1/forecast/projection")
async def public_projection(
    horizon: int = 14,
    ctx: dict = Depends(get_api_context),
    db: AsyncSession = Depends(get_db),
):
    """Tenant-scoped forward revenue projection."""
    _require_scope(ctx, "read")
    # E8-3: a `forecast_job` is a forecast computed on demand for an external
    # caller. The dashboard's own projection panel is NOT a job — metering our own
    # re-renders would spend a free tenant's 50/month in a few days of browsing.
    from app.services.usage_metering import enforce_quota, record_usage
    await enforce_quota(db, ctx["tenant_id"], "forecast_job")

    from app.services.forecast_service import revenue_projection
    horizon = max(7, min(horizon, 60))
    result = await revenue_projection(db, tenant_id=ctx["tenant_id"], allowed=None, horizon=horizon)
    await record_usage(ctx["tenant_id"], "forecast_job", metadata={"horizon": horizon})
    return result


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


@router.get("/v1/findings")
async def public_findings(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50,
    ctx: dict = Depends(get_api_context),
    db: AsyncSession = Depends(get_db),
):
    """Tenant-scoped diagnostics findings (A3) for the authenticated key — so a
    customer can pull "what's going wrong" into their own tools/Slack."""
    _require_scope(ctx, "read")
    from sqlalchemy import text
    where = ["tenant_id = :tid"]
    params: dict = {"tid": ctx["tenant_id"], "limit": max(1, min(limit, 200))}
    if status in ("open", "acknowledged", "resolved"):
        where.append("status = :status"); params["status"] = status
    if severity in ("low", "medium", "high", "critical"):
        where.append("severity = :severity"); params["severity"] = severity
    rows = (await db.execute(text(
        "SELECT id, rule, category, severity, title, detail, evidence, entity_type, "
        "entity_name, metric_value, status, recommended_action, detected_at "
        f"FROM findings WHERE {' AND '.join(where)} "
        "ORDER BY detected_at DESC LIMIT :limit"
    ), params)).mappings().all()
    return {"data": [dict(r) for r in rows], "count": len(rows)}


@router.post("/v1/ai/ask")
async def public_ai_ask(
    body: AskRequest,
    ctx: dict = Depends(get_api_context),
    db: AsyncSession = Depends(get_db),
):
    """Embeddable, tenant-scoped AI answer. Prefers Sage (NL→SQL over the curated
    tenant views) when an LLM provider is configured, then a data-grounded
    deterministic answer — so it works with zero paid keys."""
    _require_scope(ctx, "read")
    from app.services.ai_assistant import detect_intent
    from app.services.forecast_service import forecast_narrative, revenue_projection
    from app.services.nl2sql import answer_question as sage_answer_question
    from app.services.sage2 import answer_multipart, is_multipart

    tenant_id = ctx["tenant_id"]
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    # Multi-part questions → Sage v2 decompose-route-recompose (consumer scope).
    if is_multipart(question):
        multi = await answer_multipart(question, tenant_id, role="consumer")
        if multi.ok:
            return {"question": question, "answer": multi.answer, "tenant_id": tenant_id,
                    "source": "sage2",
                    "evidence": _ai_evidence(tenant_id, 0, grounded=True)}

    # Single-part → Sage NL→SQL (grounded, tenant-scoped). Falls through when no LLM
    # is configured or the query is rejected — same contract as the dashboard chat.
    sage = await sage_answer_question(question, tenant_id)
    if sage.ok:
        resp = {
            "question": question, "answer": sage.answer, "tenant_id": tenant_id,
            "source": "sage",
            "evidence": _ai_evidence(tenant_id, len(sage.rows or []), grounded=True),
        }
        # Raw SQL is debugging detail — dev only, never on the public prod surface.
        if _expose_sql():
            resp["sql"] = sage.sql
        return resp

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
        "source": "deterministic",
        "evidence": _ai_evidence(tenant_id, 0, grounded=False),
    }
