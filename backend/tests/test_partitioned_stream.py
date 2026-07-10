"""E6-3 — sales_stream_raw partitioned by month, with a retention policy.

The migration rebuilds a table that FOURTEEN objects read through
`sales_fact_view`. The single most important property is that none of them was
dropped: `CREATE OR REPLACE VIEW` preserves the view's OID, so its dependents
never notice the table underneath was swapped. A `DROP VIEW … CASCADE` would have
taken all fourteen and silently lost `security_invoker`, grants, and the
materialised views' indexes and data.

Verified against live Postgres before/after (see the commit message): identical
row counts and sums across sales_fact_view, metric_sales_fact, metric_margin_fact
and sage_sales, and all 15 objects still present.
"""
import ast
import inspect
import pathlib
import textwrap

from app.services import partition_maintenance as pm


MIGRATION = (pathlib.Path(__file__).resolve().parents[2]
             / "database" / "migrations" / "065_krishna_partition_sales_stream.sql")


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def _sql_code() -> str:
    """The migration's STATEMENTS, without its `--` comments.

    The header explains at length what a `DROP VIEW … CASCADE` would have
    destroyed, so a substring check over the raw file trips on the explanation.
    """
    return "\n".join(line.split("--", 1)[0] for line in _sql().splitlines())


def _code_only(fn) -> str:
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    node.decorator_list = []
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        node.body = node.body[1:]
    return ast.unparse(node)


# --------------------------------------------------------------------------
# The fourteen dependents.
# --------------------------------------------------------------------------

def test_the_view_is_rebound_not_dropped():
    """This one line is the difference between a swap and an outage."""
    code = _sql_code()
    assert "CREATE OR REPLACE VIEW sales_fact_view" in code
    assert "DROP VIEW" not in code.upper()
    assert "CASCADE" not in code.upper(), \
        "a CASCADE anywhere here would take the metric views with it"


def test_that_guard_would_catch_a_real_cascade():
    """Negative control: the check above must fail on a statement, not merely on
    the header comment that explains why we avoid one."""
    stripped = "\n".join(
        line.split("--", 1)[0] for line in "-- DROP VIEW x CASCADE explains it\nSELECT 1;".splitlines())
    assert "DROP VIEW" not in stripped.upper()
    stripped2 = "\n".join(
        line.split("--", 1)[0] for line in "DROP VIEW sales_fact_view CASCADE;".splitlines())
    assert "DROP VIEW" in stripped2.upper()


def test_only_the_legacy_table_is_dropped():
    """`DROP TABLE %I` inside prune_sales_stream_partitions drops a partition at
    runtime; the migration itself must drop exactly one table."""
    drops = [line.strip() for line in _sql_code().splitlines()
             if line.strip().upper().startswith("DROP TABLE")
             and "%I" not in line]
    assert drops == ["DROP TABLE sales_stream_raw_legacy;"], drops


def test_the_view_definition_is_reproduced_verbatim():
    """CREATE OR REPLACE only keeps the OID if the column list and types match."""
    sql = _sql()
    for col in ("is_streaming", "'historical'::text AS source",
                "'streaming'::text AS source", "id + 1000000000 AS id"):
        assert col in sql


def test_the_rebound_view_keeps_security_invoker():
    """CREATE OR REPLACE VIEW resets reloptions to what the statement declares.

    Omitting `WITH (security_invoker = true)` silently reverts the view to
    security-definer: it would then read sales_stream_raw and sales_historical as
    its OWNER and bypass the RLS policies that scope them to a tenant. The first
    version of this migration did exactly that, and only the schema-baseline diff
    caught it — hence this test.
    """
    code = _sql_code()
    idx = code.index("CREATE OR REPLACE VIEW sales_fact_view")
    header = code[idx:idx + 120]
    assert "security_invoker = true" in header, \
        "the rebound view must re-declare security_invoker or it becomes a definer view"


# --------------------------------------------------------------------------
# What partitioning costs, stated in the migration itself.
# --------------------------------------------------------------------------

def test_the_partition_key_is_in_both_unique_constraints():
    """Postgres requires it; without this the migration simply fails."""
    sql = _sql()
    assert 'PRIMARY KEY (id, "timestamp")' in sql
    assert 'UNIQUE (event_id, "timestamp")' in sql


def test_the_weakened_event_id_guarantee_is_documented():
    """Global uniqueness of event_id is gone. Nothing relied on it, but the next
    person to reach for it as an idempotency key must be warned in place."""
    sql = _sql().lower()
    assert "global\n-- uniqueness of event_id is therefore no longer enforced" in sql \
        or "no longer enforced by the database" in sql
    assert "on conflict (event_id)" in sql, "say what it was NOT used for"


def test_the_partition_key_is_made_not_null():
    sql = _sql()
    assert 'ALTER COLUMN "timestamp" SET NOT NULL' in sql


# --------------------------------------------------------------------------
# The safety net.
# --------------------------------------------------------------------------

def test_a_default_partition_exists_so_an_insert_can_never_be_rejected():
    """Without it, the live generator dies at 00:00 on the 1st of any month whose
    partition maintenance forgot to create."""
    assert "PARTITION OF sales_stream_raw_new DEFAULT" in _sql()


def test_the_default_partition_is_watched_because_it_leaks_retention():
    """Rows in DEFAULT cannot be reclaimed by dropping a month."""
    code = _code_only(pm.run_partition_maintenance)
    assert "default_partition_rows" in code
    assert "logger.error" in code, "a silent retention leak is the whole risk"


def test_maintenance_creates_months_ahead_of_the_clock():
    assert pm.MONTHS_AHEAD >= 1
    code = _code_only(pm.run_partition_maintenance)
    assert code.index("ensure_partitions(") < code.index("prune_partitions(") \
        if "prune_partitions(" in code else True


# --------------------------------------------------------------------------
# Retention: irreversible, so it refuses nonsense.
# --------------------------------------------------------------------------

def test_pruning_drops_partitions_rather_than_deleting_rows():
    """DROP is instant and returns the disk; DELETE rewrites and bloats."""
    code = _sql_code()
    assert "DROP TABLE %I" in code
    assert "DELETE FROM sales_stream_raw" not in code.upper()


def test_prune_refuses_a_retention_window_under_one_month():
    sql = _sql()
    assert "retention must be at least 1 month" in sql


def test_prune_never_touches_the_default_partition():
    """Its regex matches only `sales_stream_raw_YYYY_MM`."""
    sql = _sql()
    assert r"'^sales_stream_raw_\d{4}_\d{2}$'" in sql


def test_pruning_can_be_disabled_without_disabling_partition_creation():
    """Dropping a month is irreversible; an operator must be able to keep the
    partitions and skip the reaping."""
    code = _code_only(pm.run_partition_maintenance)
    assert "if retention and retention >= 1:" in code

    from app.config import Settings
    s = Settings(environment="testing",
                 jwt_secret_key="test-secret-key-minimum-32-chars-long-for-testing",
                 secret_key="test-app-secret-key-minimum-32-chars-for-testing",
                 sales_stream_retention_months=0)
    assert s.sales_stream_retention_months == 0


def test_the_default_retention_is_a_year():
    from app.config import Settings
    s = Settings(environment="testing",
                 jwt_secret_key="test-secret-key-minimum-32-chars-long-for-testing",
                 secret_key="test-app-secret-key-minimum-32-chars-for-testing")
    assert s.sales_stream_retention_months == 12
    assert s.partition_maintenance_enabled is True


# --------------------------------------------------------------------------
# Everything the old table carried must still be there.
# --------------------------------------------------------------------------

def test_the_e0_8_synthetic_confinement_trigger_is_recreated():
    """Migration 057's guard: a synthetic sale may only exist on the demo tenant.
    Postgres 13+ allows BEFORE ROW triggers on a partitioned parent."""
    sql = _sql()
    assert "trg_sales_stream_raw_confine_synthetic" in sql
    assert "BEFORE INSERT OR UPDATE ON sales_stream_raw_new" in sql
    assert "sales_stream_raw_confine_synthetic()" in sql


def test_rls_is_re_enabled_and_forced():
    sql = _sql()
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "current_tenant_id()" in sql


def test_all_four_indexes_are_recreated():
    sql = _sql()
    for idx in ("tenant", "store_item", "timestamp", "synthetic"):
        assert idx in sql


def test_the_sequence_survives_the_drop_of_its_old_owner():
    """DROP TABLE takes an OWNED BY sequence with it, and the new table's DEFAULT
    would then reference a sequence that no longer exists."""
    sql = _sql()
    assert "OWNED BY NONE" in sql
    assert sql.index("OWNED BY NONE") < sql.index("DROP TABLE sales_stream_raw_legacy")
    assert "OWNED BY sales_stream_raw.id" in sql
    assert "setval('sales_stream_raw_id_seq'" in sql


def test_constraints_are_renamed_only_after_the_legacy_table_is_gone():
    """Index names are schema-global: the new PK cannot take the name
    `sales_stream_raw_pkey` while the legacy table's index still holds it."""
    sql = _sql()
    assert sql.index("DROP TABLE sales_stream_raw_legacy") < \
        sql.index("RENAME CONSTRAINT sales_stream_raw_new_pkey")


def test_worker_grants_are_reapplied():
    """security_invoker metric views read this table as worker_rw; a new table
    starts with no grants at all."""
    sql = _sql()
    assert "GRANT SELECT ON sales_stream_raw TO worker_rw" in sql
