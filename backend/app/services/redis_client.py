import redis.asyncio as redis
import json
from typing import Optional, Any
from app.config import get_settings, logger

settings = get_settings()

redis_client: Optional[redis.Redis] = None
pubsub: Optional[redis.client.PubSub] = None

CHANNEL_SALES_STREAM = "sales:stream"
CHANNEL_PREDICTIONS = "predictions:update"
CHANNEL_ALERTS_STREAM = "alerts:stream"
CHANNEL_INVENTORY_STREAM = "inventory:stream"
CHANNEL_SECURITY_STREAM = "security:stream"
CHANNEL_OPERATIONS_STREAM = "operations:stream"


async def init_redis():
    """Initialize Redis connection.

    DEGRADES INSTEAD OF REFUSING TO BOOT. Every publisher and cache helper in
    this module is already written `if redis_client:` — a Redis-less runtime is
    a supported state, and the session middleware fails open by design. Only
    this function ever made Redis a hard startup dependency, which meant a
    deployment with no Redis (a free tier, a first pilot) could not start at all
    even though the app is built to run without it.

    On failure the client is left as None so those guards stay honest — a
    half-open client that raises on every publish would be worse than none —
    and the failure is logged loudly. /health reports redis separately, so a
    degraded deployment is visible rather than silent.
    """
    global redis_client, pubsub
    try:
        client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True
        )
        # from_url is lazy; force a real connection so we learn NOW whether this
        # deployment actually has Redis rather than at the first publish.
        await client.ping()
        channel = client.pubsub()
        await channel.subscribe(CHANNEL_SALES_STREAM)
        redis_client, pubsub = client, channel
    except Exception as exc:
        redis_client, pubsub = None, None
        logger.warning(
            "Redis unavailable (%s) — starting in DEGRADED mode: live streams, "
            "caching and rate limiting are disabled. Postgres remains the source "
            "of truth, so no financial or inventory state is affected.", exc)


async def close_redis():
    """Close Redis connection"""
    global redis_client, pubsub
    if pubsub:
        await pubsub.unsubscribe(CHANNEL_SALES_STREAM)
        await pubsub.close()
    if redis_client:
        await redis_client.close()


async def publish_sale(sale_data: dict):
    """Publish new sale to Redis channel"""
    if redis_client:
        await redis_client.publish(
            CHANNEL_SALES_STREAM,
            json.dumps(sale_data, default=str)
        )


async def publish_alert(alert_data: dict):
    """Publish new alert to Redis channel"""
    if redis_client:
        await redis_client.publish(
            CHANNEL_ALERTS_STREAM,
            json.dumps(alert_data, default=str)
        )


async def publish_inventory_update(inventory_data: dict):
    """Publish inventory update to Redis channel"""
    if redis_client:
        await redis_client.publish(
            CHANNEL_INVENTORY_STREAM,
            json.dumps(inventory_data, default=str)
        )


async def publish_security_event(event_data: dict):
    """Publish a security event to the Redis channel for live SOC dashboards."""
    if redis_client:
        await redis_client.publish(
            CHANNEL_SECURITY_STREAM,
            json.dumps(event_data, default=str)
        )


async def publish_operations_event(event_data: dict):
    """Publish an Operations Copilot status change (run/proposal transition) for
    the live queue. Fire-and-forget: the durable record is in Postgres, so a
    missed publish only delays a UI refresh, never loses an audit event."""
    if redis_client:
        await redis_client.publish(
            CHANNEL_OPERATIONS_STREAM,
            json.dumps(event_data, default=str)
        )


async def get_redis() -> redis.Redis:
    """Get Redis client"""
    return redis_client


async def cache_set(key: str, value: Any, expire: int = 3600):
    """Set cache with expiration"""
    if redis_client:
        await redis_client.set(key, json.dumps(value, default=str), ex=expire)


async def cache_get(key: str) -> Optional[Any]:
    """Get cached value"""
    if redis_client:
        value = await redis_client.get(key)
        if value:
            return json.loads(value)
    return None
