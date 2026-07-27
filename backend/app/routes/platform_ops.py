"""Platform Console — Ops & Readiness panel (developers-only). Mounted at /api/admin.

One endpoint aggregates the platform's HONEST operational status — every section
comes from the subsystem's own status function (payments.provider_status,
pos_connectors.vendor_status, einvoicing.is_provider_*, health_checks heartbeats),
never from a hand-maintained "it's fine" table. Two guarded ops actions (demo
reset, cache flush) are audited via security_events.

Honesty rules this module enforces:
  * Each status section is independently guarded — one broken subsystem reports
    {"error": "<exception class name>"} for its section instead of 500ing the
    whole panel. Class name ONLY: exception TEXT can carry paths/DSNs.
  * The security section exposes COUNTS of validate_security() warnings, never
    the warning strings themselves (see _section note inside ops_status).
  * Destructive actions record a security event with the acting developer.

Access: `require_platform_developer` on every endpoint — this is a cross-tenant
operator surface; tenant super_admins are refused (see services/platform_access).
"""
from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.config import get_settings
from app.services.platform_access import require_platform_developer
from app.services.security_events import record_event

router = APIRouter(tags=["Platform Ops"])


# ---------------------------------------------------------------------------
# Status aggregation helpers
# ---------------------------------------------------------------------------
async def _section(probe: Callable[[], Union[Any, Awaitable[Any]]]) -> Any:
    """Run one status probe; a broken subsystem yields {"error": <class name>}
    for its section instead of failing the whole panel. Class name ONLY — the
    exception TEXT is never returned, it can interpolate paths/DSNs."""
    try:
        out = probe()
        if inspect.isawaitable(out):
            out = await out
        return out
    except Exception as e:  # noqa: BLE001 — the panel must survive any subsystem
        return {"error": type(e).__name__}


async def _db_alive() -> bool:
    """Cheap liveness boolean — SELECT 1 on the owner session."""
    from app.services.database import async_session

    async with async_session() as session:
        await session.execute(text("SELECT 1"))
    return True


async def _redis_alive() -> bool:
    """Cheap liveness boolean — PING on the shared client."""
    from app.services import redis_client

    r = await redis_client.get_redis()
    if r is None:
        return False
    await r.ping()
    return True


async def _worker_status() -> Dict[str, Any]:
    """Both worker heartbeats, via the existing health_checks parsers (which
    read the Redis keys — including health:worker:singletons — json-parse them
    with parse_worker_heartbeat, and degrade to 'unknown', never raising)."""
    from app.services import health_checks, redis_client

    r = await redis_client.get_redis()
    return {
        "diagnostics": await health_checks.check_worker_heartbeat(r),
        "singletons": await health_checks.check_singletons_heartbeat(r),
    }


@router.get("/dev/ops/status")
async def ops_status(user: dict = Depends(require_platform_developer)) -> Dict[str, Any]:
    """Aggregate honest operational status for the Ops & Readiness panel.

    Every section is wrapped in _section so one broken subsystem never 500s
    the whole panel.
    """

    def _payments():
        from app.services.payments import provider_status
        return provider_status()

    def _pos():
        from app.services.pos_connectors import vendor_status
        return vendor_status()

    def _einvoicing():
        from app.services import einvoicing
        return {
            p: {
                "implemented": einvoicing.is_provider_implemented(p),
                "available": einvoicing.is_provider_available(p),
            }
            for p in sorted(einvoicing.ALL_PROVIDERS)
        }

    def _quotas():
        return {"enforcement_on": bool(get_settings().enforce_usage_quotas)}

    def _security():
        # validate_security() returns warning STRINGS. NEVER return them to the
        # panel: they can interpolate exception text — config.py's RS256 branch
        # does f"...failed to load/sign: {e}", which can carry filesystem paths
        # or DSNs. Expose ONLY counts; the strings stay in the server logs.
        w = get_settings().validate_security()
        return {
            "warnings": len(w),
            "critical": sum(1 for s in w if s.lower().startswith("critical")),
        }

    def _environment():
        s = get_settings()
        return {"environment": s.environment, "demo_mode": bool(s.demo_mode)}

    async def _db():
        try:
            return await _db_alive()
        except Exception:  # noqa: BLE001 — liveness boolean, never raises
            return False

    async def _redis():
        try:
            return await _redis_alive()
        except Exception:  # noqa: BLE001 — liveness boolean, never raises
            return False

    # environment + demo_mode are surfaced FLAT at the top level (the console UI
    # reads status.environment as a string and status.demo_mode as a bool), not
    # nested under an "environment" section.
    env = await _section(_environment)
    return {
        "payments": await _section(_payments),
        "pos": await _section(_pos),
        "einvoicing": await _section(_einvoicing),
        "quotas": await _section(_quotas),
        "security": await _section(_security),
        "environment": env.get("environment") if isinstance(env, dict) else None,
        "demo_mode": env.get("demo_mode") if isinstance(env, dict) else None,
        "worker": await _section(_worker_status),
        "db": await _section(_db),
        "redis": await _section(_redis),
    }


# ---------------------------------------------------------------------------
# Guarded ops actions — both audited via record_event.
# ---------------------------------------------------------------------------
class DemoResetRequest(BaseModel):
    """Optional override of the retention window (hours). None = configured default."""
    retain_hours: Optional[int] = Field(None, ge=0, le=24 * 365)


@router.post("/dev/ops/demo-reset")
async def demo_reset(
    body: Optional[DemoResetRequest] = None,
    user: dict = Depends(require_platform_developer),
) -> Dict[str, Any]:
    """Delete aged synthetic sales from the demo tenant, now.

    reset_demo_tenant self-guards: it verifies the target tenant's slug is
    'demo' in the DB and only deletes `is_synthetic` rows — a real tenant's
    data is unreachable from here. Still a destructive action, so it is
    audited (severity high) with the acting developer.
    """
    from app.services.demo_reset import DemoResetRefused, reset_demo_tenant

    retain_hours = body.retain_hours if body is not None else None
    effective_retain = (
        retain_hours if retain_hours is not None
        else get_settings().demo_reset_retain_hours
    )
    try:
        deleted = await reset_demo_tenant(retain_hours=retain_hours)
    except DemoResetRefused as e:
        # The safety check tripped (target is not the demo tenant) — nothing
        # was deleted. Audit the refused attempt, then report it honestly.
        await record_event(
            "ops_demo_reset_refused", category="audit", severity="high",
            actor_user_id=user.get("id"), actor_email=user.get("email"),
            detail=f"Platform Console demo reset REFUSED: {e}",
        )
        raise HTTPException(status_code=409, detail=str(e))

    await record_event(
        "ops_demo_reset", category="audit", severity="high",
        actor_user_id=user.get("id"), actor_email=user.get("email"),
        detail=(
            f"Platform Console demo reset: {deleted} synthetic rows deleted "
            f"(retain_hours={effective_retain})"
        ),
    )
    return {"deleted": deleted, "retain_hours": effective_retain}


class CacheFlushRequest(BaseModel):
    scope: str = Field(..., pattern="^(inventory|promotions|alerts|all)$")


@router.post("/dev/ops/cache-flush")
async def cache_flush(
    body: CacheFlushRequest,
    user: dict = Depends(require_platform_developer),
) -> Dict[str, List[str]]:
    """Flush the Redis response caches for one domain (or all three)."""
    from app.services import cache

    scopes = ["inventory", "promotions", "alerts"] if body.scope == "all" else [body.scope]
    flushed: List[str] = []
    for scope in scopes:
        # All three invalidators are async (they await delete_cached).
        await getattr(cache, f"invalidate_{scope}_cache")()
        flushed.append(scope)

    await record_event(
        "ops_cache_flush", category="audit", severity="medium",
        actor_user_id=user.get("id"), actor_email=user.get("email"),
        detail=f"Platform Console cache flush: {', '.join(flushed)}",
    )
    return {"flushed": flushed}
