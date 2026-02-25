from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
from datetime import datetime, timezone

from app.config import get_settings, logger
from app.services.database import init_db, close_db
from app.services.redis_client import init_redis, close_redis
from app.services.data_generator import DataGenerator
from app.services.employee_seeder import initialize_employee_system
from app.routes import sales, history, kpis, stream, analytics, auth
from app.routes import ai as ai_routes
from app.routes import inventory, promotions, alerts, admin, reports, monitoring, employees
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
    logger.info("Database initialized")
    
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
    
    logger.info("Sales Dashboard API is ready!")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Sales Dashboard API...")
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await close_db()
    await close_redis()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Sales Dashboard API",
    description="Real-time sales streaming and analytics API",
    version="1.0.0",
    lifespan=lifespan
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

# CORS middleware (innermost - runs first)
cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
