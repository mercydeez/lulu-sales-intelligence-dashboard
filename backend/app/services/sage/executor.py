"""
Read-only, tenant-scoped SQL execution for Sage.

Runs the validated SELECT as the non-owner `app_rw` role (migration 020) inside
a READ ONLY transaction with the `app.tenant_id` GUC set. That gives three
independent guarantees on top of the validator:

  1. READ ONLY transaction  -> Postgres rejects any write/DDL (even from a superuser)
  2. FORCE ROW LEVEL SECURITY on app_rw -> rows are scoped to the tenant's GUC
  3. statement_timeout       -> a runaway query can't tie up a connection

A dedicated engine is used (always app_rw, regardless of the app-wide
USE_RLS_ROLE flag) so Sage is hardened even when the main request path isn't
yet running under RLS.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings, logger
from app.services.database import _derive_rls_url, _engine_kwargs

settings = get_settings()

# Hard cap on how long a Sage query may run.
STATEMENT_TIMEOUT_MS = 8000

_engine = None


def _get_engine():
    """Lazily create the app_rw (non-owner) engine Sage executes through."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(_derive_rls_url(), **_engine_kwargs)
        logger.info("Sage executor engine ready (app_rw, read-only)")
    return _engine


async def run_select(
    sql: str, tenant_id: int, max_rows: int
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Execute a validated SELECT and return (columns, rows). Rows are capped at
    max_rows. Raises on SQL/connection errors (caller falls back)."""
    engine = _get_engine()
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            # READ ONLY must precede the first query in the transaction.
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            await conn.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )
            result = await conn.execute(text(sql))
            columns = list(result.keys())
            rows = [dict(zip(columns, r)) for r in result.fetchmany(max_rows)]
            return columns, rows
        finally:
            # Nothing to commit (read-only) — always roll back.
            await trans.rollback()


async def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
