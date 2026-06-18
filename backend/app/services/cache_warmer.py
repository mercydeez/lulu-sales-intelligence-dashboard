"""
Cache warmer.

Keeps the heaviest dashboard aggregations hot in Redis so no user request ever
pays the cold-query cost. Runs as a background task in the app lifespan and
refreshes the "all stores" (super-admin) scope of the slowest endpoints
(KPIs and store distribution) on a short interval.

Scoped queries (regional / single-store) are filtered and therefore cheap to
compute on demand, so only the full-dataset scope is warmed here.
"""
import asyncio
import logging

from app.services.database import async_session
from app.routes.kpis import compute_and_cache_kpis
from app.routes.analytics import compute_and_cache_store_distribution

logger = logging.getLogger(__name__)

# Refresh interval, kept shorter than the KPI cache TTL (15s) so the warmed
# entries are overwritten before they can expire — the cache never goes cold.
WARM_INTERVAL_SECONDS = 10


async def _warm_once() -> None:
    async with async_session() as session:
        # allowed_stores=None => the full "all stores" scope (the heaviest query).
        await compute_and_cache_kpis(session, None)
        await compute_and_cache_store_distribution(session, None)


async def run_cache_warmer() -> None:
    """Periodically recompute and cache the heavy aggregations until cancelled."""
    logger.info("Cache warmer started (interval=%ss)", WARM_INTERVAL_SECONDS)
    while True:
        try:
            await _warm_once()
        except asyncio.CancelledError:
            logger.info("Cache warmer stopping")
            raise
        except Exception as e:  # never let a transient failure kill the loop
            logger.warning("Cache warm cycle failed: %s", e)
        try:
            await asyncio.sleep(WARM_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("Cache warmer stopping")
            raise
