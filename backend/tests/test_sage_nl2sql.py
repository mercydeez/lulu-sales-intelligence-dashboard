"""
Tests for Sage's SQL safety gate and result shaping.

These cover the security-critical pure functions (no Ollama / no live DB needed):
the validator that stands between a generated query and the database, plus the
chart/no-query helpers. The end-to-end NL→SQL happy path is verified live in
Docker (it needs a running model + database).
"""
import pytest

from app.services.sage.validator import clean_and_validate, SQLValidationError
from app.services.sage.schema_catalog import ALLOWED_RELATIONS, MAX_ROWS
from app.services.sage.nl2sql import _extract_sql, _infer_chart, _safe_rows

ALLOWED = ALLOWED_RELATIONS


# ── Validator: things that must be REJECTED ──────────────────────────────────

@pytest.mark.parametrize("bad", [
    "INSERT INTO stores (name) VALUES ('x')",
    "UPDATE items SET unit_price_aed = 0",
    "DELETE FROM sales_fact_view",
    "DROP TABLE stores",
    "ALTER TABLE items ADD COLUMN x int",
    "TRUNCATE stores",
    "GRANT SELECT ON stores TO public",
    "SELECT 1; DROP TABLE stores",                      # multi-statement
    "SELECT * FROM stores -- sneaky comment",           # comment
    "SELECT * FROM stores /* block */",                 # block comment
    "SELECT * FROM pg_catalog.pg_user",                 # system schema
    "SELECT * FROM information_schema.tables",          # system schema
    "SELECT set_config('app.tenant_id','2',true)",      # GUC tamper
    "SELECT current_setting('app.tenant_id')",          # GUC read
    "SELECT * FROM users",                              # not allow-listed
    "SELECT * FROM suppliers",                          # not allow-listed
    "WITH x AS (SELECT 1) DELETE FROM stores",          # CTE then DML
    "VALUES (1),(2)",                                   # not SELECT/WITH
])
def test_rejects_unsafe(bad):
    with pytest.raises(SQLValidationError):
        clean_and_validate(bad, ALLOWED, MAX_ROWS)


# ── Validator: things that must PASS (and get LIMIT-bounded) ─────────────────

def test_accepts_basic_select_and_adds_limit():
    out = clean_and_validate("SELECT name FROM stores", ALLOWED, MAX_ROWS)
    assert out.lower().startswith("select")
    assert f"LIMIT {MAX_ROWS}" in out


def test_keeps_existing_limit():
    out = clean_and_validate("SELECT name FROM stores LIMIT 5", ALLOWED, MAX_ROWS)
    assert out.count("LIMIT") == 1
    assert "LIMIT 5" in out


def test_join_of_allowed_relations_ok():
    sql = ("SELECT s.name, SUM(f.sales) FROM sales_fact_view f "
           "JOIN stores s ON s.id = f.store_id GROUP BY s.name ORDER BY 2 DESC")
    out = clean_and_validate(sql, ALLOWED, MAX_ROWS)
    assert "sales_fact_view" in out and "stores" in out


def test_cte_referencing_its_own_name_ok():
    sql = ("WITH daily AS (SELECT date, SUM(sales) AS u FROM sales_fact_view GROUP BY date) "
           "SELECT * FROM daily ORDER BY date")
    out = clean_and_validate(sql, ALLOWED, MAX_ROWS)
    assert "daily" in out


def test_strips_markdown_fences():
    out = clean_and_validate("```sql\nSELECT name FROM items\n```", ALLOWED, MAX_ROWS)
    assert out.lower().startswith("select name from items")


def test_strips_sql_prefix_and_semicolon():
    out = clean_and_validate("SQL: SELECT name FROM items;", ALLOWED, MAX_ROWS)
    assert ";" not in out
    assert out.lower().startswith("select")


# ── nl2sql helpers ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", ["NO_QUERY", "no_query", "  NO QUERY  ", "I cannot answer that"])
def test_extract_sql_detects_no_query(raw):
    assert _extract_sql(raw) is None


def test_extract_sql_passes_through_query():
    assert _extract_sql("SELECT 1") == "SELECT 1"


def test_infer_chart_bar_for_label_plus_measure():
    cols = ["name", "units"]
    rows = [{"name": "A", "units": 10}, {"name": "B", "units": 7}]
    chart = _infer_chart(cols, rows)
    assert chart == {"type": "bar", "x": "name", "y": "units"}


def test_infer_chart_line_for_time_series():
    cols = ["date", "revenue"]
    rows = [{"date": "2026-01-01", "revenue": 5.0}, {"date": "2026-01-02", "revenue": 6.0}]
    chart = _infer_chart(cols, rows)
    assert chart["type"] == "line"


def test_infer_chart_none_for_single_row():
    assert _infer_chart(["name", "units"], [{"name": "A", "units": 1}]) is None


def test_safe_rows_serializes_decimal_and_date():
    import datetime
    from decimal import Decimal
    rows = [{"d": datetime.date(2026, 1, 1), "v": Decimal("3.50")}]
    safe = _safe_rows(rows)
    assert safe == [{"d": "2026-01-01", "v": 3.5}]
