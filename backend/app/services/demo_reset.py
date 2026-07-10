"""Nightly demo-tenant reset (E0-8).

The synthetic generator appends a sale every ~5-15s forever. Left alone the demo
tenant accumulates months of fabricated stream rows, which drags the dashboard's
"all-time" numbers away from the seeded CSV history the demo script is written
against. This deletes generated rows once they're older than a retention window,
keeping the live stream populated while the historical picture stays the seeded one.

Safety: this is a DELETE, so it verifies its target is genuinely the demo tenant
(by slug, in the DB) before touching a row, and it only ever removes rows the
generator itself marked `is_synthetic` (migration 057). A real tenant's rows are
unreachable from here on both counts.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.config import get_settings
from app.services.database import async_session

logger = logging.getLogger(__name__)
settings = get_settings()

_SECONDS_PER_HOUR = 3600


class DemoResetRefused(RuntimeError):
    """The reset target failed its safety checks; nothing was deleted."""


async def _assert_is_demo_tenant(session, tenant_id: int) -> None:
    """Refuse to delete unless `tenant_id` is the tenant slugged 'demo'."""
    row = (
        await session.execute(
            text("SELECT slug FROM tenants WHERE id = :tid"), {"tid": tenant_id}
        )
    ).first()

    if row is None:
        raise DemoResetRefused(f"tenant {tenant_id} does not exist")
    if row[0] != "demo":
        raise DemoResetRefused(
            f"tenant {tenant_id} has slug '{row[0]}', not 'demo' — refusing to delete its sales"
        )


async def reset_demo_tenant(retain_hours: int | None = None) -> int:
    """Delete synthetic sales older than the retention window. Returns rows removed."""
    tenant_id = settings.demo_tenant_id
    retain = settings.demo_reset_retain_hours if retain_hours is None else retain_hours
    cutoff = datetime.now(timezone.utc) - timedelta(hours=retain)

    async with async_session() as session:
        await _assert_is_demo_tenant(session, tenant_id)

        result = await session.execute(
            text(
                """
                DELETE FROM sales_stream_raw
                 WHERE tenant_id = :tid
                   AND is_synthetic
                   AND timestamp < :cutoff
                """
            ),
            {"tid": tenant_id, "cutoff": cutoff},
        )
        await session.commit()

    deleted = result.rowcount or 0
    logger.info(
        "demo reset: removed %s synthetic sales from tenant %s (older than %sh)",
        deleted, tenant_id, retain,
    )
    return deleted


def seconds_until_next_reset(now: datetime, hour_utc: int) -> float:
    """Seconds from `now` to the next occurrence of `hour_utc`:00 UTC."""
    target = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def run_demo_reset_loop() -> None:
    """Sleep until the configured hour, reset, repeat. Started from main.py's lifespan."""
    if not (settings.demo_mode and settings.demo_reset_enabled):
        logger.info("demo reset loop not started (demo_mode/demo_reset_enabled off)")
        return

    while True:
        delay = seconds_until_next_reset(datetime.now(timezone.utc), settings.demo_reset_hour_utc)
        logger.info("demo reset: next run in %.1f hours", delay / _SECONDS_PER_HOUR)
        await asyncio.sleep(delay)
        try:
            await reset_demo_tenant()
        except DemoResetRefused as exc:
            # Misconfiguration, not a transient fault — stop rather than retry nightly.
            logger.error("demo reset refused, loop stopping: %s", exc)
            return
        except Exception:
            logger.exception("demo reset failed; will retry at the next scheduled hour")
