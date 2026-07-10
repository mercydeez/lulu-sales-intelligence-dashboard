"""E2-4 — reverse an import, exactly.

Replays `import_row_undo` in reverse insertion order:

    op='insert' -> DELETE the row this import created.
    op='update' -> restore the row's `before_image` (inventory upserts only).

Three refusals, all deliberate:

1. A job written before the ledger existed is `reversible = FALSE`. We decline
   rather than delete rows we cannot prove this import created.

2. A job already rolled back is not rolled back twice. The second attempt would
   delete whatever now occupies those ids.

3. If a row created by the import is referenced by data created SINCE (a sale
   against an imported store, a PO against an imported supplier), Postgres raises
   a foreign-key violation and the whole rollback aborts. We surface that as a
   409 naming the blocking table. Cascading would silently destroy the
   customer's later work to undo their earlier mistake — never the right trade.

The whole replay runs in ONE transaction. A partial undo is a worse state than
either endpoint.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# `table_name` comes out of the database and goes into SQL. It can only ever be
# one of these five, and anything else is a bug or an attack — so it is checked
# against a literal set rather than escaped.
UNDOABLE_TABLES = frozenset({"stores", "items", "suppliers", "sales_historical", "inventory"})

# Columns that identify the row's owner, qualified with the alias `t`. `inventory`
# has no tenant_id at all (migration 011 never added one), so it is scoped through
# its store.
_TENANT_PREDICATE = {
    "stores": "t.tenant_id = :tid",
    "items": "t.tenant_id = :tid",
    "suppliers": "t.tenant_id = :tid",
    "sales_historical": "t.tenant_id = :tid",
    "inventory": "t.store_id IN (SELECT id FROM stores WHERE tenant_id = :tid)",
}

# Never restored from a before_image: identity and ownership are not the import's
# to rewrite, and `id` is the key we are matching on.
_IMMUTABLE = frozenset({"id", "tenant_id"})

# Populated from the catalogue on first use, per table.
_WRITABLE_COLUMNS: Dict[str, frozenset] = {}


async def _writable_columns(db: AsyncSession, table: str) -> frozenset:
    """Columns of `table` that an UPDATE may assign.

    `to_jsonb(row)` captures GENERATED columns too — inventory.available_stock is
    one — and assigning those raises `column "x" is a generated column`. Ask the
    catalogue rather than hardcode a list, so a new generated column added later
    does not break rollback silently.
    """
    if table in _WRITABLE_COLUMNS:
        return _WRITABLE_COLUMNS[table]
    rows = (await db.execute(text("""
        SELECT a.attname
          FROM pg_attribute a
         WHERE a.attrelid = CAST(:tbl AS regclass)
           AND a.attnum > 0
           AND NOT a.attisdropped
           AND a.attgenerated = ''      -- not a generated column
           AND a.attidentity  = ''      -- not GENERATED ... AS IDENTITY
    """), {"tbl": table})).scalars().all()
    cols = frozenset(rows) - _IMMUTABLE
    _WRITABLE_COLUMNS[table] = cols
    return cols


class RollbackRefused(Exception):
    """The rollback cannot proceed and no rows were touched."""

    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


async def rollback_status(db: AsyncSession, tenant_id: int, job_id: int) -> Optional[Dict[str, Any]]:
    row = (await db.execute(text("""
        SELECT j.id, j.import_type, j.status, j.imported_rows, j.reversible,
               j.rolled_back_at, j.rolled_back_by, j.created_at,
               (SELECT COUNT(*) FROM import_row_undo u WHERE u.import_job_id = j.id) AS undo_rows
          FROM import_jobs j
         WHERE j.id = :jid AND j.tenant_id = :tid
    """), {"jid": job_id, "tid": tenant_id})).mappings().fetchone()
    if not row:
        return None
    d = dict(row)
    d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
    d["rolled_back_at"] = d["rolled_back_at"].isoformat() if d.get("rolled_back_at") else None
    d["can_rollback"] = bool(d["reversible"]) and d["rolled_back_at"] is None and d["undo_rows"] > 0
    if not d["can_rollback"]:
        d["reason"] = (
            "already_rolled_back" if d["rolled_back_at"]
            else "not_reversible" if not d["reversible"]
            else "nothing_to_undo"
        )
    return d


def _restore_sql(table: str, before: Dict[str, Any], writable: frozenset) -> Optional[str]:
    """The UPDATE that puts a row back exactly as it was.

    Values are fed through `jsonb_populate_record(NULL::<table>, …)` rather than
    bound one by one. `before_image` is JSONB, so a DATE comes back as the string
    '2026-07-06' and a TIMESTAMPTZ as an ISO string — asyncpg binds those strictly
    and rejects them ('str' object has no attribute 'toordinal'). Letting Postgres
    coerce each field to its own column type sidesteps the whole class of bug.

    Generated columns are skipped; Postgres recomputes them from the columns we do
    restore, so nothing is lost.
    """
    cols = sorted(c for c in before if c in writable)
    if not cols:
        return None
    assignments = ", ".join(f"{c} = r.{c}" for c in cols)
    return (f"UPDATE {table} AS t SET {assignments} "
            f"FROM jsonb_populate_record(NULL::{table}, CAST(:img AS JSONB)) AS r "
            f"WHERE t.id = :row_id AND {_TENANT_PREDICATE[table]}")


async def rollback_import(db: AsyncSession, tenant_id: int, job_id: int, *, user: str) -> Dict[str, Any]:
    """Undo every row this import wrote. All-or-nothing; the caller commits."""
    job = (await db.execute(text("""
        SELECT id, reversible, rolled_back_at, import_type
          FROM import_jobs
         WHERE id = :jid AND tenant_id = :tid
         FOR UPDATE
    """), {"jid": job_id, "tid": tenant_id})).mappings().fetchone()

    if not job:
        raise RollbackRefused("not_found", "Import job not found for this tenant")
    if job["rolled_back_at"] is not None:
        raise RollbackRefused(
            "already_rolled_back",
            "This import has already been rolled back; rolling it back again would "
            "delete whatever now occupies those rows")
    if not job["reversible"]:
        raise RollbackRefused(
            "not_reversible",
            "This import ran before the undo ledger existed, so we cannot prove "
            "which rows it created. Rolling it back could delete data it never wrote.")

    entries = (await db.execute(text("""
        SELECT id, table_name, op, row_id, before_image
          FROM import_row_undo
         WHERE import_job_id = :jid AND tenant_id = :tid
         ORDER BY id DESC
    """), {"jid": job_id, "tid": tenant_id})).mappings().all()

    if not entries:
        raise RollbackRefused("nothing_to_undo", "This import wrote no reversible rows")

    unknown = {e["table_name"] for e in entries} - UNDOABLE_TABLES
    if unknown:
        raise RollbackRefused("unknown_table",
                              f"Undo ledger references unsupported table(s): {sorted(unknown)}")

    deleted, restored = 0, 0
    try:
        for e in entries:
            table = e["table_name"]
            if e["op"] == "insert":
                res = await db.execute(
                    text(f"DELETE FROM {table} AS t "
                         f"WHERE t.id = :row_id AND {_TENANT_PREDICATE[table]}"),
                    {"row_id": e["row_id"], "tid": tenant_id})
                deleted += res.rowcount or 0
            else:
                before = e["before_image"] or {}
                writable = await _writable_columns(db, table)
                sql = _restore_sql(table, before, writable)
                if not sql:
                    continue
                res = await db.execute(
                    text(sql),
                    {"img": json.dumps(before, default=str),
                     "row_id": e["row_id"], "tid": tenant_id})
                restored += res.rowcount or 0
    except IntegrityError as exc:
        # A row this import created is now referenced by newer data. Undoing it
        # would take that newer data with it.
        raise RollbackRefused(
            "referenced_by_newer_data",
            "Rows created by this import are referenced by data added since "
            "(for example sales recorded against an imported store). Nothing was "
            f"changed. Underlying constraint: {getattr(exc.orig, 'constraint_name', None) or 'foreign key'}"
        ) from exc

    await db.execute(text("""
        UPDATE import_jobs
           SET status = 'rolled_back', rolled_back_at = now(), rolled_back_by = :by
         WHERE id = :jid AND tenant_id = :tid
    """), {"by": user, "jid": job_id, "tid": tenant_id})

    # The ledger is consumed. Keeping it would let a second rollback replay against
    # ids that now belong to somebody else's rows.
    await db.execute(text("""
        DELETE FROM import_row_undo WHERE import_job_id = :jid AND tenant_id = :tid
    """), {"jid": job_id, "tid": tenant_id})

    return {
        "job_id": job_id,
        "import_type": job["import_type"],
        "rows_deleted": deleted,
        "rows_restored": restored,
        "undo_entries": len(entries),
        "rolled_back_by": user,
    }
