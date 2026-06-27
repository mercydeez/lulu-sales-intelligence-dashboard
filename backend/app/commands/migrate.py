"""One-shot: apply database migrations.

    python -m app.commands.migrate

Run as a dedicated job (the `migrate` service in production), NOT from every API
replica. Exits 0 on success, non-zero on failure so an orchestrator can gate the
API/worker on its completion.
"""
import asyncio
import sys

from app.config import logger
from app.services.database import init_db, close_db
from app.services.migration_runner import run_migrations


async def _main() -> int:
    logger.info("[migrate] applying database migrations…")
    await init_db()
    try:
        await run_migrations()
        logger.info("[migrate] migrations applied successfully")
        return 0
    except Exception as e:  # noqa: BLE001 — top-level CLI boundary
        logger.error(f"[migrate] migration FAILED: {e}")
        return 1
    finally:
        await close_db()


def main() -> None:
    sys.exit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
