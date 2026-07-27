"""E2-3: effective-dated item cost + margin.

Cost is a time series, not a scalar. These are DB-free structural guards; the
live semantics (overlap rejection, SCD-2 close-and-open, point-in-time resolution,
NULL-never-zero margin) are exercised against a real Postgres by the `migrations`
CI job, which applies 058 and the schema-drift check.
"""
import os
import re

_HERE = os.path.dirname(__file__)
_REPO = os.path.dirname(os.path.dirname(_HERE))
_MIGRATION = os.path.join(_REPO, "database", "migrations", "058_krishna_item_cost_margin.sql")


def _migration_sql() -> str:
    with open(_MIGRATION, "r", encoding="utf-8") as fh:
        return fh.read()


def test_migration_exists_and_is_effective_dated():
    sql = _migration_sql()
    assert "CREATE TABLE IF NOT EXISTS item_costs" in sql
    assert "valid_from" in sql and "valid_until" in sql


def test_overlapping_cost_periods_are_impossible():
    """Two costs in effect on the same day would make COGS ambiguous."""
    sql = _migration_sql()
    assert "item_costs_no_overlap" in sql
    assert "EXCLUDE USING gist" in sql
    assert "daterange(valid_from, valid_until, '[)')" in sql


def test_items_gets_the_blueprint_named_current_cost_column():
    sql = _migration_sql()
    assert "ALTER TABLE items ADD COLUMN IF NOT EXISTS unit_cost_aed" in sql
    # No DEFAULT — an unknown cost must stay NULL, never 0 (which reads as free).
    m = re.search(r"ADD COLUMN IF NOT EXISTS unit_cost_aed[^\n;]*", sql)
    assert m and "DEFAULT" not in m.group(0).upper()


def test_point_in_time_resolver_and_scd2_writer_exist():
    sql = _migration_sql()
    assert "CREATE OR REPLACE FUNCTION item_cost_at" in sql
    # set_item_cost closes the straddling period; a bare INSERT always collides
    # with the open-ended current period.
    assert "CREATE OR REPLACE FUNCTION set_item_cost" in sql
    assert "SET valid_until = p_from" in sql


def test_margin_view_joins_cost_as_of_the_sale_date():
    sql = _migration_sql()
    assert "CREATE OR REPLACE VIEW metric_margin_fact" in sql
    # The as-of predicate — not a blended average.
    assert "s.date     >= c.valid_from" in sql
    assert "c.valid_until IS NULL OR s.date < c.valid_until" in sql
    # RLS follows the caller, matching the metric_* house style (E6-1).
    assert "security_invoker = true" in sql


def test_new_table_is_tenant_scoped_with_rls():
    sql = _migration_sql()
    assert "tenant_id" in sql
    assert "ALTER TABLE item_costs ENABLE ROW LEVEL SECURITY" in sql
    assert "tenant_id = current_tenant_id()" in sql


def test_backfill_is_labelled_not_disguised_as_real_cost():
    """The seeded cost is derived from the blended inventory column — a reader must
    be able to tell it apart from a cost the tenant actually supplied."""
    sql = _migration_sql()
    assert "'backfill_inventory'" in sql
    assert "source" in sql


def test_roi_and_kpis_share_one_needs_cost_string():
    """Every cost-gated surface must say the same thing to the user."""
    from app.routes.kpis import _NEEDS_COST as kpi_needs
    from app.services.roi import _NEEDS_COST as roi_needs

    assert kpi_needs == roi_needs
    assert "cost" in kpi_needs.lower()


def test_import_writes_cost_through_the_scd2_helper():
    """csv_import must not hand-roll the close/insert — it goes through set_item_cost."""
    import inspect

    from app.services import csv_import

    src = inspect.getsource(csv_import.commit_import)
    assert "set_item_cost" in src
    assert "unit_cost_aed" in csv_import.SCHEMAS["items"]["fields"]


def test_mock_inventory_stream_no_longer_invents_a_cost():
    """generate_inventory_update used to emit unit_cost=random.uniform(10,100)."""
    import inspect

    from app.routes import stream

    # Assert on the CODE, not the docstring — which deliberately quotes the removed
    # line to explain why it went. Strip the docstring node so it can't mask a real
    # regression (or fake one).
    import ast
    import textwrap

    fn = ast.parse(textwrap.dedent(inspect.getsource(stream.generate_inventory_update))).body[0]
    if fn.body and isinstance(fn.body[0], ast.Expr) and isinstance(fn.body[0].value, ast.Constant):
        fn.body = fn.body[1:]
    body = ast.unparse(fn)

    assert "'unit_cost'" not in body      # no cost key in the emitted payload
    assert "random.uniform" not in body   # nothing fabricates a money value
    assert "'is_synthetic': True" in body # the mock event says what it is
