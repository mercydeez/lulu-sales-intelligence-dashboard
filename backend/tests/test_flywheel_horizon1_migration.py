"""Migration 077 — the structural guarantees Horizon 1 depends on.

Source-level assertions, following the pattern of test_flywheel_migration.py:
they run without a live database so they hold in CI and on a laptop alike.

What is being protected here is not "the SQL parses" but a set of PROMISES the
rest of the system makes to its users:

  * evidence cannot be rewritten after the fact;
  * lawful erasure remains possible, so the append-only guard cannot make the
    product non-compliant or break tenant offboarding;
  * every new table is tenant-isolated at the database, per the 20 Jul 2026
    ruling that RLS is mandatory in production;
  * no shared table is altered — Flywheel extends the platform, never forks it.
"""
from __future__ import annotations

import os
import re

import pytest

NEW_TABLES = (
    "flywheel_preregistrations",
    "flywheel_readouts",
    "flywheel_holdout_balance",
    "flywheel_allocation_runs",
    "flywheel_allocation_lines",
    "flywheel_shadow_decisions",
    "flywheel_promotion_criteria",
)


def _find_migration() -> str:
    """Locate 077 from either the repo root or the container's /app.

    The container copies `backend/` to `/app`, so a path relative to this test
    file resolves differently in the two environments — hence the search rather
    than a hardcoded relative path.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (
        os.path.join(here, "..", "..", "database", "migrations"),
        os.path.join(here, "..", "database", "migrations"),
        "/app/database/migrations",
        os.path.join(os.getcwd(), "database", "migrations"),
    ):
        path = os.path.join(os.path.abspath(candidate),
                            "077_krishna_flywheel_horizon1.sql")
        if os.path.exists(path):
            return path
    pytest.skip("migration 077 not reachable from this working directory")


@pytest.fixture(scope="module")
def sql() -> str:
    with open(_find_migration(), "r", encoding="utf-8") as handle:
        return handle.read()


def _table_block(sql_text: str, table: str) -> str:
    start = sql_text.index(f"CREATE TABLE IF NOT EXISTS {table}")
    end = sql_text.index(");", start)
    return sql_text[start:end]


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def test_all_new_tables_are_created(sql):
    for table in NEW_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql, f"{table} missing"


def test_migration_is_transactional(sql):
    """All-or-nothing: a half-applied migration leaves the schema in a state no
    code was written against.

    Checks ORDER, not the first byte — the file opens with its rationale header,
    which is deliberate and worth keeping.
    """
    assert "\nBEGIN;" in sql, "migration is not wrapped in a transaction"
    assert sql.strip().endswith("COMMIT;")
    assert sql.index("\nBEGIN;") < sql.index("CREATE TABLE"), (
        "BEGIN; must precede the first DDL statement")


def test_every_new_table_carries_tenant_id(sql):
    for table in NEW_TABLES:
        block = _table_block(sql, table)
        assert "tenant_id" in block, f"{table} has no tenant_id"
        assert "REFERENCES tenants(id)" in block, f"{table}.tenant_id is not a real FK"


def test_money_columns_are_numeric_never_float(sql):
    """A float anywhere in a money path eventually disagrees with the ledger."""
    for match in re.finditer(r"^\s+(\w*aed\w*)\s+([A-Z ]+)", sql, re.M | re.I):
        column, sqltype = match.group(1), match.group(2).strip().upper()
        assert sqltype.startswith("NUMERIC"), (
            f"{column} is {sqltype}, must be NUMERIC")


# ---------------------------------------------------------------------------
# Tenancy — ruling #2 of 20 Jul 2026
# ---------------------------------------------------------------------------

def test_every_new_table_gets_policy_and_force_rls(sql):
    for table in NEW_TABLES:
        assert f"'{table}'" in sql, f"{table} absent from the RLS loop"
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "tenant_id = current_tenant_id()" in sql


def test_rls_policy_has_both_using_and_with_check(sql):
    """USING alone filters reads but permits a write that lands in another
    tenant. Both clauses, or the isolation is one-directional."""
    assert "USING (tenant_id = current_tenant_id())" in sql
    assert "WITH CHECK (tenant_id = current_tenant_id())" in sql


# ---------------------------------------------------------------------------
# Immutability, and its deliberate exception
# ---------------------------------------------------------------------------

def test_evidence_tables_are_append_only(sql):
    for table in ("flywheel_readouts", "flywheel_preregistrations"):
        assert f"BEFORE UPDATE OR DELETE ON {table}" in sql, (
            f"{table} is not protected against rewriting")


def test_update_is_blocked_unconditionally(sql):
    """There is no legitimate reason to edit a historical readout in place, so
    the guard must not offer an escape hatch for UPDATE — only for DELETE."""
    guard = sql[sql.index("CREATE OR REPLACE FUNCTION flywheel_forbid_mutation"):
                sql.index("STAGE 01")]
    assert "UPDATE is not permitted" in guard
    assert "TG_OP = 'DELETE'" in guard
    assert "allow_purge" in guard


def test_delete_escape_exists_for_lawful_erasure(sql):
    """A blanket DELETE block breaks ON DELETE CASCADE and makes the product
    non-compliant with the PDPL right to erasure. The escape must exist, be
    explicit, and be transaction-scoped."""
    guard = sql[sql.index("CREATE OR REPLACE FUNCTION flywheel_forbid_mutation"):
                sql.index("STAGE 01")]
    assert "current_setting('flywheel.allow_purge', true)" in guard, (
        "purge flag must be read with the missing_ok form so an unset GUC "
        "denies rather than raising")
    assert "RETURN OLD" in guard


def test_guard_documents_why_delete_is_not_absolute(sql):
    """The reasoning must survive in the file. A future maintainer who sees a
    'hole' in an append-only table and closes it would silently reintroduce
    both the cascade failure and the compliance breach."""
    guard = sql[:sql.index("STAGE 01")]
    assert "PDPL" in guard
    assert "CASCADE" in guard


# ---------------------------------------------------------------------------
# Correctness invariants
# ---------------------------------------------------------------------------

def test_readouts_are_idempotent_per_window(sql):
    """Re-running the scheduler on the same day must not double-record. This is
    what makes a lost pass safe to simply retry."""
    assert "uq_flywheel_readout_window UNIQUE (tenant_id, campaign_id, window_end)" in sql


def test_one_preregistration_per_campaign(sql):
    """Re-registering after seeing results is the abuse the table exists to
    prevent; the unique constraint is the enforcement, not the service."""
    assert "uq_flywheel_prereg_campaign UNIQUE (tenant_id, campaign_id)" in sql


def test_readout_window_must_be_non_empty(sql):
    """A zero-width window silently reports 0 retained in both arms, which reads
    as 'the campaign achieved nothing' rather than 'we measured nothing' — the
    exact bug already fixed once in measurement.py."""
    assert "CHECK (window_end > window_start)" in sql


def test_alpha_is_bounded(sql):
    assert "CHECK (alpha > 0 AND alpha < 0.5)" in sql


def test_allocation_mode_is_constrained(sql):
    assert "CHECK (mode IN ('greedy', 'portfolio'))" in sql


# ---------------------------------------------------------------------------
# Reuse, don't fork
# ---------------------------------------------------------------------------

def test_no_shared_table_is_altered(sql):
    """077 may reference shared tables by FK but must never modify one."""
    for table in re.findall(r"ALTER TABLE\s+(?:IF EXISTS\s+)?(\w+)", sql, re.I):
        assert table.startswith("flywheel_") or table == "%I", (
            f"077 alters the shared table '{table}' — Flywheel extends the "
            f"platform, it does not fork it")


def test_no_parallel_copy_of_a_platform_table(sql):
    """The guard from test_flywheel_migration.py, extended to 077."""
    for forbidden in ("flywheel_stores", "flywheel_items", "flywheel_sales",
                      "flywheel_inventory", "flywheel_users"):
        assert f"CREATE TABLE IF NOT EXISTS {forbidden}" not in sql


def test_seed_is_guarded_against_an_empty_database(sql):
    """Migration 074 failed on a clean deploy because it seeded unconditionally.
    077 must not repeat that."""
    assert "WHERE EXISTS (SELECT 1 FROM tenants WHERE id = 1)" in sql
    assert "ON CONFLICT (tenant_id, model_label) DO NOTHING" in sql


def test_promotion_bar_records_why_nothing_is_promoted(sql):
    """The seeded blocked_reason is user-visible governance copy, not a comment;
    it is what a due-diligence reader sees on the Shadow Mode page."""
    assert "three different winners" in sql
    assert "blocked_reason" in sql
