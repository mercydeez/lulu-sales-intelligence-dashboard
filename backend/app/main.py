from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sse_starlette.sse import EventSourceResponse
from contextlib import asynccontextmanager
import asyncio
import traceback
from datetime import datetime, timezone

from app.config import get_settings, logger
from app.services.database import init_db, close_db
from app.services.redis_client import init_redis, close_redis
from app.services.data_generator import DataGenerator
from app.services.employee_seeder import initialize_employee_system
from app.services.migration_runner import run_migrations
from app.services.db_seeder import run_seed
from app.services.cache_warmer import run_cache_warmer
from app.services.forecast_trainer import run_forecast_trainer

from app.routes import sales, history, kpis, stream, analytics, auth
from app.routes import ai as ai_routes
from app.routes import inventory, promotions, alerts, admin, reports, monitoring, employees
from app.routes import data_sources
from app.routes import tenants
from app.routes import public_api, api_keys, webhooks, procurement
from app.routes import findings as findings_routes
from app.routes import security as security_routes
from app.routes import search as search_routes
from app.middleware import (
    RequestIDMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware,
    BodySizeLimitMiddleware, CSRFMiddleware, SessionInvalidationMiddleware
)


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Sales Dashboard API...")
    logger.info(f"Environment: {settings.environment}")
    
    # ── Security validation (fail-fast on insecure production config) ──
    security_issues = settings.validate_security()
    for issue in security_issues:
        if issue.startswith("CRITICAL"):
            logger.error(f"🔒 {issue}")
        else:
            logger.warning(f"🔒 {issue}")
    if security_issues:
        logger.warning(
            "🔒 Resolve the security warnings above before deploying to production."
        )
    else:
        logger.info("🔒 Security configuration validated — no issues found.")
    
    # Observability (Track B): init Sentry only if a DSN is set AND the SDK is
    # installed. No DSN / no SDK => silent no-op, so nothing is forced on the stack.
    if settings.sentry_dsn:
        try:
            import sentry_sdk  # optional dependency
            sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment,
                            traces_sample_rate=0.1)
            logger.info("Sentry error tracking initialized")
        except ImportError:
            logger.warning("SENTRY_DSN set but sentry-sdk is not installed; skipping")
        except Exception as e:
            logger.warning(f"Sentry init failed (continuing without it): {e}")

    await init_db()
    logger.info("Database connection tested")

    # ── One-shot startup work — gated by flags. In production these run as
    # dedicated jobs (app.commands.{seed,migrate}); the API does API only. ──
    if settings.run_seed_on_startup:
        # Seed loads SYNTHETIC demo data (idempotent). Only runs in dev or a
        # DEMO_MODE box; validate_security() blocks it in real production.
        try:
            await run_seed()
            logger.info("Database seed ensured (RUN_SEED_ON_STARTUP=true)")
        except Exception as e:
            logger.error(f"Failed to seed database: {e}")
            raise e
    else:
        logger.info("Startup seed skipped (RUN_SEED_ON_STARTUP=false) — run `python -m app.commands.seed`")

    if settings.run_migrations_on_startup:
        try:
            await run_migrations()
            logger.info("Database migrations applied (RUN_MIGRATIONS_ON_STARTUP=true)")
        except Exception as e:
            logger.error(f"Failed to apply database migrations: {e}")
            raise e
    else:
        logger.info(
            "Startup migrations skipped (RUN_MIGRATIONS_ON_STARTUP=false) — "
            "run the dedicated migrate job (`python -m app.commands.migrate`)"
        )

    await init_redis()
    logger.info("Redis initialized")

    # Employee system (migration + seeding) — gated; non-fatal.
    if settings.run_employee_seeder_on_startup:
        try:
            await initialize_employee_system()
            logger.info("Employee system initialized")
        except Exception as e:
            logger.warning(f"Employee system initialization skipped: {e}")
    else:
        logger.info("Employee seeder skipped (RUN_EMPLOYEE_SEEDER_ON_STARTUP=false)")

    # Refresh per-category prices from the single price source (items.unit_price_aed)
    # so inventory/promotions/procurement never drift from the analytics revenue math.
    try:
        from app.services.data_sync import DataSyncService
        from app.services.database import async_session
        async with async_session() as _s:
            await DataSyncService.refresh_category_costs(_s)
    except Exception as e:
        logger.warning(f"Category cost refresh skipped: {e}")

    # ── Background tasks — gated; only started tasks are tracked/cancelled. ──
    started_tasks: list[tuple[str, asyncio.Task]] = []

    # The synthetic generator writes fake sales — DEMO ONLY.
    if settings.demo_mode and settings.live_generator_enabled:
        generator = DataGenerator()
        started_tasks.append(("data_generator", asyncio.create_task(generator.start())))
        logger.info("Data generator started (DEMO_MODE + LIVE_GENERATOR_ENABLED)")
    else:
        logger.info("Data generator NOT started (demo/live-generator disabled)")

    if settings.run_cache_warmer:
        started_tasks.append(("cache_warmer", asyncio.create_task(run_cache_warmer())))
        logger.info("Cache warmer started")
    else:
        logger.info("Cache warmer disabled (RUN_CACHE_WARMER=false)")

    if settings.run_forecast_trainer:
        started_tasks.append(("forecast_trainer", asyncio.create_task(run_forecast_trainer())))
        logger.info("Forecast trainer started")
    else:
        logger.info("Forecast trainer disabled (RUN_FORECAST_TRAINER=false)")

    logger.info("Sales Dashboard API is ready!")

    yield

    # Shutdown — cancel only the tasks we actually started.
    logger.info("Shutting down Sales Dashboard API...")
    for _name, t in started_tasks:
        t.cancel()
    for _name, t in started_tasks:
        try:
            await t
        except asyncio.CancelledError:
            pass
    await close_db()  # disposes the owner engine AND the RLS engine if present
    await close_redis()
    try:
        from app.services.nl2sql.executor import dispose_sage_engine
        await dispose_sage_engine()
    except Exception:
        pass
    logger.info("Shutdown complete")


# Interactive API docs (/docs, /redoc, /openapi.json) expose the full API
# surface, so they're disabled outside development to avoid info disclosure.
# In production they can be re-enabled deliberately via EXPOSE_API_DOCS=true
# (and should then be protected at the reverse proxy — see config.api_docs_enabled).
_docs_enabled = settings.api_docs_enabled
app = FastAPI(
    title=f"{settings.product_name} API",
    description="Real-time sales streaming and analytics API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

# =============================================================================
# Global Exception Handlers
# =============================================================================

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handle HTTP exceptions with a consistent JSON structure."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "status_code": exc.status_code,
            "message": exc.detail or "An error occurred",
            "path": str(request.url.path),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle request validation errors with field-level detail."""
    errors = []
    for err in exc.errors():
        errors.append({
            "field": " → ".join(str(loc) for loc in err.get("loc", [])),
            "message": err.get("msg", "Invalid value"),
            "type": err.get("type", "value_error"),
        })
    return JSONResponse(
        status_code=422,
        content={
            "error": True,
            "status_code": 422,
            "message": "Validation failed",
            "details": errors,
            "path": str(request.url.path),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all for unhandled exceptions — log full trace, return safe message."""
    logger.error(
        f"Unhandled exception on {request.method} {request.url.path}: "
        f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    )
    # Never leak internal details to the client
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "status_code": 500,
            "message": "Internal server error",
            "path": str(request.url.path),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


# =============================================================================
# Middleware (order matters - first added = last executed)
# =============================================================================

# Security headers (outermost - always applied)
app.add_middleware(SecurityHeadersMiddleware)

# CSRF protection
app.add_middleware(CSRFMiddleware)

# Request body size limit
app.add_middleware(BodySizeLimitMiddleware)

# Session invalidation check (token blacklist)
app.add_middleware(SessionInvalidationMiddleware)

# Rate limiting (Redis-backed)
app.add_middleware(RateLimitMiddleware)

# Request ID tracking and logging
app.add_middleware(RequestIDMiddleware)

# CORS middleware (innermost - runs first).
# Origins are enumerated from settings (never "*"). Methods/headers are listed
# explicitly because the CORS spec forbids "*" wildcards once
# allow_credentials=True — browsers reject credentialed responses that echo "*".
cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
if not cors_origins:
    logger.warning("🔒 No CORS origins configured — cross-origin browser requests will be blocked.")

cors_kwargs = dict(
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID", "Cache-Control"],
    expose_headers=["X-Request-ID", "X-Process-Time", "X-RateLimit-Remaining"],
    max_age=600,
)
# In development, tolerate any localhost/127.0.0.1 origin on any port so authed
# preflights don't 400 when the dev server is reached via 127.0.0.1 instead of
# localhost (or on a non-default port). Production stays locked to the explicit
# allow_origins list above — no wildcard, credentials-safe.
if settings.environment == "development":
    cors_kwargs["allow_origin_regex"] = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
    logger.info("🔓 Dev CORS: localhost/127.0.0.1 origins allowed on any port")

app.add_middleware(CORSMiddleware, **cors_kwargs)

# =============================================================================
# API Routes
# =============================================================================
app.include_router(sales.router, prefix="/api/sales", tags=["Sales"])
app.include_router(history.router, prefix="/api/history", tags=["History"])
app.include_router(kpis.router, prefix="/api/kpis", tags=["KPIs"])
app.include_router(stream.router, prefix="/stream", tags=["Stream"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["Analytics"])
app.include_router(ai_routes.router, prefix="/api/ai", tags=["AI Assistant"])
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(inventory.router, prefix="/api/inventory", tags=["Inventory Management"])
app.include_router(promotions.router, prefix="/api/promotions", tags=["Promotions & Pricing"])
app.include_router(alerts.router, prefix="/api/alerts", tags=["Alerts & Notifications"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(reports.router, prefix="/api/reports", tags=["Reports"])
app.include_router(monitoring.router, prefix="/api/monitoring", tags=["Monitoring"])
app.include_router(employees.router, prefix="/api/employees", tags=["Employees"])
app.include_router(data_sources.router, prefix="/api/data-sources", tags=["Data Sources"])
app.include_router(tenants.router, prefix="/api/tenants", tags=["Tenants"])
app.include_router(api_keys.router, prefix="/api/api-keys", tags=["API Keys"])
app.include_router(webhooks.router, prefix="/api/webhooks", tags=["Webhooks"])
app.include_router(procurement.router, prefix="/api/procurement", tags=["Procurement"])
app.include_router(findings_routes.router, prefix="/api/findings", tags=["Diagnostics"])
app.include_router(security_routes.router, prefix="/api/security", tags=["Security"])
app.include_router(search_routes.router, prefix="/api/search", tags=["Search"])
app.include_router(public_api.router, prefix="/api/public", tags=["Public API"])

# Also mount /api/latest from stream router
@app.get("/api/latest", tags=["Stream"])
async def get_latest_redirect():
    """Redirect to stream latest endpoint"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/stream/latest")


# Handle legacy /api/stream/sales requests - redirect to /stream/sales
@app.get("/api/stream/sales", tags=["Stream"])
async def stream_sales_redirect(request: Request):
    """SSE endpoint for real-time sales streaming (legacy URL support)"""
    from app.routes.stream import event_generator
    return EventSourceResponse(event_generator(request))


@app.get("/health")
async def health_check():
    """
    Health check endpoint.
    Returns: {"status":"healthy","database":"healthy","redis":"healthy","timestamp":"...","version":"1.0.0"}
    """
    from app.services.database import engine
    from app.services.redis_client import get_redis
    from sqlalchemy import text
    
    # Check database
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = "unhealthy"
    
    # Check Redis
    try:
        redis = await get_redis()
        await redis.ping()
        redis_status = "healthy"
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        redis_status = "unhealthy"

    # Overall status
    if db_status == "healthy" and redis_status == "healthy":
        overall_status = "healthy"
    elif db_status == "unhealthy" and redis_status == "unhealthy":
        overall_status = "unhealthy"
    else:
        overall_status = "degraded"

    return {
        "status": overall_status,
        "database": db_status,
        "redis": redis_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "environment": settings.environment
    }


# =============================================================================
# Health / readiness probes (Phase 3)
#   /health/live  — liveness: process up, NO external deps (cheap; keep-warm safe)
#   /health/ready — readiness: DB + Redis + migrations current + config valid
#   /health/deep  — detailed subsystem status (no secrets)
# =============================================================================

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.get("/health/live", tags=["Health"])
async def health_live():
    """Liveness — the process is running. No DB/Redis dependency by design, so an
    orchestrator/keep-warm pinger can hit this cheaply without touching the DB."""
    return {"status": "alive", "timestamp": _now()}


@app.get("/health/ready", tags=["Health"])
async def health_ready():
    """Readiness — only 200 when the app can actually serve: DB + Redis reachable,
    migrations current, and security config valid."""
    from app.services.database import engine
    from app.services.redis_client import get_redis
    from app.services.migration_runner import pending_migrations
    from sqlalchemy import text

    checks: dict[str, str] = {}
    ready = True

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"
        ready = False

    try:
        redis = await get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"
        ready = False

    try:
        pending = await pending_migrations()
        checks["migrations"] = "current" if not pending else f"pending:{len(pending)}"
        if pending:
            ready = False
    except Exception:
        checks["migrations"] = "unknown"
        ready = False

    try:
        settings.validate_security()  # raises only on hard misconfig
        checks["config"] = "ok"
    except Exception:
        checks["config"] = "invalid"
        ready = False

    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "checks": checks, "timestamp": _now()},
    )


@app.get("/health/deep", tags=["Health"])
async def health_deep():
    """Detailed subsystem status for operators. Never includes secrets."""
    from app.services.database import engine
    from app.services.redis_client import get_redis
    from app.services.migration_runner import pending_migrations
    from sqlalchemy import text

    checks: dict[str, object] = {}
    healthy = True

    # Database
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"
        healthy = False

    # Redis (+ best-effort BullMQ queue presence)
    try:
        redis = await get_redis()
        await redis.ping()
        queue = "unknown"
        try:
            keys = await redis.keys("bull:*")
            queue = f"keys:{len(keys)}"
        except Exception:
            pass
        checks["redis"] = "ok"
        checks["worker_queue"] = queue
    except Exception:
        checks["redis"] = "error"
        checks["worker_queue"] = "unknown"
        healthy = False

    # Migrations
    try:
        pending = await pending_migrations()
        checks["migrations"] = "current" if not pending else {"pending": pending}
    except Exception:
        checks["migrations"] = "unknown"

    # Expected tables exist (security_events, findings)
    try:
        async with engine.connect() as conn:
            res = await conn.execute(text(
                "SELECT to_regclass('public.security_events') IS NOT NULL, "
                "to_regclass('public.findings') IS NOT NULL"
            ))
            sec, find = res.fetchone()
        checks["security_events_table"] = bool(sec)
        checks["findings_table"] = bool(find)
    except Exception:
        checks["security_events_table"] = "unknown"
        checks["findings_table"] = "unknown"

    # Data freshness (latest generated sale)
    try:
        async with engine.connect() as conn:
            res = await conn.execute(text("SELECT MAX(created_at) FROM sales_stream_raw"))
            latest = res.scalar()
        checks["latest_stream_sale"] = latest.isoformat() if latest else None
    except Exception:
        checks["latest_stream_sale"] = "unknown"

    return {
        "status": "healthy" if healthy else "degraded",
        "timestamp": _now(),
        "environment": settings.environment,
        "version": "1.0.0",
        "mode": {
            "demo_mode": settings.demo_mode,
            "live_generator_enabled": settings.live_generator_enabled,
            "generator_running": bool(settings.demo_mode and settings.live_generator_enabled),
            "use_rls_role": settings.use_rls_role,
            "external_ai": settings.enable_external_ai,
            "local_ai": settings.enable_local_ai,
        },
        "checks": checks,
    }
