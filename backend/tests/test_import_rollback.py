"""E2-4 — undoing an import.

The naive design (`DELETE WHERE import_job_id = :job`) is wrong here, and quietly
so. Four import types append; `inventory` UPSERTs. Deleting the rows an inventory
import "touched" would destroy stock records it only overwrote and never created.
So the importer writes an undo ledger — insert vs update, with a pre-image — and
rollback replays it.

The behaviour is verified end to end against live Postgres (see the commit
message); these tests pin the properties that a refactor could quietly break.
"""
import ast
import inspect
import pathlib
import textwrap

import pytest

from app.services import csv_import
from app.services import import_rollback as rb


MIGRATION = (pathlib.Path(__file__).resolve().parents[2]
             / "database" / "migrations" / "063_krishna_import_rollback.sql")


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def _code_only(fn) -> str:
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    node.decorator_list = []
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        node.body = node.body[1:]
    return ast.unparse(node)


# --------------------------------------------------------------------------
# The ledger's shape is what makes an exact undo possible.
# --------------------------------------------------------------------------

def test_the_ledger_distinguishes_insert_from_update():
    sql = _sql().lower()
    assert "op in ('insert', 'update')" in sql
    assert "before_image" in sql


def test_an_update_entry_must_carry_a_before_image():
    """An 'update' with no pre-image cannot be undone, so the DB forbids it."""
    sql = _sql().lower()
    assert "import_row_undo_update_has_image" in sql
    assert "op <> 'update' or before_image is not null" in sql


def test_an_insert_entry_must_not_carry_one():
    sql = _sql().lower()
    assert "import_row_undo_insert_has_no_image" in sql


def test_the_ledger_is_tenant_scoped_with_forced_rls():
    sql = _sql().lower()
    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "current_tenant_id()" in sql


def test_pre_existing_jobs_are_marked_non_reversible():
    """Every job that already exists was written without a ledger. The API must
    decline rather than delete rows it cannot prove the import created."""
    sql = _sql().lower()
    assert "reversible" in sql
    assert "default false" in sql


def test_the_status_domain_admits_the_new_lifecycle_states():
    """The job row is now written BEFORE the rows it owns (so they can carry its
    id), which needs 'running'; a reversed import needs 'rolled_back'."""
    sql = _sql().lower()
    assert "'running'" in sql and "'rolled_back'" in sql
    assert "import_jobs_status_check" in sql


def test_rollback_bookkeeping_cannot_disagree_with_status():
    sql = _sql().lower()
    assert "import_jobs_rollback_is_consistent" in sql


# --------------------------------------------------------------------------
# The upsert is the reason the ledger exists.
# --------------------------------------------------------------------------

def test_the_inventory_upsert_captures_its_pre_image_before_writing():
    code = _code_only(csv_import.commit_import)
    before_capture = code.index("SELECT to_jsonb(inv)")
    the_upsert = code.index("ON CONFLICT (store_id, item_id) DO UPDATE")
    assert before_capture < the_upsert, \
        "the pre-image must be read BEFORE the upsert overwrites it"


def test_an_upsert_over_an_existing_row_is_recorded_as_an_update():
    code = _code_only(csv_import.commit_import)
    assert "'update' if before else 'insert'" in code


def test_the_append_only_types_record_inserts():
    code = _code_only(csv_import.commit_import)
    for table in ("stores", "items", "suppliers", "sales_historical"):
        assert f"'{table}', 'insert'" in code, f"{table} must record an insert entry"


def test_a_conflicting_store_is_not_counted_as_imported():
    """ON CONFLICT DO NOTHING returns no row. Counting that as 'imported' would
    inflate the number we report back to the operator."""
    code = _code_only(csv_import.commit_import)
    assert "if store_id is None:" in code and "continue" in code


# --------------------------------------------------------------------------
# The AED truncation bug this work uncovered.
# --------------------------------------------------------------------------

def test_imported_aed_costs_keep_their_fils():
    """`COALESCE(:uc, 0)` leaves the bind parameter untyped, so Postgres resolves
    it from the neighbouring integer literal and stores 7.77 AED as 7. The cast is
    the fix; this guard is why it stays."""
    code = _code_only(csv_import.commit_import)
    assert "COALESCE(CAST(:uc AS NUMERIC), 0)" in code, "unit_cost must be cast to NUMERIC"
    assert "COALESCE(CAST(:ads AS NUMERIC), 0)" in code, "average_daily_sales must be cast"
    assert "COALESCE(:uc, 0)" not in code
    assert "COALESCE(:ads, 0)" not in code


def test_the_integer_columns_keep_their_integer_literals():
    """reorder_point IS an integer column — its untyped-param-next-to-`50` is
    correct, and casting it to NUMERIC would be cargo-culting the fix."""
    code = _code_only(csv_import.commit_import)
    assert "COALESCE(:rp, 50)" in code


# --------------------------------------------------------------------------
# Safety: what rollback refuses to do.
# --------------------------------------------------------------------------

def test_table_names_from_the_database_are_whitelisted_not_escaped():
    """`table_name` is interpolated into SQL. It can only ever be one of five."""
    assert rb.UNDOABLE_TABLES == {"stores", "items", "suppliers", "sales_historical", "inventory"}
    code = _code_only(rb.rollback_import)
    assert "UNDOABLE_TABLES" in code


def test_every_undoable_table_has_a_tenant_predicate():
    assert set(rb._TENANT_PREDICATE) == set(rb.UNDOABLE_TABLES)


def test_inventory_is_scoped_through_its_store():
    """inventory has no tenant_id column at all (migration 011 never added one),
    so a naive `tenant_id = :tid` would be a runtime error, and omitting the
    predicate would be a cross-tenant delete."""
    pred = rb._TENANT_PREDICATE["inventory"]
    assert "tenant_id" not in pred.split("SELECT")[0]
    assert "stores WHERE tenant_id = :tid" in pred


def test_a_non_reversible_job_is_refused():
    code = _code_only(rb.rollback_import)
    assert "not_reversible" in code
    assert "RollbackRefused" in code


def test_a_second_rollback_is_refused():
    """The ids the ledger names now belong to whatever was inserted after."""
    code = _code_only(rb.rollback_import)
    assert "already_rolled_back" in code


def test_a_foreign_key_violation_refuses_rather_than_cascades():
    """Cascading would destroy the customer's later work in order to undo their
    earlier mistake."""
    code = _code_only(rb.rollback_import)
    assert "IntegrityError" in code
    assert "referenced_by_newer_data" in code
    assert "CASCADE" not in code.upper()


def test_the_ledger_is_consumed_so_it_cannot_replay():
    code = _code_only(rb.rollback_import)
    assert "DELETE FROM import_row_undo" in code


@pytest.mark.asyncio
async def test_restore_skips_generated_columns():
    """`to_jsonb(row)` captures inventory.available_stock, which is GENERATED.
    Assigning it raises. Postgres recomputes it from what we do restore."""
    sql = rb._restore_sql("inventory",
                          {"current_stock": 1, "available_stock": 1, "id": 9, "tenant_id": 1},
                          frozenset({"current_stock"}))
    assert "available_stock" not in sql
    assert "id = " not in sql.split("WHERE")[0]
    assert "current_stock = r.current_stock" in sql


def test_restore_lets_postgres_coerce_the_json_types():
    """before_image is JSONB, so a DATE arrives as '2026-07-06' and asyncpg rejects
    a str for a DATE column. jsonb_populate_record coerces each field to its own
    column type, killing the whole class of bug."""
    sql = rb._restore_sql("inventory", {"current_stock": 1}, frozenset({"current_stock"}))
    assert "jsonb_populate_record(NULL::inventory" in sql


def test_restore_returns_none_when_nothing_is_writable():
    assert rb._restore_sql("stores", {"id": 1, "tenant_id": 1}, frozenset()) is None


def test_writable_columns_excludes_identity_and_generated():
    code = _code_only(rb._writable_columns)
    assert "attgenerated = ''" in code
    assert "attidentity  = ''" in code or "attidentity = ''" in code
