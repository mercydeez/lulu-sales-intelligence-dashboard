"""
Monitoring Routes
Provides endpoints for metrics, health checks, and system status.
"""
from fastapi import APIRouter, Depends, Response, HTTPException
from datetime import datetime
from typing import Dict, Any

from app.config import get_settings, logger
from app.services.metrics import get_metrics
from app.services.database import engine, async_session
from app.services.redis_client import get_redis, cache_get, cache_set
from app.routes.auth import get_current_user, require_role
from sqlalchemy import text


router = APIRouter()
settings = get_settings()


@router.get("/metrics")
async def prometheus_metrics(current_user: dict = Depends(get_current_user)):
    """
    Prometheus metrics endpoint.
    Returns metrics in Prometheus text format for scraping.
    """
    metrics = get_metrics()
    content = metrics.export_prometheus()
    return Response(content=content, media_type="text/plain; charset=utf-8")


@router.get("/metrics/json")
async def metrics_json(current_user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """
    JSON metrics endpoint.
    Returns metrics in JSON format for dashboard consumption.
    """
    metrics = get_metrics()
    return metrics.get_stats()


@router.get("/health/detailed")
async def detailed_health_check(current_user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """
    Detailed health check endpoint.
    Provides comprehensive system status including:
    - Database connectivity and pool status
    - Redis connectivity
    - Application metrics
    - System information
    """
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "environment": settings.environment,
        "checks": {}
    }
    
    # Database check
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT COUNT(*) FROM sales_fact_view"))
            sales_count = result.scalar()
            
            result = await conn.execute(text("SELECT COUNT(*) FROM sales_fact_view WHERE is_streaming = true"))
            streaming_count = result.scalar()
            
        health_status["checks"]["database"] = {
            "status": "healthy",
            "sales_records": sales_count,
            "streaming_records": streaming_count
        }
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        health_status["checks"]["database"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_status["status"] = "degraded"
    
    # Redis check
    try:
        redis = await get_redis()
        info = await redis.info()
        
        health_status["checks"]["redis"] = {
            "status": "healthy",
            "connected_clients": info.get("connected_clients", 0),
            "used_memory_human": info.get("used_memory_human", "unknown"),
            "uptime_in_seconds": info.get("uptime_in_seconds", 0)
        }
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        health_status["checks"]["redis"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_status["status"] = "degraded"
    
    # Application metrics
    try:
        metrics = get_metrics()
        stats = metrics.get_stats()
        health_status["checks"]["application"] = {
            "status": "healthy",
            "uptime_seconds": stats.get("uptime_seconds", 0),
            "requests_in_progress": stats.get("requests_in_progress", 0),
            "total_requests": stats.get("counters", {}).get("http_requests_total", 0)
        }
    except Exception as e:
        logger.error(f"Metrics check failed: {e}")
        health_status["checks"]["application"] = {
            "status": "unknown",
            "error": str(e)
        }
    
    # Determine overall status
    statuses = [check.get("status") for check in health_status["checks"].values()]
    if all(s == "healthy" for s in statuses):
        health_status["status"] = "healthy"
    elif all(s == "unhealthy" for s in statuses):
        health_status["status"] = "unhealthy"
    else:
        health_status["status"] = "degraded"
    
    return health_status


@router.get("/ready")
async def readiness_check() -> Dict[str, str]:
    """
    Kubernetes readiness probe endpoint.
    Returns 200 if the service is ready to receive traffic.
    """
    try:
        # Check database
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        
        # Check Redis
        redis = await get_redis()
        await redis.ping()
        
        return {"status": "ready"}
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        return Response(
            content='{"status": "not_ready", "error": "' + str(e) + '"}',
            status_code=503,
            media_type="application/json"
        )


@router.get("/live")
async def liveness_check() -> Dict[str, str]:
    """
    Kubernetes liveness probe endpoint.
    Returns 200 if the service is alive.
    """
    return {"status": "alive", "timestamp": datetime.utcnow().isoformat()}


@router.get("/public-status")
async def public_status() -> Dict[str, Any]:
    """Public component status for the /status page (CX trust loop — K2,
    docs/product/CX_LOOPS_PLAN.md). Unauthenticated by design; Redis-cached
    60s so a thousand open status tabs cost one probe a minute. Exposes
    component states ONLY — no versions, hosts, or error strings (info-leak
    safe). Always returns 200: the payload carries the health verdict.
    """
    cache_key = "public_status:v1"
    try:
        cached = await cache_get(cache_key)
        if cached:
            return cached
    except Exception:
        pass  # the cache path must never take the status endpoint down

    async def db_ok() -> bool:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def redis_ok() -> bool:
        try:
            r = await get_redis()
            await r.ping()
            return True
        except Exception:
            return False

    database_up = await db_ok()
    cache_up = await redis_ok()
    payload: Dict[str, Any] = {
        "status": "operational" if (database_up and cache_up) else "degraded",
        "components": {
            "api": "operational",  # this handler answered
            "database": "operational" if database_up else "down",
            "cache_stream": "operational" if cache_up else "down",
        },
        "checked_at": datetime.utcnow().isoformat() + "Z",
    }
    if cache_up:
        try:
            await cache_set(cache_key, payload, expire=60)
        except Exception:
            pass
    return payload


@router.get("/residency")
async def data_residency() -> Dict[str, Any]:
    """Public data-residency posture (E5-3) for a `/trust`-style page. Reports the
    configured region, backup region, cross-border policy, external-AI caveat, and
    log retention — region ids + booleans only, NO secrets. Honest: it reports
    exactly what the operator configured, never an unbacked compliance claim.
    Returns 404 when the operator has disabled the public statement."""
    s = get_settings()
    if not getattr(s, "data_residency_statement_enabled", True):
        raise HTTPException(status_code=404, detail="residency_statement_disabled")
    from app.services.data_residency import residency_posture
    payload = residency_posture(s)
    payload["checked_at"] = datetime.utcnow().isoformat() + "Z"
    return payload


@router.get("/forecast-methodology")
async def forecast_methodology() -> Dict[str, Any]:
    """Public forecast methodology + measured accuracy (E7-2).

    "Ramadan-accurate, and we show our error rate." Competitors publish claims;
    this publishes the error bars. Unauthenticated on purpose — a prospect must be
    able to check our arithmetic before trusting us with their data.

    Anonymous by construction: unitless error rates, the baseline we score against,
    and which calendar features are on. No revenue, no store, no tenant, no volume.

    Honesty: Ramadan accuracy is reported ONLY when the back-test window actually
    contained Ramadan dates; otherwise it comes back null with the reason. We do
    not extrapolate a seasonal claim from a season we never measured. A cold cache
    returns `warming`, not a stale or invented number.
    """
    s = get_settings()
    if not getattr(s, "forecast_methodology_public", True):
        raise HTTPException(status_code=404, detail="forecast_methodology_disabled")

    from app.routes.analytics import model_metrics_cache_key
    from app.services.cache import get_cached

    cached = await get_cached(model_metrics_cache_key(s.demo_tenant_id, None, 14))

    if not cached or cached.get("status") != "ready":
        return {
            "status": "warming",
            "reason": "the reference models are still training; no number is published until they are",
            "baseline_model": "seasonal_naive",
            "checked_at": datetime.utcnow().isoformat() + "Z",
        }

    # A strict whitelist. Everything else in the model-metrics payload — revenue,
    # per-store heatmaps, item accuracy — stays private by never being copied here.
    fields = (
        "forecasting_version", "baseline_model",
        "baseline_mape", "baseline_wape",
        "selected_model", "selected_model_mape", "selected_model_wape",
        "wape_improvement_vs_baseline_pct",
        "ramadan_accuracy", "ramadan_mape", "ramadan_wape",
        "ramadan_eval_days", "ramadan_accuracy_reason",
        "calendar_feature_summary", "methodology_note",
    )
    payload: Dict[str, Any] = {k: cached.get(k) for k in fields}
    payload["status"] = "ready"
    payload["dataset"] = "reference tenant (synthetic UAE retail history)"
    payload["checked_at"] = datetime.utcnow().isoformat() + "Z"
    return payload


@router.get("/jwks.json")
async def jwks() -> Dict[str, Any]:
    """Public JSON Web Key Set (E5-6). Publishes the RS256 **public** keys so any
    downstream verifier (worker, public API, another service) can validate tokens
    WITHOUT holding the private signing key — the whole point of moving off the
    shared HS256 secret. Contains public key material only; returns an empty set
    when running legacy HS256 (a symmetric secret is never published). Safe to
    cache; keys change only on rotation."""
    from app.services.jwt_keys import get_key_provider
    return get_key_provider().public_jwks()


@router.get("/stats")
async def system_stats(current_user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """
    System statistics endpoint.
    Returns aggregated statistics about the system.
    """
    stats = {
        "timestamp": datetime.utcnow().isoformat(),
        "database": {},
        "streaming": {},
        "cache": {}
    }
    
    try:
        async with async_session() as session:
            # Database stats
            result = await session.execute(text("""
                SELECT 
                    COUNT(*) as total_sales,
                    COUNT(*) FILTER (WHERE is_streaming = true) as streaming_sales,
                    COUNT(DISTINCT store_id) as active_stores,
                    COUNT(DISTINCT item_id) as active_items,
                    MIN(date) as earliest_date,
                    MAX(date) as latest_date
                FROM sales_fact_view
            """))
            row = result.fetchone()
            
            stats["database"] = {
                "total_sales": row[0] if row else 0,
                "streaming_sales": row[1] if row else 0,
                "active_stores": row[2] if row else 0,
                "active_items": row[3] if row else 0,
                "date_range": {
                    "start": str(row[4]) if row and row[4] else None,
                    "end": str(row[5]) if row and row[5] else None
                }
            }
            
            # Recent streaming stats
            result = await session.execute(text("""
                SELECT 
                    COUNT(*) as count,
                    AVG(sales) as avg_sales,
                    MAX(created_at) as last_generated
                FROM sales_fact_view 
                WHERE is_streaming = true 
                AND created_at > NOW() - INTERVAL '1 hour'
            """))
            row = result.fetchone()
            
            stats["streaming"] = {
                "last_hour_count": row[0] if row else 0,
                "last_hour_avg_sales": float(row[1]) if row and row[1] else 0,
                "last_generated": str(row[2]) if row and row[2] else None
            }
            
    except Exception as e:
        logger.error(f"Failed to get system stats: {e}")
        stats["error"] = str(e)
    
    # Cache stats
    try:
        redis = await get_redis()
        info = await redis.info()
        stats["cache"] = {
            "connected_clients": info.get("connected_clients", 0),
            "used_memory": info.get("used_memory_human", "unknown"),
            "total_keys": info.get("db0", {}).get("keys", 0) if isinstance(info.get("db0"), dict) else 0
        }
    except Exception as e:
        stats["cache"]["error"] = str(e)

    return stats


@router.post("/alerts/test")
async def send_test_alert(user: dict = Depends(require_role("super_admin", "admin"))) -> Dict[str, Any]:
    """Admin-only: emit a TEST alert through the configured webhook so an operator
    can prove the founder-phone path end-to-end (E0-2 acceptance evidence).

    Requires super_admin/admin. Never returns the webhook URL — only whether the
    alert was sent and the alerting provider status. If alerting is disabled or no
    webhook is configured, it reports that honestly instead of sending.
    """
    from app.services.alerting import send_alert, alerting_status

    result = await send_alert(
        title=f"{settings.product_name} test alert",
        message=f"Manual test alert triggered by {user.get('email', 'admin')}.",
        severity="critical",
        check="manual_test",
        status="test",
    )
    return {
        "requested_by": user.get("email"),
        "alerting": alerting_status(),   # {status, provider} — no URL
        "result": result,                # {sent: bool, reason?: str}
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
