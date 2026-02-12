import redis.asyncio as redis
import json
from typing import Optional, Any
from app.config import get_settings

settings = get_settings()

redis_client: Optional[redis.Redis] = None
pubsub: Optional[redis.client.PubSub] = None

CHANNEL_SALES_STREAM = "sales:stream"
CHANNEL_PREDICTIONS = "predictions:update"
CHANNEL_ALERTS_STREAM = "alerts:stream"
CHANNEL_INVENTORY_STREAM = "inventory:stream"


async def init_redis():
    """Initialize Redis connection"""
    global redis_client, pubsub
    redis_client = redis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True
    )
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(CHANNEL_SALES_STREAM)


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
