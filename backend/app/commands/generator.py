"""Long-running: the SYNTHETIC live sale generator.

    python -m app.commands.generator

Refuses to run unless BOTH DEMO_MODE=true and LIVE_GENERATOR_ENABLED=true — it
writes synthetic sales to the database and must never run against a real tenant.
Runs until interrupted (SIGINT/SIGTERM). Exit codes: 0 clean stop / refused-noop
is 2, 1 on error.
"""
import asyncio
import sys

from app.config import logger, get_settings
from app.services.database import init_db, close_db
from app.services.redis_client import init_redis, close_redis
from app.services.data_generator import DataGenerator


async def _main() -> int:
    s = get_settings()
    if not (s.demo_mode and s.live_generator_enabled):
        logger.error(
            "[generator] REFUSING: requires DEMO_MODE=true AND LIVE_GENERATOR_ENABLED=true. "
            "The generator writes SYNTHETIC sales and must not run in a real tenant."
        )
        return 2

    logger.info("[generator] starting synthetic sale generator (DEMO_MODE)…")
    await init_db()
    await init_redis()
    gen = DataGenerator()
    try:
        await gen.start()
        return 0
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("[generator] stopped")
        return 0
    except Exception as e:  # noqa: BLE001
        logger.error(f"[generator] FAILED: {e}")
        return 1
    finally:
        await close_redis()
        await close_db()


def main() -> None:
    sys.exit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
