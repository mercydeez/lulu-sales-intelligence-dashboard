"""One-shot: seed SYNTHETIC demo data (historical + base rows).

    python -m app.commands.seed

Refuses to run unless DEMO_MODE or SAMPLE_DATA_ENABLED is set, because the seed
loads synthetic demo data that must NEVER be written into a real-tenant
production database (see docs/product/DEMO_VS_REAL_DATA.md).
Exit codes: 0 success, 1 failure, 2 refused (unsafe config).
"""
import asyncio
import sys

from app.config import logger, get_settings
from app.services.database import init_db, close_db
from app.services.db_seeder import run_seed


async def _main() -> int:
    s = get_settings()
    if not (s.demo_mode or s.sample_data_enabled):
        logger.error(
            "[seed] REFUSING: DEMO_MODE and SAMPLE_DATA_ENABLED are both off. "
            "Seeding loads SYNTHETIC demo data and must not run against real tenants."
        )
        return 2

    logger.info("[seed] seeding synthetic demo data…")
    await init_db()
    try:
        await run_seed()
        logger.info("[seed] seed ensured")
        return 0
    except Exception as e:  # noqa: BLE001
        logger.error(f"[seed] seed FAILED: {e}")
        return 1
    finally:
        await close_db()


def main() -> None:
    sys.exit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
