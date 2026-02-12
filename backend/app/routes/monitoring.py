"""
Monitoring Routes
Provides endpoints for metrics, health checks, and system status.
"""
from fastapi import APIRouter, Response
from datetime import datetime
from typing import Dict, Any

from app.config import get_settings, logger
from app.services.metrics import get_metrics
from app.services.database import engine, async_session
from app.services.redis_client import get_redis
from sqlalchemy import text


router = APIRouter()
settings = get_settings()


@router.get("/metrics")
async def prometheus_metrics():
    """
    Prometheus metrics endpoint.
    Returns metrics in Prometheus text format for scraping.
    """
    metrics = get_metrics()
    content = metrics.export_prometheus()
    return Response(content=content, media_type="text/plain; charset=utf-8")


@router.get("/metrics/json")
async def metrics_json() -> Dict[str, Any]:
    """
    JSON metrics endpoint.
    Returns metrics in JSON format for dashboard consumption.
    """
    metrics = get_metrics()
    return metrics.get_stats()


@router.get("/health/detailed")
async def detailed_health_check() -> Dict[str, Any]:
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
            result = await conn.execute(text("SELECT COUNT(*) FROM sales"))
            sales_count = result.scalar()
            
            result = await conn.execute(text("SELECT COUNT(*) FROM sales WHERE is_streaming = true"))
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


@router.get("/stats")
async def system_stats() -> Dict[str, Any]:
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
                FROM sales
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
                FROM sales 
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
