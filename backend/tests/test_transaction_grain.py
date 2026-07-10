"""E2-5: basket / transaction-grain schema (migration 059).

The tables ship EMPTY on purpose. The load-bearing decisions are structural:
  * a parallel grain — never unioned into sales_fact_view, or a connected POS
    would double-count every dirham (ADR-010);
  * idempotent ingest — a replayed POS export cannot duplicate a receipt;
  * the line-total invariant is enforced by the DB, not by hope.

DB-free structural guards; the live constraint behaviour is exercised by the
`migrations` CI job (which applies 059 and runs the schema-drift check).
"""
import os
import re

_HERE = os.path.dirname(__file__)
_REPO = os.path.dirname(os.path.dirname(_HERE))
_MIGRATION = os.path.join(_REPO, "database", "migrations", "059_krishna_transaction_grain.sql")
_ADR = os.path.join(_REPO, "docs", "architecture", "ADR.md")


def _sql() -> str:
    with open(_MIGRATION, "r", encoding="utf-8") as fh:
        return fh.read()


def test_both_tables_are_created():
    sql = _sql()
    assert "CREATE TABLE IF NOT EXISTS transactions" in sql
    assert "CREATE TABLE IF NOT EXISTS transaction_lines" in sql


def test_ingest_is_idempotent_by_construction():
    """Replaying a POS export must not duplicate a receipt."""
    sql = _sql()
    assert "uq_transactions_source_ref" in sql
    assert "UNIQUE (tenant_id, source, txn_ref)" in sql
    # And a line number cannot repeat within a basket.
    assert "UNIQUE (transaction_id, line_no)" in sql


def test_line_total_invariant_is_enforced_by_the_database():
    """qty * price - discount = line_total, checked, not merely documented."""
    sql = _sql()
    assert "ck_transaction_lines_total" in sql
    assert "qty * unit_price_aed - discount_aed" in sql


def test_qty_is_units_and_supports_weighed_goods():
    """The daily grain's INTEGER cannot express 0.750 kg."""
    sql = _sql()
    assert re.search(r"qty\s+NUMERIC\(10,\s*3\)\s+NOT NULL", sql)


def test_money_columns_are_aed_numeric_never_mixed_with_units():
    sql = _sql()
    for col in ("unit_price_aed", "discount_aed", "line_total_aed", "total_aed"):
        assert col in sql
    # unit_price_aed must match items.unit_price_aed's numeric(10,2)
    assert re.search(r"unit_price_aed\s+NUMERIC\(10,\s*2\)", sql)


def test_voids_and_refunds_are_states_not_deletions():
    sql = _sql()
    assert "CHECK (status IN ('completed', 'voided', 'refunded'))" in sql


def test_header_is_tenant_scoped_and_lines_scope_through_the_parent():
    """House pattern (migration 020): line tables carry no tenant_id."""
    sql = _sql()
    assert "ALTER TABLE transactions ENABLE ROW LEVEL SECURITY" in sql
    assert "tenant_id = current_tenant_id()" in sql
    assert "ALTER TABLE transaction_lines ENABLE ROW LEVEL SECURITY" in sql
    assert "EXISTS (SELECT 1 FROM transactions t" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    # The child must NOT denormalise tenant_id.
    lines_block = sql.split("CREATE TABLE IF NOT EXISTS transaction_lines")[1].split(");")[0]
    assert "tenant_id" not in lines_block


def test_provenance_flag_follows_the_e0_8_convention():
    assert "is_synthetic        BOOLEAN NOT NULL DEFAULT FALSE" in _sql()


def test_the_grain_is_not_bridged_into_the_revenue_views():
    """ADR-010: a bridge would make the first connected POS double-count."""
    sql = _sql()
    for view in ("sales_fact_view", "metric_sales_fact", "sales_rollup_daily", "mv_daily"):
        # It may be *mentioned* in comments, but never created/altered/inserted into.
        assert f"CREATE OR REPLACE VIEW {view}" not in sql
        assert f"INSERT INTO {view}" not in sql
    assert "double-count" in sql  # the reason is written down where the next dev will look


def test_adr_records_the_no_bridge_decision():
    with open(_ADR, "r", encoding="utf-8") as fh:
        adr = fh.read()
    assert "ADR-010" in adr
    assert "double-count" in adr


def test_naming_traps_are_called_out():
    """Three existing tables sound related and are not."""
    sql = _sql()
    for trap in ("inventory_transactions", "employee_transactions", "basket_associations"):
        assert trap in sql
