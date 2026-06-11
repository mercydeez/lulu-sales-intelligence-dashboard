import os
import logging
from sqlalchemy import text
from app.services.database import engine

logger = logging.getLogger(__name__)

async def run_migrations():
    """
    Finds and applies all database migrations in order.
    Tracks applied migrations in schema_migrations table.
    """
    # Candidate migration directories
    candidates = [
        "/app/database/migrations",
        "./database/migrations",
        "../database/migrations",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "database", "migrations")
    ]
    
    migrations_dir = None
    for path in candidates:
        if os.path.isdir(path):
            migrations_dir = os.path.abspath(path)
            break
            
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
                
            # Execute migration SQL
            try:
                # Execute as a single block
                await conn.execute(text(sql_content))
                # Record in schema_migrations
                await conn.execute(
                    text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                    {"version": filename}
                )
                logger.info(f"Migration {filename} applied successfully.")
            except Exception as e:
                logger.error(f"Failed to apply migration {filename}: {e}")
                # Since we are in engine.begin() context manager, this transaction will automatically rollback.
                raise e
