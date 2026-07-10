"""
Database seeder.

Portable replacement for the Postgres docker-entrypoint init. Managed Postgres
(e.g. Render) cannot run database/init.sql, and a server-side
`COPY FROM '/data/train.csv'` needs the file on the DB host. So the application
owns seeding in every environment:

  1. exec database/init.sql            -> base schema + stores/items/regions/users (idempotent)
  2. if sales_historical is empty      -> bulk-load data/train.csv via asyncpg COPY (client-side, streamed)
  3. date-shift the history            -> latest day becomes yesterday

Runs once at startup, before migrations. Idempotent and safe on every boot:
already-seeded databases skip the CSV load.
"""
import os
import logging

from sqlalchemy import text

from app.services.database import engine

logger = logging.getLogger(__name__)

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# backend/app/services/db_seeder.py -> repo paths
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR))))

_INIT_SQL_CANDIDATES = [
    "/app/database/init.sql",
    os.path.join(os.getcwd(), "database", "init.sql"),
    os.path.join(_REPO_ROOT, "database", "init.sql"),
]
_CSV_CANDIDATES = [
    os.environ.get("SEED_CSV_PATH", ""),
    "/app/data/train.csv",
    os.path.join(os.getcwd(), "data", "train.csv"),
    os.path.join(_REPO_ROOT, "data", "train.csv"),
]

_DATE_SHIFT_SQL = """
DO $$
DECLARE
    max_hist_date DATE;
    shift_days INTEGER;
BEGIN
    SELECT MAX(date) INTO max_hist_date FROM sales_historical;
    IF max_hist_date IS NOT NULL THEN
        shift_days := (CURRENT_DATE - 1) - max_hist_date;
        IF shift_days <> 0 THEN
            UPDATE sales_historical SET date = date + shift_days;
        END IF;
    END IF;
END $$;
"""


def _first_existing(paths):
    for p in paths:
        if p and os.path.isfile(p):
            return os.path.abspath(p)
    return None


async def run_seed():
    """Ensure base schema + historical data exist. Idempotent."""
    # 1. Base schema (idempotent DDL + reference-data seeds).
    init_sql = _first_existing(_INIT_SQL_CANDIDATES)
    if not init_sql:
        logger.warning(
            "init.sql not found in %s — assuming the database is already provisioned",
            _INIT_SQL_CANDIDATES,
        )
    else:
        with open(init_sql, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        async with engine.begin() as conn:
            from app.services.database import exempt_statement_timeout
            await exempt_statement_timeout(conn)  # schema script runs long (E6-4)
            raw = await conn.get_raw_connection()
            # asyncpg runs the multi-statement script (DO blocks, views, seeds).
            await raw.driver_connection.execute(schema_sql)
        logger.info("Base schema ensured (%s)", init_sql)

    # 2. Bulk-load history only if empty.
    async with engine.begin() as conn:
        count = (await conn.execute(text("SELECT COUNT(*) FROM sales_historical"))).scalar()
    if count and count > 0:
        logger.info("sales_historical already populated (%s rows) — skipping CSV load", count)
        return

    csv_path = _first_existing(_CSV_CANDIDATES)
    if not csv_path:
        logger.warning(
            "train.csv not found in %s — sales_historical left empty (set SEED_CSV_PATH)",
            _CSV_CANDIDATES,
        )
        return

    logger.info("Bulk-loading historical sales from %s ...", csv_path)
    async with engine.begin() as conn:
        from app.services.database import exempt_statement_timeout
        await exempt_statement_timeout(conn)  # ~900k-row COPY + date shift (E6-4)
        raw = await conn.get_raw_connection()
        asyncpg_conn = raw.driver_connection
        # Client-side streamed COPY (works against managed Postgres). The CSV's
        # 4 columns (date,store,item,sales) map positionally to these columns.
        await asyncpg_conn.copy_to_table(
            "sales_historical",
            source=csv_path,
            columns=["date", "store_id", "item_id", "sales"],
            format="csv",
            header=True,
        )
        # Shift dates so the latest historical day is yesterday.
        await conn.execute(text(_DATE_SHIFT_SQL))
        new_count = (await conn.execute(text("SELECT COUNT(*) FROM sales_historical"))).scalar()
        rng = (await conn.execute(text("SELECT MIN(date), MAX(date) FROM sales_historical"))).fetchone()

    logger.info(
        "Seeded %s historical rows (date range %s .. %s)", new_count, rng[0], rng[1]
    )
