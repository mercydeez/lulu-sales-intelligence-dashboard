"""Migration 079 — Horizon 3 structural guarantees (source-level, no live DB).

Protects the promises the two tracks rest on: supplier money cannot be overspent
or over-settled, an issued settlement cannot be silently rewritten, every table
is tenant-isolated with FORCE RLS (ruling #2), and no shared platform table is
altered.
"""
from __future__ import annotations

import os
import re

import pytest

NEW_TABLES = (
    "flywheel_supplier_funding", "flywheel_supplier_funding_skus",
    "flywheel_settlements", "flywheel_cannibalization", "flywheel_substitution",
    "flywheel_profiling_objections", "flywheel_pos_staging",
    "flywheel_identity_links",
)


def _find_migration() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (
        os.path.join(here, "..", "..", "database", "migrations"),
        os.path.join(here, "..", "database", "migrations"),
        "/app/database/migrations",
        os.path.join(os.getcwd(), "database", "migrations"),
    ):
        path = os.path.join(os.path.abspath(candidate),
                            "079_krishna_flywheel_horizon3.sql")
        if os.path.exists(path):
            return path
    pytest.skip("migration 079 not reachable")


@pytest.fixture(scope="module")
def sql() -> str:
    with open(_find_migration(), "r", encoding="utf-8") as handle:
        return handle.read()


def test_all_new_tables_created(sql):
    for t in NEW_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {t}" in sql, f"{t} missing"


def test_transactional(sql):
    assert "\nBEGIN;" in sql and sql.strip().endswith("COMMIT;")


def test_every_table_tenant_scoped_with_forced_rls(sql):
    for t in NEW_TABLES:
        assert f"'{t}'" in sql, f"{t} not in RLS loop"
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "USING (tenant_id = current_tenant_id())" in sql
    assert "WITH CHECK (tenant_id = current_tenant_id())" in sql


def test_app_rw_is_granted_on_new_tables(sql):
    """Ruling #2: the request path is the non-owner app_rw role, which needs
    table privileges (RLS filters rows, it does not grant table access)."""
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO app_rw" in sql
    assert "pg_roles WHERE rolname = 'app_rw'" in sql


def test_supplier_money_cannot_be_overspent(sql):
    """The core Track B invariant: a supplier's committed money is a hard ceiling
    on spend, and settlement cannot exceed spend — enforced by the DB."""
    assert "CHECK (spent_aed <= committed_aed)" in sql
    assert "CHECK (settled_aed <= spent_aed)" in sql


def test_issued_settlement_is_immutable(sql):
    """An issued settlement's amount and period are frozen — a supplier query is
    a dispute transition, not an edit of what they were charged."""
    assert "flywheel_settlement_immutable" in sql
    assert "BEFORE UPDATE ON flywheel_settlements" in sql
    guard = sql[sql.index("flywheel_settlement_immutable"):]
    assert "amount_due_aed <> OLD.amount_due_aed" in guard
    assert "restrict_violation" in guard


def test_funding_covers_at_least_the_supplier_scope(sql):
    """The supplier-scope table exists and is unique per (funding, item) so a SKU
    cannot be double-scoped."""
    assert "flywheel_supplier_funding_skus" in sql
    assert "uq_flywheel_funding_sku UNIQUE (funding_id, item_id)" in sql


def test_cannibalization_records_reliability(sql):
    """A supplier is never charged on a number the retailer would not defend, so
    the reliability of the estimate is a stored column, not an afterthought."""
    assert "is_reliable" in sql
    assert "net_incremental_margin_aed" in sql
    assert "method" in sql and "'did'" in sql


def test_profiling_objection_is_uniquely_per_customer(sql):
    """One live objection per customer; the PDPL right is a lifecycle on one row,
    not an ever-growing log that could disagree with itself."""
    assert "uq_flywheel_objection UNIQUE (tenant_id, customer_id)" in sql
    assert "pdpl" in sql.lower()


def test_identity_can_decline_to_link(sql):
    """A wrong merge corrupts three stores at once; the schema must allow
    'ambiguous' and 'unlinked', not force a customer_id."""
    assert "'ambiguous'" in sql and "'unlinked'" in sql
    # customer_id is nullable (no NOT NULL) so an unresolved transaction can stay
    # anonymous. Whitespace-tolerant so reformatting the migration cannot silently
    # flip this guarantee.
    link_block = sql[sql.index("CREATE TABLE IF NOT EXISTS flywheel_identity_links"):]
    link_block = link_block[:link_block.index(");")]
    assert re.search(r"customer_id\s+INTEGER\s+REFERENCES", link_block), \
        "identity link's customer_id must be a nullable FK"
    assert not re.search(r"customer_id\s+INTEGER\s+NOT\s+NULL", link_block), \
        "identity link's customer_id must NOT be NOT NULL — a record may stay unlinked"


def test_pos_ingestion_is_idempotent(sql):
    """Re-importing the same export file must be a no-op, not a duplicate."""
    assert "uq_flywheel_pos_txn UNIQUE (tenant_id, external_txn_id)" in sql


def test_no_shared_table_is_altered(sql):
    for table in re.findall(r"ALTER TABLE\s+(?:IF EXISTS\s+)?(\w+)", sql, re.I):
        assert table.startswith("flywheel_") or table == "%I", (
            f"079 alters shared table '{table}' — Flywheel extends, never forks")


def test_no_parallel_copy_of_a_platform_table(sql):
    for forbidden in ("flywheel_suppliers", "flywheel_items", "flywheel_stores",
                      "flywheel_products"):
        assert f"CREATE TABLE IF NOT EXISTS {forbidden}" not in sql
