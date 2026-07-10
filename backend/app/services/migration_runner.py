import os
import logging
from typing import List, Optional
from sqlalchemy import text
from app.services.database import engine

logger = logging.getLogger(__name__)


def _find_migrations_dir() -> Optional[str]:
    """Locate the migrations directory across dev/container layouts."""
    candidates = [
        "/app/database/migrations",
        "./database/migrations",
        "../database/migrations",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "database", "migrations"),
    ]
    for path in candidates:
        if os.path.isdir(path):
            return os.path.abspath(path)
    return None


def _list_migration_files(migrations_dir: str) -> List[str]:
    return sorted(f for f in os.listdir(migrations_dir) if f.endswith(".sql"))


async def pending_migrations() -> List[str]:
    """Return migration filenames present on disk but not yet applied.

    Empty list => schema is current. Used by readiness/deep health checks.
    Raises on a DB connectivity error (caller decides how to surface it).
    """
    migrations_dir = _find_migrations_dir()
    if not migrations_dir:
        return []
    files = _list_migration_files(migrations_dir)
    if not files:
        return []
    async with engine.connect() as conn:
        exists = await conn.execute(text(
            "SELECT to_regclass('public.schema_migrations') IS NOT NULL"
        ))
        if not exists.scalar():
            return files  # table absent => nothing applied yet
        result = await conn.execute(text("SELECT version FROM schema_migrations"))
        applied = {row[0] for row in result.fetchall()}
    return [f for f in files if f not in applied]


async def run_migrations():
    """
    Finds and applies all database migrations in order.
    Tracks applied migrations in schema_migrations table.
    """
    migrations_dir = _find_migrations_dir()
    if not migrations_dir:
        logger.warning("Migration directory not found in candidate paths. Skipping auto-migrations.")
        return

    logger.info(f"Using migrations directory: {migrations_dir}")
    
    # Get all migration files
    try:
        migration_files = sorted([
            f for f in os.listdir(migrations_dir)
            if f.endswith('.sql')
        ])
    except Exception as e:
        logger.error(f"Failed to read migration files: {e}")
        return
    
    if not migration_files:
        logger.info("No migration files found.")
        return

    async with engine.begin() as conn:
        # Migrations legitimately run long (backfills, index builds) — lift the
        # engine-default statement_timeout for this transaction only (E6-4).
        from app.services.database import exempt_statement_timeout
        await exempt_statement_timeout(conn)

        # Create schema_migrations table if not exists
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """))
        
        # Get applied migrations
        result = await conn.execute(text("SELECT version FROM schema_migrations"))
        applied = {row[0] for row in result.fetchall()}
        
        for filename in migration_files:
            if filename in applied:
                logger.info(f"Migration {filename} already applied.")
                continue
                
            logger.info(f"Applying migration: {filename}")
            filepath = os.path.join(migrations_dir, filename)
            
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    sql_content = f.read()
            except Exception as e:
                logger.error(f"Failed to read migration file {filename}: {e}")
                raise e
                
            # Execute migration SQL with the underlying driver so multi-statement
            # PostgreSQL scripts (DDL, DO blocks, functions, triggers) run as-is.
            try:
                raw_conn = await conn.get_raw_connection()
                await raw_conn.driver_connection.execute(sql_content)
                # Record in schema_migrations. ON CONFLICT DO NOTHING is
                # defence-in-depth: the startup advisory lock (services.leader_lock)
                # already serializes booting processes, but a torn boot (SIGKILL
                # after a migration file's embedded COMMIT, before this INSERT) must
                # never crash a later process on the PK.
                await conn.execute(
                    text("INSERT INTO schema_migrations (version) VALUES (:version) "
                         "ON CONFLICT (version) DO NOTHING"),
                    {"version": filename}
                )
                logger.info(f"Migration {filename} applied successfully.")
            except Exception as e:
                logger.error(f"Failed to apply migration {filename}: {e}")
                # Since we are in engine.begin() context manager, this transaction will automatically rollback.
                raise e
