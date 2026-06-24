"""
Data source registry.

Stores external database connections (Postgres now, Mongo later) that a
super-admin can register and activate so the dashboard reads from a client's
data instead of the built-in synthetic demo. Connection strings are encrypted
at rest (Fernet, key derived from SECRET_KEY); the `mapping` records how the
source's columns map to the dashboard's canonical fields:

    { "table": "orders", "date": "order_date", "store": "store_id",
      "item": "product_id", "category": "category", "quantity": "qty",
      "price": "unit_price" }

Only `date`, `store`, `item`, `quantity` are required; `category`/`price` are
optional. `table` may be `schema.table`.
"""
import base64
import hashlib
import re
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from cryptography.fernet import Fernet
from sqlalchemy import text

from app.services.database import async_session
from app.config import get_settings, logger

REQUIRED_MAPPING_FIELDS = ("date", "store", "item", "quantity")
OPTIONAL_MAPPING_FIELDS = ("category", "price")

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _fernet() -> Fernet:
    # Derive a stable 32-byte Fernet key from SECRET_KEY.
    digest = hashlib.sha256(get_settings().secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def _safe_identifier(name: str) -> str:
    """Validate + double-quote a SQL identifier (supports schema.table)."""
    parts = name.split(".")
    for p in parts:
        if not _IDENT_RE.match(p):
            raise ValueError(f"Invalid identifier: {name!r}")
    return ".".join(f'"{p}"' for p in parts)


def _plain_dsn(connection: str) -> str:
    """asyncpg.connect wants a libpq URI, not SQLAlchemy's +asyncpg scheme."""
    return connection.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgres+asyncpg://", "postgres://"
    )


# ---------------------------------------------------------------------------
# Connection testing
# ---------------------------------------------------------------------------

async def test_connection(source_type: str, connection: Optional[str], mapping: dict) -> tuple[bool, str]:
    """Probe a source. Returns (ok, message). Never raises."""
    if source_type == "builtin":
        return True, "Built-in demo source"
    if source_type == "postgres":
        if not connection:
            return False, "A connection string is required"
        try:
            return await _test_postgres(connection, mapping or {})
        except Exception as e:  # asyncpg / DNS / auth / mapping errors
            return False, str(e)
    return False, f"Unsupported source type: {source_type}"


async def _test_postgres(connection: str, mapping: dict) -> tuple[bool, str]:
    conn = await asyncpg.connect(dsn=_plain_dsn(connection), timeout=8)
    try:
        await conn.fetchval("SELECT 1")
        table = mapping.get("table")
        if table:
            missing = [f for f in REQUIRED_MAPPING_FIELDS if not mapping.get(f)]
            if missing:
                return False, f"Mapping is missing required field(s): {', '.join(missing)}"
            cols = [mapping[f] for f in REQUIRED_MAPPING_FIELDS]
            cols += [mapping[f] for f in OPTIONAL_MAPPING_FIELDS if mapping.get(f)]
            select_list = ", ".join(_safe_identifier(c) for c in cols)
            # LIMIT 1 — validates the table + every mapped column exists, cheaply.
            await conn.fetch(f"SELECT {select_list} FROM {_safe_identifier(table)} LIMIT 1")
            return True, f"Connected; mapped columns valid on {table}"
        return True, "Connected (no table mapping to validate yet)"
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def _row_public(row) -> dict:
    """Serialize a row for the API — never includes the connection string."""
    return {
        "id": row.id,
        "name": row.name,
        "type": row.type,
        "mapping": row.mapping or {},
        "is_active": row.is_active,
        "status": row.status,
        "last_tested_at": row.last_tested_at.isoformat() if row.last_tested_at else None,
        "last_error": row.last_error,
        "has_connection": bool(getattr(row, "connection_enc", None)),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def list_sources(tenant_id: int = 1) -> list[dict]:
    async with async_session() as s:
        rows = (await s.execute(text(
            "SELECT id, name, type, mapping, is_active, status, last_tested_at, "
            "last_error, connection_enc, created_at FROM data_sources "
            "WHERE tenant_id = :tid ORDER BY id"
        ), {"tid": tenant_id})).fetchall()
    return [_row_public(r) for r in rows]


async def create_source(name: str, source_type: str, connection: Optional[str],
                        mapping: dict, user_id: Optional[int], tenant_id: int = 1) -> dict:
    enc = encrypt(connection) if connection else None
    async with async_session() as s:
        row = (await s.execute(text(
            "INSERT INTO data_sources (name, type, connection_enc, mapping, created_by, tenant_id) "
            "VALUES (:name, :type, :enc, CAST(:mapping AS jsonb), :uid, :tid) "
            "RETURNING id, name, type, mapping, is_active, status, last_tested_at, "
            "last_error, connection_enc, created_at"
        ), {
            "name": name, "type": source_type, "enc": enc,
            "mapping": _json(mapping), "uid": user_id, "tid": tenant_id,
        })).fetchone()
        await s.commit()
    return _row_public(row)


async def record_test_result(source_id: int, ok: bool, message: str) -> None:
    async with async_session() as s:
        await s.execute(text(
            "UPDATE data_sources SET status = :st, last_tested_at = :ts, "
            "last_error = :err, updated_at = now() WHERE id = :id"
        ), {
            "st": "ok" if ok else "error",
            "ts": datetime.now(timezone.utc),
            "err": None if ok else message,
            "id": source_id,
        })
        await s.commit()


async def set_active(source_id: int) -> bool:
    """Activate one source (deactivates the rest). Returns False if id unknown."""
    async with async_session() as s:
        exists = (await s.execute(text("SELECT 1 FROM data_sources WHERE id = :id"),
                                  {"id": source_id})).fetchone()
        if not exists:
            return False
        # Two statements (one transaction): clear the current active row first so
        # there is never a moment with two active rows — a single
        # `is_active = (id = :id)` update can violate the one-active partial unique
        # index depending on row-update order.
        await s.execute(text("UPDATE data_sources SET is_active = false WHERE is_active"))
        await s.execute(text(
            "UPDATE data_sources SET is_active = true, updated_at = now() WHERE id = :id"
        ), {"id": source_id})
        await s.commit()
    return True


async def delete_source(source_id: int) -> tuple[bool, str]:
    async with async_session() as s:
        row = (await s.execute(text(
            "SELECT type, is_active FROM data_sources WHERE id = :id"), {"id": source_id})).fetchone()
        if not row:
            return False, "Not found"
        if row.type == "builtin":
            return False, "The built-in source cannot be deleted"
        if row.is_active:
            return False, "Deactivate the source before deleting it"
        await s.execute(text("DELETE FROM data_sources WHERE id = :id"), {"id": source_id})
        await s.commit()
    return True, "Deleted"


async def get_source_with_connection(source_id: int) -> Optional[dict]:
    """Internal: a single source incl. its decrypted connection (for adapters)."""
    async with async_session() as s:
        row = (await s.execute(text(
            "SELECT id, name, type, mapping, is_active, status, last_tested_at, "
            "last_error, connection_enc, created_at FROM data_sources WHERE id = :id"
        ), {"id": source_id})).fetchone()
    if not row:
        return None
    out = _row_public(row)
    out["connection"] = decrypt(row.connection_enc) if row.connection_enc else None
    return out


async def get_active_source() -> Optional[dict]:
    """Internal: the active source incl. decrypted connection (for adapters)."""
    async with async_session() as s:
        row = (await s.execute(text(
            "SELECT id, name, type, mapping, is_active, status, last_tested_at, "
            "last_error, connection_enc, created_at FROM data_sources WHERE is_active LIMIT 1"
        ))).fetchone()
    if not row:
        return None
    out = _row_public(row)
    out["connection"] = decrypt(row.connection_enc) if row.connection_enc else None
    return out


def _json(value) -> str:
    import json
    return json.dumps(value or {})
