"""Migration 080 — Horizon 4 structural guarantees (source-level, no live DB)."""
from __future__ import annotations

import os
import re

import pytest

NEW_TABLES = (
    "flywheel_seasonality_calendar", "flywheel_coalition_partners",
    "flywheel_coalition_activity", "flywheel_coalition_attribution",
    "flywheel_shelf_life", "flywheel_outcome_pricing",
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
                            "080_krishna_flywheel_horizon4.sql")
        if os.path.exists(path):
            return path
    pytest.skip("migration 080 not reachable")


@pytest.fixture(scope="module")
def sql() -> str:
    with open(_find_migration(), "r", encoding="utf-8") as handle:
        return handle.read()


def test_all_new_tables_created(sql):
    for t in NEW_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {t}" in sql, f"{t} missing"


def test_transactional(sql):
    assert "\nBEGIN;" in sql and sql.strip().endswith("COMMIT;")


def test_tenant_scoped_forced_rls_and_grants(sql):
    for t in NEW_TABLES:
        assert f"'{t}'" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "WITH CHECK (tenant_id = current_tenant_id())" in sql
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO app_rw" in sql


def test_demand_multiplier_is_bounded(sql):
    """A fat-fingered 20x must not be able to make the optimizer hand out the
    store — the multiplier is CHECK-constrained."""
    assert "demand_multiplier > 0 AND demand_multiplier <= 5" in sql


def test_seasonality_unique_handles_null_category(sql):
    """The NULL-category trap: a plain UNIQUE(tenant,name,category) would let
    duplicate ('Ramadan', NULL) rows through and re-seeding would stack them. The
    fix is a COALESCE unique index, and the seed guards on NOT EXISTS."""
    assert "COALESCE(category, '')" in sql, "unique index must collapse NULL category"
    assert "NOT EXISTS" in sql, "seed must be idempotent regardless of NULL category"
    # The old, broken constraint form must be gone.
    assert "UNIQUE (tenant_id, name, category)" not in sql


def test_attribution_weight_is_bounded(sql):
    """A weight is a fraction in [0,1]; the service asserts the per-customer sum
    is 1, the DB bounds each row."""
    assert "attribution_weight >= 0 AND attribution_weight <= 1" in sql


def test_shelf_life_window_is_sane(sql):
    assert "expires_on >= received_on" in sql
    assert "units >= 0" in sql


def test_outcome_pricing_share_is_bounded(sql):
    """A margin share above 50% is almost certainly a mistake and is refused at
    the DB; the real gate (evidence) is enforced in the service."""
    assert "margin_share_pct > 0 AND margin_share_pct <= 0.5" in sql
    assert "gate_met" in sql
    assert "gate_readouts_required" in sql


def test_seed_is_guarded_against_empty_db(sql):
    assert "WHERE EXISTS (SELECT 1 FROM tenants WHERE id = 1)" in sql
    assert "Ramadan" in sql and "Summer Lull" in sql


def test_no_shared_table_is_altered(sql):
    for table in re.findall(r"ALTER TABLE\s+(?:IF EXISTS\s+)?(\w+)", sql, re.I):
        assert table.startswith("flywheel_") or table == "%I", (
            f"080 alters shared table '{table}' — Flywheel extends, never forks")


def test_no_parallel_copy_of_a_platform_table(sql):
    for forbidden in ("flywheel_stores", "flywheel_items_v2", "flywheel_inventory"):
        assert f"CREATE TABLE IF NOT EXISTS {forbidden}" not in sql
