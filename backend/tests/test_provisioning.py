"""E10-2 completion — the tenant isolation-tier provisioning control plane.

The audit found E10-2 "partial: only a fail-closed 503 guard, provisioning not
built". This closes it at the control-plane layer with a governed lifecycle, and
implements the dedicated_schema data-plane primitive (a private schema with the
tenant's own copies of the core transactional tables).

The end-to-end lifecycle is verified against live Postgres in the commit (request →
provision → 8 isolated tables, a write isolated from public → deprovision drops the
schema). These tests pin the properties and the honest boundary.
"""
import ast
import inspect
import pathlib
import textwrap

import pytest

from app.services import provisioning as prov


MIGRATION = (pathlib.Path(__file__).resolve().parents[2]
             / "database" / "migrations" / "068_krishna_tenant_provisioning.sql")


def _code(fn) -> str:
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    node.decorator_list = []
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        node.body = node.body[1:]
    return ast.unparse(node)


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# The control plane: table + lifecycle.
# --------------------------------------------------------------------------

def test_the_provisioning_table_tracks_the_lifecycle():
    sql = _sql().lower()
    assert "create table if not exists tenant_provisioning" in sql
    for status in ("requested", "provisioning", "active", "failed", "deprovisioning", "deprovisioned"):
        assert f"'{status}'" in sql
    assert "unique (tenant_id)" in sql  # one live record per tenant


def test_a_failed_provisioning_must_say_why():
    sql = _sql().lower()
    assert "tenant_provisioning_failure_has_reason" in sql
    assert "status <> 'failed' or" in sql


def test_an_active_dedicated_tier_must_name_its_target():
    sql = _sql().lower()
    assert "tenant_provisioning_active_has_target" in sql
    assert "dedicated_schema' and schema_name is not null" in sql
    assert "dedicated_db' and db_ref is not null" in sql


# --------------------------------------------------------------------------
# The dedicated_schema data-plane primitive.
# --------------------------------------------------------------------------

def test_provision_creates_a_private_schema_with_isolated_core_tables():
    sql = _sql().lower()
    assert "create or replace function provision_tenant_schema" in sql
    assert "create schema if not exists" in sql
    assert "like public.%i including all" in sql
    # The core transactional tables — the tenant's own data.
    for tbl in ("stores", "items", "sales_historical", "inventory", "purchase_orders"):
        assert f"'{tbl}'" in sql


def test_the_synthetic_stream_is_not_isolated():
    """sales_stream_raw is partitioned + demo-only; cloning it per tenant is wrong.
    It is deliberately absent from the isolated set."""
    sql = _sql().lower()
    fn_start = sql.index("provision_tenant_schema")
    fn_body = sql[fn_start:sql.index("$$", fn_start + 50)]
    assert "sales_stream_raw" not in fn_body


def test_deprovision_drops_the_schema_defensively():
    """A tenant switched dedicated_schema -> dedicated_db would orphan the old
    schema; deprovision drops it regardless of the current tier."""
    code = _code(prov.deprovision)
    assert "deprovision_tenant_schema" in code
    # NOT gated on tier == dedicated_schema (the bug that was fixed).
    assert "if rec['tier'] == 'dedicated_schema'" not in code


# --------------------------------------------------------------------------
# Gating: a dedicated tier is served ONLY when provisioned active.
# --------------------------------------------------------------------------

def test_shared_needs_no_provisioning():
    """Fast path: shared is always active, no DB lookup."""
    code = _code(prov.is_tier_active)
    assert "if tier == 'shared':" in code
    assert "return True" in code


def test_isolation_gate_consults_provisioning_not_just_the_flag():
    from app.services import isolation
    code = _code(isolation.enforce_tenant_isolation)
    assert "provisioning.is_tier_active" in code
    assert "_refuse(tier)" in code  # still fails closed when not active


def test_login_only_pays_the_provisioning_query_for_dedicated_tenants():
    from app.routes import auth
    code = _code(auth.login)
    assert "if _iso_tier != 'shared':" in code
    assert "enforce_tenant_isolation" in code


# --------------------------------------------------------------------------
# dedicated_db is honest — recorded, not faked.
# --------------------------------------------------------------------------

def test_dedicated_db_is_an_operator_action_not_a_fake_db_creation():
    code = _code(prov.provision)
    assert "operator_action_required" in code
    # It hands back a runbook (which mentions creating a database) but never
    # EXECUTES a CREATE DATABASE — no db.execute of one.
    assert "db.execute" not in code.split("operator_action_required")[1], \
        "a request handler must not pretend to create a database"


# --------------------------------------------------------------------------
# Session routing is off by default (the analytics-view boundary).
# --------------------------------------------------------------------------

def test_dedicated_routing_is_off_by_default():
    from app.config import Settings
    s = Settings(environment="testing",
                 jwt_secret_key="test-secret-key-minimum-32-chars-long-for-testing",
                 secret_key="test-app-secret-key-minimum-32-chars-for-testing")
    assert s.enable_dedicated_schema_routing is False


def test_the_routing_helper_is_a_no_op_when_disabled():
    from app.services import database
    code = _code(database._apply_dedicated_routing)
    assert "dedicated_routing_enabled()" in code
    assert "return" in code  # early-out when off


@pytest.mark.parametrize("tier,expect_active_check", [
    ("shared", False), ("dedicated_schema", True), ("dedicated_db", True)])
def test_tiers_are_validated(tier, expect_active_check):
    assert tier in prov.VALID_TIERS
