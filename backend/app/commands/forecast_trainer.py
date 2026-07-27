"""Long-running: offline forecast trainer (Forecast Lab).

    python -m app.commands.forecast_trainer

Trains forecast models off the request path and serves them from cache. CPU-heavy;
run as a single dedicated worker in production. Refuses (noop, exit 2) if
RUN_FORECAST_TRAINER is false.
"""
import asyncio
import sys

from app.config import logger, get_settings
from app.services.database import init_db, close_db
from app.services.redis_client import init_redis, close_redis
from app.services.forecast_trainer import run_forecast_trainer


async def _main() -> int:
    s = get_settings()
    if not s.run_forecast_trainer:
        logger.error("[forecast_trainer] REFUSING: RUN_FORECAST_TRAINER is false.")
        return 2

    logger.info("[forecast_trainer] starting…")
    await init_db()
    await init_redis()
    try:
        await run_forecast_trainer()
        return 0
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("[forecast_trainer] stopped")
        return 0
    except Exception as e:  # noqa: BLE001
        logger.error(f"[forecast_trainer] FAILED: {e}")
        return 1
    finally:
        await close_redis()
        await close_db()


def main() -> None:
    sys.exit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
