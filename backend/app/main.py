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
    
    await init_db()
    logger.info("Database connection tested")

    # Seed base schema + historical data (portable; works on managed Postgres
    # that can't run the docker-entrypoint init.sql). Idempotent.
    try:
        await run_seed()
        logger.info("Database seed ensured")
    except Exception as e:
        logger.error(f"Failed to seed database: {e}")
        raise e

    try:
        await run_migrations()
        logger.info("Database migrations applied successfully")
    except Exception as e:
        logger.error(f"Failed to apply database migrations: {e}")
        # In production, we might want to exit, but let's log it and raise to fail startup if critical.
        raise e

    
    await init_redis()
    logger.info("Redis initialized")
    
    # Initialize employee system (migration + seeding)
    try:
        await initialize_employee_system()
        logger.info("Employee system initialized")
    except Exception as e:
        logger.warning(f"Employee system initialization skipped: {e}")
    
    # Start the data generator background task
    generator = DataGenerator()
    task = asyncio.create_task(generator.start())
    logger.info("Data generator started")

    # Start the cache warmer so the heavy dashboard queries are always hot
    warmer_task = asyncio.create_task(run_cache_warmer())
    logger.info("Cache warmer started")

    # Start the forecast trainer so Forecast Lab models are trained offline and
    # served from cache (never trained on the request path)
    trainer_task = asyncio.create_task(run_forecast_trainer())
    logger.info("Forecast trainer started")

    logger.info("Sales Dashboard API is ready!")

    yield

    # Shutdown
    logger.info("Shutting down Sales Dashboard API...")
    task.cancel()
    warmer_task.cancel()
    trainer_task.cancel()
    for t in (task, warmer_task, trainer_task):
        try:
            await t
        except asyncio.CancelledError:
            pass
    from app.services.queue import close_queues
    await close_queues()
    from app.services.sage.executor import dispose_engine
    await dispose_engine()
    await close_db()
    await close_redis()
    logger.info("Shutdown complete")


app = FastAPI(
    title=f"{settings.product_name} API",
    description="Real-time sales streaming and analytics API",
    version="1.0.0",
    lifespan=lifespan
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
