"""Long-running: dashboard cache warmer.

    python -m app.commands.cache_warmer

Keeps the heavy dashboard queries hot. Safe to run per-instance, or as a single
dedicated worker. Refuses (noop, exit 2) if RUN_CACHE_WARMER is false.
"""
import asyncio
import sys

from app.config import logger, get_settings
from app.services.database import init_db, close_db
from app.services.redis_client import init_redis, close_redis
from app.services.cache_warmer import run_cache_warmer


async def _main() -> int:
    s = get_settings()
    if not s.run_cache_warmer:
        logger.error("[cache_warmer] REFUSING: RUN_CACHE_WARMER is false.")
        return 2

    logger.info("[cache_warmer] starting…")
    await init_db()
    await init_redis()
    try:
        await run_cache_warmer()
        return 0
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("[cache_warmer] stopped")
        return 0
    except Exception as e:  # noqa: BLE001
        logger.error(f"[cache_warmer] FAILED: {e}")
        return 1
    finally:
        await close_redis()
        await close_db()


def main() -> None:
    sys.exit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
