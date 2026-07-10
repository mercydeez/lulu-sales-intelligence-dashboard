"""E6-3 — keep `sales_stream_raw`'s monthly partitions ahead of the clock, and
drop the ones past retention.

TWO JOBS, AND THEY FAIL DIFFERENTLY.

`ensure` must run *before* the month turns. If the partition for next month does
not exist at 00:00 on the 1st, every generator insert lands in the DEFAULT
partition — which is why the DEFAULT exists, so nothing is ever rejected. But
rows in DEFAULT cannot be reclaimed by dropping a month, so a DEFAULT that is not
empty is a silent, permanent leak of the retention policy. It is checked on every
tick and logged as an error, not a debug line.

`prune` DROPs whole partitions. That is the point of partitioning: reclaiming a
month is instant and returns the disk, where `DELETE ... WHERE timestamp < …`
would rewrite the table and leave it bloated. It is also irreversible, so it
refuses a retention window under one month, and it never touches DEFAULT.

The generator's synthetic rows are already wiped nightly by `demo_reset`; this is
the policy for real ingested events.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from sqlalchemy import text

from app.config import get_settings, logger
from app.services.database import async_session

# Partitions to keep ahead of "now". Three months means a maintenance outage has
# to last a full quarter before a row can reach the DEFAULT partition.
MONTHS_AHEAD = 3

# Once a day is ample: the work is creating at most one table and dropping at
# most one. Ticking hourly would mostly log that there is nothing to do.
TICK_SECONDS = 6 * 60 * 60


async def ensure_partitions(db, months_ahead: int = MONTHS_AHEAD) -> int:
    created = (await db.execute(
        text("SELECT ensure_sales_stream_partitions(:m)"), {"m": months_ahead}
    )).scalar()
    return int(created or 0)


async def default_partition_rows(db) -> int:
    """Rows that landed outside every declared month.

    Should always be zero. Non-zero means `ensure` did not run in time, and those
    rows will never be reclaimed by pruning.
    """
    return int((await db.execute(text("SELECT count(*) FROM sales_stream_raw_default"))).scalar() or 0)


async def prune_partitions(db, retention_months: int) -> List[str]:
    rows = (await db.execute(
        text("SELECT dropped FROM prune_sales_stream_partitions(:r)"),
        {"r": retention_months},
    )).scalars().all()
    return list(rows)


async def run_partition_maintenance() -> Dict[str, Any]:
    """One pass. Safe to call from anywhere; returns what it did."""
    settings = get_settings()
    retention = settings.sales_stream_retention_months

    async with async_session() as db:
        created = await ensure_partitions(db)
        await db.commit()

    async with async_session() as db:
        stranded = await default_partition_rows(db)

    if stranded:
        # Loud on purpose. The retention policy is silently not applying to these.
        logger.error(
            f"sales_stream_raw_default holds {stranded} row(s): a partition was missing "
            f"when they arrived. They cannot be reclaimed by dropping a month — move them "
            f"into their month partition, then investigate why maintenance did not run."
        )

    dropped: List[str] = []
    if retention and retention >= 1:
        async with async_session() as db:
            dropped = await prune_partitions(db, retention)
            await db.commit()
        if dropped:
            logger.info(f"Partition retention: dropped {len(dropped)} month(s): {dropped}")

    return {"created": created, "dropped": dropped,
            "default_partition_rows": stranded, "retention_months": retention}


async def partition_maintenance_loop() -> None:
    """Background task. Runs once at startup so a fresh deploy is immediately
    correct, then every TICK_SECONDS."""
    logger.info(
        f"Partition maintenance started (every {TICK_SECONDS // 3600}h, "
        f"retention {get_settings().sales_stream_retention_months} months)")
    while True:
        try:
            result = await run_partition_maintenance()
            if result["created"]:
                logger.info(f"Partition maintenance created {result['created']} partition(s)")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(f"Partition maintenance failed: {exc!r}")
        await asyncio.sleep(TICK_SECONDS)
