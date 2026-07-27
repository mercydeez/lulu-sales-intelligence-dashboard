"""E10-2 (isolation tiers) and E10-7 (read-replica routing).

Both are places where the tempting implementation is the dishonest one:

  * E10-2 — store `isolation_tier`, serve everyone from the shared pool, call the
    column future-proofing. A tenant who paid for a dedicated database and is
    silently sitting in the shared one has been mis-sold, and nothing errors until
    an auditor asks. So the app fails CLOSED on a tier it cannot deliver.

  * E10-7 — route reads to a replica and hope nothing reads its own write. A
    replica is BEHIND the primary; a user who saves a promotion and is then shown
    a list that does not contain it will not blame replication lag. So the
    dependency is opt-in per route, and only for aggregates over days of data.
"""
import ast
import inspect
import pathlib
import textwrap

import pytest
from fastapi import HTTPException

from app.services import isolation


def _find_migration(name: str) -> pathlib.Path:
    """Robust to the repo layout (backend/ + database/ siblings) AND the container
    layout (both under /app)."""
    here = pathlib.Path(__file__).resolve()
    for base in here.parents:
        cand = base / "database" / "migrations" / name
        if cand.is_file():
            return cand
    return here.parents[2] / "database" / "migrations" / name


MIGRATION = _find_migration("066_krishna_isolation_tiers.sql")
ROUTES_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "routes"


def _settings(**kw):
    from app.config import Settings
    return Settings(environment="testing",
                    jwt_secret_key="test-secret-key-minimum-32-chars-long-for-testing",
                    secret_key="test-app-secret-key-minimum-32-chars-for-testing",
                    **kw)


def _code_only(fn) -> str:
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    node.decorator_list = []
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        node.body = node.body[1:]
    return ast.unparse(node)


# ==========================================================================
# E10-2 — isolation tiers
# ==========================================================================

def test_provisionable_tiers_include_dedicated_schema():
    """E10-2 completion: the schema-provisioning primitive exists (migration 068),
    so dedicated_schema is now provisionable. dedicated_db stays operator-only.
    Actual SERVING is still gated on the provisioning control plane (below)."""
    assert _settings().supported_isolation_tiers == ["shared", "dedicated_schema"]


def test_the_database_constrains_the_tier_to_known_values():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "isolation_tier in ('shared', 'dedicated_schema', 'dedicated_db')" in sql
    assert "default 'shared'" in sql


def test_a_provisionable_tier_passes_the_static_check(monkeypatch):
    monkeypatch.setattr(isolation, "get_settings", lambda: _settings())
    isolation.assert_supported("shared")            # does not raise
    isolation.assert_supported("dedicated_schema")  # now provisionable, does not raise


def test_a_tier_this_deployment_cannot_provision_fails_closed(monkeypatch):
    """dedicated_db is not in the provisionable set by default → refused."""
    monkeypatch.setattr(isolation, "get_settings", lambda: _settings())
    with pytest.raises(HTTPException) as ei:
        isolation.assert_supported("dedicated_db", tenant_id=7)
    assert ei.value.status_code == 503
    d = ei.value.detail
    assert d["error"] == "isolation_tier_not_provisioned"
    assert d["isolation_tier"] == "dedicated_db"
    assert "did not agree to" in d["message"] or "not yet provisioned" in d["message"]


def test_the_real_gate_is_provisioning_active_not_the_static_list():
    """enforce_tenant_isolation consults the provisioning control plane: a tenant
    whose isolation_tier is dedicated_schema is served ONLY when provisioning is
    active, even though dedicated_schema is in the provisionable list."""
    from app.services import isolation as iso
    code = _code_only(iso.enforce_tenant_isolation)
    assert "provisioning.is_tier_active" in code
    assert "_refuse(tier)" in code


def test_a_missing_tier_is_treated_as_shared(monkeypatch):
    monkeypatch.setattr(isolation, "get_settings", lambda: _settings())
    isolation.assert_supported(None)


def test_both_doors_are_closed():
    """Login and API-key auth are the two ways into a tenant's data. Both now go
    through the provisioning-aware enforce_tenant_isolation gate."""
    from app.routes import auth, public_api

    assert "enforce_tenant_isolation" in _code_only(auth.login)
    assert "enforce_tenant_isolation" in _code_only(public_api.get_api_context)


def test_the_login_tier_check_is_free_for_shared_tenants():
    """A `shared` tenant (the overwhelming majority) pays NO extra query — the
    tier rides along on authenticate_user's existing JOIN and short-circuits.
    Only a dedicated tenant pays the provisioning lookup."""
    from app.services import auth_service

    src = inspect.getsource(auth_service.AuthService.authenticate_user)
    assert "isolation_tier" in src
    assert "LEFT JOIN tenants" in src

    from app.routes import auth
    code = _code_only(auth.login)
    # shared short-circuits before any session is opened.
    assert "if _iso_tier != 'shared':" in code


def test_authenticate_user_actually_returns_the_tier():
    """BEHAVIOURAL, not a source grep.

    The first version selected isolation_tier in the SQL but dropped it from the
    curated dict authenticate_user returns. `user_data.get("isolation_tier")` was
    then None, `assert_supported(None)` treats that as 'shared', and a
    dedicated_db tenant logged straight in. Every source-string test still passed;
    only hitting the live endpoint caught it.
    """
    from app.services import auth_service

    src = inspect.getsource(auth_service.AuthService.authenticate_user)
    body = src[src.index('"id": user['):]
    returned_keys = body[:body.index("return user_data")]
    assert '"isolation_tier"' in returned_keys, (
        "authenticate_user selects isolation_tier but must also RETURN it, or "
        "/login's tier check silently reads None and passes"
    )


@pytest.mark.parametrize("tier,expect_raise", [("shared", False), ("dedicated_db", True),
                                               ("dedicated_schema", False), (None, False)])
def test_static_check_admits_provisionable_tiers_refuses_the_rest(monkeypatch, tier, expect_raise):
    """assert_supported guards the provisionable set (shared + dedicated_schema);
    dedicated_db (operator-only) still raises. The provisioning-active gate is a
    separate, stricter check exercised live in test_provisioning.py."""
    monkeypatch.setattr(isolation, "get_settings", lambda: _settings())
    if expect_raise:
        with pytest.raises(HTTPException) as ei:
            isolation.assert_supported(tier)
        assert ei.value.status_code == 503
    else:
        isolation.assert_supported(tier)


def test_the_isolation_check_precedes_issuing_credentials():
    """Refusing after the token is minted would still hand out a session."""
    from app.routes import auth
    code = _code_only(auth.login)
    assert code.index("enforce_tenant_isolation") < code.index("two_factor_enabled")


# ==========================================================================
# E10-7 — read-replica routing
# ==========================================================================

def test_no_replica_configured_means_reads_go_to_the_primary():
    """With DATABASE_REPLICA_URL unset the dependency is a no-op — nothing here is
    dormant, the routing is live with one node to route to."""
    assert _settings().database_replica_url is None
    from app.services import database
    assert database.replica_configured() is False
    assert database.read_session is database.rls_session


def test_the_replica_url_is_forced_onto_the_async_driver():
    from app.services.database import _derive_replica_url
    assert _derive_replica_url("postgresql://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"
    assert _derive_replica_url("postgres://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"
    assert _derive_replica_url("postgresql+asyncpg://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"


def test_the_read_session_never_commits():
    """A replica is read-only. A route that writes through this dependency should
    surface as an error, not silently reach the primary."""
    from app.services import database
    code = inspect.getsource(database.get_read_db)
    assert "await session.rollback()" in code
    assert "await session.commit()" not in code


def test_the_replica_engine_is_disposed_on_shutdown():
    from app.services import database
    code = inspect.getsource(database.close_db)
    assert "replica_engine" in code


def _routers_using(dep: str):
    """Route modules that bind `dep` as a FastAPI dependency."""
    out = []
    for path in ROUTES_DIR.glob("*.py"):
        src = path.read_text(encoding="utf-8")
        if f"Depends({dep})" in src:
            out.append(path.name)
    return sorted(out)


def test_only_lag_tolerant_readers_use_the_replica():
    """Aggregates over days of data. Nothing that reads its own write, nothing in
    the auth path, nothing a mutation returns."""
    assert _routers_using("get_read_db") == ["analytics.py", "history.py"]


def test_the_replica_routed_routers_never_write():
    """The guard that matters. If someone adds an INSERT to analytics.py it lands
    on a read-only replica — or worse, silently on the primary through a session
    that is never committed."""
    offenders = {}
    for name in _routers_using("get_read_db"):
        src = (ROUTES_DIR / name).read_text(encoding="utf-8")
        # Strip comments/docstrings crudely: only look at lines that execute SQL.
        writes = [ln.strip() for ln in src.splitlines()
                  if any(kw in ln.upper() for kw in ("INSERT INTO", "UPDATE ", "DELETE FROM"))
                  and not ln.strip().startswith("#")]
        if writes:
            offenders[name] = writes
    assert not offenders, f"a replica-routed router must not write: {offenders}"


def test_that_guard_is_not_vacuous():
    """It must actually be inspecting files that exist and contain SQL."""
    routers = _routers_using("get_read_db")
    assert routers, "no router uses get_read_db — the guard above proves nothing"
    src = (ROUTES_DIR / routers[0]).read_text(encoding="utf-8")
    assert "SELECT" in src.upper(), "expected the read-routed router to run queries"


def test_any_test_that_stubs_get_db_must_also_stub_get_read_db():
    """A real footgun, found by this change breaking test_rbac.

    FastAPI keys dependency_overrides on the callable, so stubbing `get_db` leaves
    `get_read_db` bound to a real engine — the route then opens an actual
    connection and the test fails for a reason that has nothing to do with what it
    is testing. Worse in reverse: a stub that silently *works* would be testing the
    wrong session.
    """
    tests_dir = pathlib.Path(__file__).resolve().parent
    offenders = []
    for path in tests_dir.glob("test_*.py"):
        src = path.read_text(encoding="utf-8")
        if "dependency_overrides[get_db]" in src and "dependency_overrides[get_read_db]" not in src:
            # Only matters if the module drives a replica-routed router.
            if any(r.replace(".py", "") in src for r in ("analytics", "history")):
                offenders.append(path.name)
    assert not offenders, (
        f"these tests stub get_db but not get_read_db, and exercise a replica-routed "
        f"router: {offenders}"
    )
