"""
Data-subject rights (Phase 12 — trust & legal).

Two tenant-scoped capabilities, both admin-gated at the route layer:

  * export_tenant_data() — portability. Assembles a JSON snapshot of *this tenant's*
    rows from every tenant-stamped table, discovered dynamically from
    information_schema so we can never accidentally reference another table's
    columns or miss a new tenant table. Sensitive auth columns are dropped.

  * delete-on-request — erasure. We DO NOT hard-delete from the API. A request is
    recorded in `data_requests` and must be approved + executed by an operator
    (human-approved, with a reversible review window). This service only manages
    the request lifecycle + audit; see docs/runbooks/DATA_DELETION.md for the
    operator procedure.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Columns never included in an export, even from a tenant-owned row — they are
# credential material or another subject's secrets, not the requester's data.
_SENSITIVE_COLUMNS = {
    "password_hash", "hashed_password", "key_hash", "token_hash",
    "totp_secret", "mfa_secret", "backup_codes", "reset_token", "verify_token",
    "client_secret", "credentials", "secret",
}

# Hard caps so a single export can't OOM the API on a large tenant.
_MAX_ROWS_PER_TABLE = 50_000
_EXPORT_VERSION = 1


async def _tenant_tables(db: AsyncSession) -> List[str]:
    """Every base table in the public schema that has a tenant_id column."""
    rows = (await db.execute(text("""
        SELECT c.table_name
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name
        WHERE c.table_schema = 'public'
          AND c.column_name = 'tenant_id'
          AND t.table_type = 'BASE TABLE'
        ORDER BY c.table_name
    """))).fetchall()
    return [r.table_name for r in rows]


async def _table_columns(db: AsyncSession, table: str) -> List[str]:
    rows = (await db.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :t
        ORDER BY ordinal_position
    """), {"t": table})).fetchall()
    return [r.column_name for r in rows if r.column_name not in _SENSITIVE_COLUMNS]


async def export_tenant_data(db: AsyncSession, tenant_id: int) -> Dict:
    """Build a tenant-scoped JSON-serialisable export. Read-only."""
    tables = await _tenant_tables(db)
    export: Dict[str, Dict] = {}
    for tbl in tables:
        cols = await _table_columns(db, tbl)
        if not cols:
            continue
        col_list = ", ".join(f'"{c}"' for c in cols)
        # Parameterised tenant scope; identifiers are from information_schema (safe).
        rows = (await db.execute(text(
            f'SELECT {col_list} FROM "{tbl}" WHERE tenant_id = :tid '
            f'LIMIT :lim'
        ), {"tid": tenant_id, "lim": _MAX_ROWS_PER_TABLE})).mappings().all()
        truncated = len(rows) >= _MAX_ROWS_PER_TABLE
        export[tbl] = {
            "row_count": len(rows),
            "truncated": truncated,
            "rows": [_jsonable(dict(r)) for r in rows],
        }
    return {
        "export_version": _EXPORT_VERSION,
        "tenant_id": tenant_id,
        "tables": export,
        "note": "Scoped to this tenant only. Sensitive credential columns are omitted.",
    }


def _jsonable(row: dict) -> dict:
    """Coerce DB values (datetime/Decimal/etc.) to JSON-safe primitives."""
    from datetime import date, datetime
    from decimal import Decimal
    out = {}
    for k, v in row.items():
        if isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


async def create_request(
    db: AsyncSession,
    tenant_id: int,
    kind: str,
    *,
    scope: Optional[str] = None,
    requested_by: Optional[int] = None,
    requested_email: Optional[str] = None,
) -> Dict:
    """Record an export/delete request (pending). Never executes a deletion."""
    if kind not in ("export", "delete"):
        raise ValueError("kind must be 'export' or 'delete'")
    row = (await db.execute(text("""
        INSERT INTO data_requests (tenant_id, kind, scope, requested_by, requested_email)
        VALUES (:tid, :kind, :scope, :by, :email)
        RETURNING id, status, created_at
    """), {"tid": tenant_id, "kind": kind, "scope": scope,
           "by": requested_by, "email": requested_email})).fetchone()
    await db.commit()
    return {"id": row.id, "kind": kind, "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None}


async def list_requests(db: AsyncSession, tenant_id: int) -> List[Dict]:
    rows = (await db.execute(text("""
        SELECT id, kind, status, scope, requested_email, reason, created_at, updated_at
        FROM data_requests WHERE tenant_id = :tid ORDER BY created_at DESC
    """), {"tid": tenant_id})).mappings().all()
    return [_jsonable(dict(r)) for r in rows]
