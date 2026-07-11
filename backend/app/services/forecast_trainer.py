"""
Forecast trainer.

Runs the heavy forecast model training off the request path. On a cadence it
recomputes the Forecast Lab payload (rolling-origin backtest + DL model
selection + diagnostics) for the default scope and writes it to the same Redis
key the /analytics/model-metrics endpoint reads. The Lab therefore loads
instantly and no user request ever trains a model — the correct ML-serving
split (train offline, serve from cache).

Only the demo tenant's full ("all stores") scope at the default horizon is
warmed here — that's the default Forecast Lab load. Narrower scopes / other
horizons are computed lazily in the background on first request (see
routes/analytics.py) and then kept hot by their own cache TTL.
"""
import asyncio
import logging

from app.config import get_settings
from app.services.database import async_session
from app.services.forecast_lab import compute_and_cache_model_metrics

logger = logging.getLogger(__name__)

# Retrain cadence. Comfortably shorter than MODEL_METRICS_TTL so the warmed
# entry is refreshed long before it can expire — the Lab never goes cold.
TRAIN_INTERVAL_SECONDS = 30 * 60  # 30 minutes

# Default Forecast Lab load: demo tenant, all stores, 14-day horizon.
WARM_TENANT_ID = 1
WARM_HORIZON = 14


async def _train_once() -> None:
    async with async_session() as session:
        # The training fetch reads the full sales history — legitimately long on
        # real-tenant volumes; lift the engine-default statement_timeout for this
        # transaction only (E6-4). Background task, never a request connection.
        from app.services.database import exempt_statement_timeout
        await exempt_statement_timeout(session)
        await compute_and_cache_model_metrics(
            session, tenant_id=WARM_TENANT_ID, allowed=None, horizon=WARM_HORIZON
        )


async def run_forecast_trainer() -> None:
    """Periodically retrain forecast models and cache the Lab payload until cancelled.

    Gated by ``forecast_trainer_enabled`` and delayed at startup so the API is
    responsive before any CPU-heavy training begins; the training itself runs in
    a worker thread (see compute_and_cache_model_metrics) so it never blocks the loop.
    """
    settings = get_settings()
    if not settings.forecast_trainer_enabled:
        logger.info("Forecast trainer disabled (forecast_trainer_enabled=false)")
        return

    delay = max(0, settings.forecast_trainer_startup_delay_seconds)
    if delay:
        logger.info("Forecast trainer warming up in %ss", delay)
        await asyncio.sleep(delay)

    logger.info("Forecast trainer started (interval=%ss)", TRAIN_INTERVAL_SECONDS)
    while True:
        try:
            await _train_once()
            logger.info("Forecast models retrained and cached")
        except asyncio.CancelledError:
            logger.info("Forecast trainer stopping")
            raise
        except Exception as e:  # never let a transient failure kill the loop
            logger.warning("Forecast training cycle failed: %s", e)
        try:
            await asyncio.sleep(TRAIN_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("Forecast trainer stopping")
            raise
