"""One-shot: wipe the demo tenant's synthetic sales (E0-8).

    python -m app.commands.demo_reset [--retain-hours N]

The API runs this nightly on its own (services/demo_reset.run_demo_reset_loop);
this command is the manual path — before a demo, or to verify the job by hand.

Refuses unless DEMO_MODE=true, and refuses again inside reset_demo_tenant() if the
target tenant isn't slugged 'demo'. Only rows the generator marked `is_synthetic`
are ever deleted. Exit codes: 0 deleted / 2 refused / 1 error.
"""
import argparse
import asyncio
import sys

from app.config import logger, get_settings
from app.services.database import init_db, close_db
from app.services.demo_reset import DemoResetRefused, reset_demo_tenant


async def _main(retain_hours: int | None) -> int:
    s = get_settings()
    if not s.demo_mode:
        logger.error("[demo_reset] REFUSING: requires DEMO_MODE=true.")
        return 2

    await init_db()
    try:
        deleted = await reset_demo_tenant(retain_hours=retain_hours)
        logger.info(f"[demo_reset] removed {deleted} synthetic sales from tenant {s.demo_tenant_id}")
        return 0
    except DemoResetRefused as e:
        logger.error(f"[demo_reset] REFUSING: {e}")
        return 2
    except Exception as e:  # noqa: BLE001
        logger.error(f"[demo_reset] FAILED: {e}")
        return 1
    finally:
        await close_db()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset the demo tenant's synthetic sales.")
    parser.add_argument(
        "--retain-hours",
        type=int,
        default=None,
        help="Keep synthetic sales younger than this (default: DEMO_RESET_RETAIN_HOURS).",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args.retain_hours)))


if __name__ == "__main__":
    main()
