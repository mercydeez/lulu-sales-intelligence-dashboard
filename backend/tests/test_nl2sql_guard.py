"""
Security tests for Sage's SQL allow-list guard (A2). Pure/DB-free — these are the
core injection defenses and must pass everywhere.
"""
import pytest

from app.services.nl2sql.guard import SqlGuardError, validate_sql

MAX = 200


def _ok(sql: str) -> str:
    return validate_sql(sql, MAX)


# --- valid queries pass and get a hard outer LIMIT --------------------------
def test_valid_select_is_wrapped_with_limit():
    out = _ok("SELECT store_name, revenue_aed FROM sage_store_performance ORDER BY revenue_aed DESC")
    assert "sage_result" in out and f"LIMIT {MAX}" in out


def test_valid_cte_allowed():
    out = _ok("WITH t AS (SELECT date, units FROM sage_daily_sales) SELECT * FROM t")
    assert "sage_result" in out


def test_inner_limit_is_still_capped_by_outer():
    out = _ok("SELECT * FROM sage_sales LIMIT 999999")
    # Outer wrapper enforces the cap regardless of the inner LIMIT.
    assert out.rstrip().endswith(f"LIMIT {MAX}")


# --- statement stacking / comments ------------------------------------------
@pytest.mark.parametrize("sql", [
    "SELECT 1 FROM sage_sales; DROP TABLE users",
    "SELECT 1 FROM sage_sales; SELECT 1 FROM sage_items",
])
def test_multiple_statements_rejected(sql):
    with pytest.raises(SqlGuardError):
        _ok(sql)


@pytest.mark.parametrize("sql", [
    "SELECT units FROM sage_sales -- sneaky",
    "SELECT units /* x */ FROM sage_sales",
])
def test_comments_rejected(sql):
    with pytest.raises(SqlGuardError):
        _ok(sql)


# --- DDL / DML rejected ------------------------------------------------------
@pytest.mark.parametrize("sql", [
    "DROP TABLE users",
    "DELETE FROM sage_sales",
    "UPDATE items SET unit_price_aed = 0",
    "INSERT INTO sage_sales VALUES (1)",
    "TRUNCATE sage_sales",
    "GRANT SELECT ON users TO sage_ro",
    "CREATE TABLE x (id int)",
    "ALTER VIEW sage_sales SET (security_invoker=true)",
])
def test_ddl_dml_rejected(sql):
    with pytest.raises(SqlGuardError):
        _ok(sql)


# --- allow-list: only sage_* views ------------------------------------------
@pytest.mark.parametrize("sql", [
    "SELECT * FROM users",
    "SELECT * FROM sales_fact_view",
    "SELECT * FROM tenant_api_keys",
    "SELECT email FROM sage_sales JOIN users ON true",
    "SELECT * FROM sage_sales UNION SELECT password_hash, 1, 1 FROM users",
    "SELECT * FROM public.users",
    "SELECT * FROM pg_catalog.pg_roles",
])
def test_non_allowlisted_relations_rejected(sql):
    with pytest.raises(SqlGuardError):
        _ok(sql)


# --- catalog / GUC / file functions blocked ---------------------------------
@pytest.mark.parametrize("sql", [
    "SELECT pg_sleep(10) FROM sage_sales",
    "SELECT set_config('app.tenant_id','2',false) FROM sage_sales",
    "SELECT current_setting('app.tenant_id') FROM sage_sales",
    "SELECT * FROM sage_sales WHERE units = (SELECT count(*) FROM information_schema.tables)",
    "SELECT current_user FROM sage_sales",
])
def test_dangerous_functions_rejected(sql):
    with pytest.raises(SqlGuardError):
        _ok(sql)


def test_empty_rejected():
    with pytest.raises(SqlGuardError):
        _ok("   ")


def test_non_select_rejected():
    with pytest.raises(SqlGuardError):
        _ok("EXPLAIN SELECT * FROM sage_sales")


# ============================================================================
# FALSE POSITIVES — the other half of the contract.
#
# Everything above asserts attacks are blocked. Nothing asserted that ordinary
# analytical SQL still gets through, and that asymmetry hid a real defect: the
# lexical checks scanned the RAW statement, so query DATA was read as if it were
# SQL. A literal containing "do", "set", "create", "into" or "--" was rejected,
# as was EXTRACT(MONTH FROM date) -- the guard saw `date` in FROM position and
# called it an unknown relation. Measured against realistic queries, 7 of 14 were
# refused.
#
# This is not a cosmetic concern. A rejected query does not surface an error: it
# silently degrades Sage to a canned rule-based reply, so an over-strict guard is
# indistinguishable to the user from an assistant that simply cannot answer.
# Guard changes must keep BOTH halves green.
# ============================================================================

@pytest.mark.parametrize("sql", [
    # Literals whose CONTENTS collide with forbidden keywords or comment markers.
    "SELECT * FROM sage_sales WHERE item_name = 'do not ship'",
    "SELECT * FROM sage_items WHERE item_name ILIKE '%do%'",
    "SELECT * FROM sage_items WHERE item_name ILIKE '%set%'",
    "SELECT * FROM sage_items WHERE category = 'create'",
    "SELECT * FROM sage_stores WHERE store_name = 'Into Mall'",
    "SELECT * FROM sage_items WHERE item_name = 'A--B'",
    "SELECT * FROM sage_items WHERE item_name = 'it''s a set'",
    # EXTRACT/SUBSTRING put a non-relation token in FROM position.
    "SELECT EXTRACT(MONTH FROM date) m, SUM(units) FROM sage_sales GROUP BY m",
    "SELECT EXTRACT(YEAR FROM date) y FROM sage_sales",
    # Ordinary analytics that must never regress.
    "SELECT store_name, SUM(units) AS u FROM sage_sales GROUP BY store_name",
    "SELECT date_trunc('month', date) m, SUM(units) FROM sage_sales GROUP BY m",
    "SELECT s.store_name, i.category FROM sage_sales s JOIN sage_items i ON i.item_id = s.item_id",
    "SELECT created_at FROM sage_sales",
])
def test_legitimate_analytical_sql_is_allowed(sql):
    out = _ok(sql)
    assert "sage_result" in out and f"LIMIT {MAX}" in out


# --- literal masking must not become its own bypass -------------------------
@pytest.mark.parametrize("sql", [
    # A statement hidden after a literal must still count as stacking.
    "SELECT * FROM sage_sales WHERE a='x'; DROP TABLE users",
    # '' is an escaped quote, not a terminator -- the tail is still a 2nd statement.
    "SELECT * FROM sage_sales WHERE a='it''s'; DELETE FROM users",
    # Dollar quoting would survive single-quote masking, so it is refused outright.
    "SELECT $$ ; DROP TABLE users $$ FROM sage_sales",
    "SELECT $tag$ anything $tag$ FROM sage_sales",
    # An unpaired quote means masking could not be trusted.
    "SELECT * FROM sage_sales WHERE a='oops",
    # A comment outside the literal is still a comment.
    "SELECT * FROM sage_sales WHERE a='x' -- drop",
    # A relation named only inside a literal is not a relation; the real one is.
    "SELECT 'from users' FROM sage_sales UNION SELECT email FROM users",
    # EXTRACT handling must not excuse a genuinely bad relation.
    "SELECT EXTRACT(MONTH FROM date) FROM users",
])
def test_literal_masking_is_not_a_bypass(sql):
    with pytest.raises(SqlGuardError):
        _ok(sql)
