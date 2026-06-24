"""
Cache Service
High-performance caching layer using Redis for API responses
"""
import json
import hashlib
from decimal import Decimal
from typing import Optional, Any, Callable
from functools import wraps
# Import the module (not the name) so we always read the LIVE client. The global
# `redis_client` is None at import time and reassigned in init_redis() at startup;
# `from ... import redis_client` would capture that None forever and silently
# disable caching (every request would recompute its query). Reading
# `_redis.redis_client` at call time picks up the connected client.
from app.services import redis_client as _redis
from app.config import logger

# Cache TTLs in seconds
CACHE_TTL = {
    'inventory_summary': 60,      # 1 minute
    'inventory_items': 30,        # 30 seconds
    'inventory_categories': 120,  # 2 minutes
    'promotions_summary': 60,     # 1 minute
    'promotions_list': 30,        # 30 seconds
    'promotions_performance': 120,# 2 minutes
    'alerts_summary': 30,         # 30 seconds
    'alerts_list': 30,            # 30 seconds
    'admin_dashboard': 60,        # 1 minute
    'admin_stores': 120,          # 2 minutes
    'kpis': 15,                   # 15 seconds (more real-time)
    'analytics': 60,              # 1 minute
    'default': 30                 # 30 seconds default
}


def _json_default(o: Any):
    """JSON fallback for non-native types. Decimal must become a JSON *number*
    so a cache HIT matches the uncached path (FastAPI also encodes Decimal as a
    number); stringifying it caused values like avg_basket_size to come back as
    "12.5" and break `.toFixed()` on the frontend. Everything else (date,
    datetime, …) falls back to its ISO/str form as before."""
    if isinstance(o, Decimal):
        return float(o)
    return str(o)


def generate_cache_key(prefix: str, **kwargs) -> str:
    """Generate a unique, TENANT-SCOPED cache key from prefix and parameters.

    The active tenant (tenant_context) is ALWAYS folded into the key so a cached
    response can never be served across tenants. This is essential: super_admins
    of different tenants share the same scope params (e.g. accessible_stores=[] =>
    the 'all' scope), which previously collided on a single key and leaked one
    tenant's data to another. Defaults to tenant 1 outside a request (cache warmer).
    Imported lazily to avoid a circular import with services.database."""
    try:
        from app.services.database import tenant_context
        tid = tenant_context.get()
    except Exception:
        tid = "_"
    params_str = json.dumps(kwargs, sort_keys=True, default=str)
    params_hash = hashlib.md5(params_str.encode()).hexdigest()[:12]
    return f"cache:t{tid}:{prefix}:{params_hash}"


async def get_cached(key: str) -> Optional[Any]:
    """Get value from cache"""
    try:
        client = _redis.redis_client
        if client:
            value = await client.get(key)
            if value:
                logger.debug(f"Cache HIT: {key}")
                return json.loads(value)
            logger.debug(f"Cache MISS: {key}")
    except Exception as e:
        logger.warning(f"Cache get error: {e}")
    return None


async def set_cached(key: str, value: Any, ttl: int = None):
    """Set value in cache with TTL"""
    try:
        client = _redis.redis_client
        if client:
            ttl = ttl or CACHE_TTL['default']
            await client.set(key, json.dumps(value, default=_json_default), ex=ttl)
            logger.debug(f"Cache SET: {key} (TTL: {ttl}s)")
    except Exception as e:
        logger.warning(f"Cache set error: {e}")


async def delete_cached(pattern: str):
    """Delete cache keys matching pattern"""
    try:
        client = _redis.redis_client
        if client:
            keys = await client.keys(f"cache:{pattern}:*")
            if keys:
                await client.delete(*keys)
                logger.debug(f"Cache DELETE: {len(keys)} keys matching {pattern}")
    except Exception as e:
        logger.warning(f"Cache delete error: {e}")


async def invalidate_inventory_cache():
    """Invalidate all inventory-related caches"""
    await delete_cached("inventory_*")


async def invalidate_promotions_cache():
    """Invalidate all promotions-related caches"""
    await delete_cached("promotions_*")


async def invalidate_alerts_cache():
    """Invalidate all alerts-related caches"""
    await delete_cached("alerts_*")


def cached_endpoint(cache_prefix: str, ttl: int = None):
    """Decorator for caching API endpoint responses"""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Generate cache key from function arguments
            cache_key = generate_cache_key(cache_prefix, **kwargs)
            
            # Try to get from cache
            cached = await get_cached(cache_key)
            if cached is not None:
                return cached
            
            # Execute function
            result = await func(*args, **kwargs)
            
            # Store in cache
            cache_ttl = ttl or CACHE_TTL.get(cache_prefix, CACHE_TTL['default'])
            await set_cached(cache_key, result, cache_ttl)
            
            return result
        return wrapper
    return decorator
