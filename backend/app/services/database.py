from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool, AsyncAdaptedQueuePool
from sqlalchemy import text
from typing import AsyncGenerator
import asyncio
import logging
from app.config import get_settings
from app.models.sales import Base

settings = get_settings()
logger = logging.getLogger(__name__)

# Optimized connection pooling for production
engine = create_async_engine(
    settings.database_url,
    poolclass=NullPool if settings.environment == "testing" else AsyncAdaptedQueuePool,
    pool_size=20,           # Base number of connections
    max_overflow=30,        # Additional connections when pool is exhausted
    pool_pre_ping=True,     # Test connections before use
    pool_recycle=1800,      # Recycle connections after 30 minutes
    pool_timeout=30,        # Wait up to 30 seconds for connection
    echo=False              # Disable SQL logging in production for speed
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


async def init_db(max_retries: int = 30, retry_delay: float = 3.0):
    """Initialize database connection with retry logic"""
    for attempt in range(max_retries):
        try:
            async with engine.begin() as conn:
                # Test the connection
                await conn.execute(text("SELECT 1"))
                logger.info("Database connection established successfully")
                return
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(
                    f"Database connection attempt {attempt + 1}/{max_retries} failed: {e}. "
                    f"Retrying in {retry_delay}s..."
                )
                await asyncio.sleep(retry_delay)
            else:
                logger.error(f"Failed to connect to database after {max_retries} attempts")
                raise


async def close_db():
    """Close database connection"""
    await engine.dispose()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting database session"""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
