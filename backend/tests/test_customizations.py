"""Platform Console B1 — the customization ENGINE + its routes.

The engine layers catalog default -> plan floor -> tenant override and NEVER lets
an override bypass the plan (the plan is what was sold; the override is bespoke
ON TOP of a qualifying plan). Storage merges into ONE JSONB namespace
(tenants.settings->'customizations') and must never clobber the whole column.

These tests pin: the dependency-only gating of the routes (no ad-hoc role
checks), the merge-not-clobber SQL, the plan-floor enforcement inside
resolve_effective, the pure validation layer, and — behaviorally, with a canned
fake db — the override/plan/default source resolution.
"""
import ast
import inspect
import json
import textwrap

import pytest

from app.services import customization as cz
import app.routes.customizations as cz_routes


def _code(fn) -> str:
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    node.decorator_list = []
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        node.body = node.body[1:]
    return ast.unparse(node)


class _ExplodingDB:
    """Any DB touch is a test failure — pins that pure validation runs first."""

    async def execute(self, *a, **k):
        raise AssertionError("the DB must not be touched on this path")

    async def commit(self):
        raise AssertionError("the DB must not be touched on this path")


class _Result:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row

    def scalar(self):
        return self._row[0] if self._row else None


class _FakeDB:
    """Canned-row async db: SELECTs return `row`, writes are recorded."""

    def __init__(self, row=None):
        self._row = row
        self.updates = []

    async def execute(self, stmt, params=None):
        if str(stmt).strip().lower().startswith("select"):
            return _Result(self._row)
        self.updates.append((str(stmt), params))
        return _Result()

    async def commit(self):
        pass


# --------------------------------------------------------------------------
# Routes: gated by the platform-developer dependency, owner session only.
# --------------------------------------------------------------------------

def test_every_route_is_gated_by_the_dependency_not_role_checks():
    src = inspect.getsource(cz_routes)
    assert "require_platform_developer" in src
    endpoints = [r.endpoint for r in cz_routes.router.routes]
    assert len(endpoints) >= 4
    for ep in endpoints:
        code = _code(ep)
        # The gate is the dependency in the signature...
        assert "require_platform_developer" in code, ep.__name__
        # ...never an ad-hoc role string check (super_admin is a TENANT role).
        assert "role" not in code, ep.__name__


def test_routes_use_the_owner_session_not_rls_bound_get_db():
    """Cross-tenant control plane: get_db binds the caller's tenant GUC and RLS
    would hide every other tenant's rows. (The module docstring is stripped — it
    is allowed to EXPLAIN why get_db is banned; the code may not use it.)"""
    tree = ast.parse(inspect.getsource(cz_routes))
    body = tree.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    code = "\n".join(ast.unparse(n) for n in body)
    assert "async_session" in code
    assert "get_db" not in code


def test_catalog_route_is_declared_before_the_dynamic_tenant_route():
    paths = [r.path for r in cz_routes.router.routes]
    assert paths.index("/dev/customizations/catalog") < paths.index("/dev/customizations/{tenant_id}")


def test_router_is_registered_under_api_admin():
    from app.routes.registry import ROUTERS
    entries = [(prefix, tags) for router, prefix, tags in ROUTERS if router is cz_routes.router]
    assert entries == [("/api/admin", ["Customizations"])]


# --------------------------------------------------------------------------
# Storage: merge into the namespace, never clobber the settings column.
# --------------------------------------------------------------------------

def test_set_override_merges_never_clobbers_the_settings_column():
    code = _code(cz.set_override)
    assert "jsonb_set" in code
    assert "SET settings = :" not in code  # full-column assignment would clobber
    assert "COALESCE(settings" in code     # null-safe on both column and namespace


def test_clear_override_removes_one_key_defensively():
    code = _code(cz.clear_override)
    assert "jsonb_set" in code
    assert "- CAST(:key AS text)" in code
    assert "SET settings = :" not in code
    assert "COALESCE(settings" in code


def test_resolve_effective_enforces_the_plan_floor():
    code = _code(cz.resolve_effective)
    assert "plan_allows" in code
    assert "validate_value" in code  # invalid stored values are ignored, not served


# --------------------------------------------------------------------------
# The pure layer, exercised through the real catalog.
# --------------------------------------------------------------------------

def test_every_catalog_default_is_itself_valid():
    for key, entry in cz.FLAG_CATALOG.items():
        ok, err = cz.validate_value(key, entry["default"])
        assert ok, f"{key}: {err}"


def test_enterprise_reaches_every_plan_floor():
    for key in cz.FLAG_CATALOG:
        assert cz.plan_allows(key, "enterprise"), key


def test_int_bounds_are_enforced_through_the_catalog():
    ok, err = cz.validate_value("limits.api_rate_multiplier", 11)
    assert not ok and "<=" in err
    ok, _ = cz.validate_value("limits.api_rate_multiplier", True)  # bool is not an int
    assert not ok
    ok, _ = cz.validate_value("limits.api_rate_multiplier", 10)
    assert ok


def test_an_unknown_plan_fails_closed():
    assert cz.plan_allows("assistant.voice", "bespoke-unknown-plan") is False


# --------------------------------------------------------------------------
# Behavioral: override / plan / default resolution with a canned db.
# --------------------------------------------------------------------------

OVERRIDES = {
    "assistant.voice": True,               # valid value, but plan_min = growth
    "assistant.mode": "copilot",           # valid, no plan floor
    "interface.compact_tables": "dense",   # invalid type — must be ignored
}


@pytest.mark.asyncio
async def test_resolve_layers_default_plan_and_override_sources():
    eff = await cz.resolve_effective(_FakeDB(row=("free", dict(OVERRIDES))), 7)
    assert set(eff) == set(cz.FLAG_CATALOG)  # every catalog key answered
    # Plan-refused override: catalog default served, source is honest about why.
    assert eff["assistant.voice"] == {"value": False, "source": "plan"}
    assert eff["assistant.mode"] == {"value": "copilot", "source": "override"}
    # Invalid stored value: treated as absent.
    assert eff["interface.compact_tables"] == {"value": False, "source": "default"}
    assert eff["modules.forecasting"] == {"value": True, "source": "default"}


@pytest.mark.asyncio
async def test_a_qualifying_plan_unlocks_the_same_override():
    eff = await cz.resolve_effective(_FakeDB(row=("growth", dict(OVERRIDES))), 7)
    assert eff["assistant.voice"] == {"value": True, "source": "override"}


@pytest.mark.asyncio
async def test_missing_tenant_resolves_to_pure_defaults():
    eff = await cz.resolve_effective(_FakeDB(row=None), 999)
    assert all(v["source"] == "default" for v in eff.values())


@pytest.mark.asyncio
async def test_resolution_survives_a_string_typed_jsonb_payload():
    """Defensive: a driver without the jsonb codec hands back text."""
    eff = await cz.resolve_effective(_FakeDB(row=("growth", json.dumps({"assistant.mode": "hidden"}))), 7)
    assert eff["assistant.mode"] == {"value": "hidden", "source": "override"}


@pytest.mark.asyncio
async def test_get_overrides_is_empty_on_null_or_garbage():
    assert await cz.get_overrides(_FakeDB(row=None), 1) == {}
    assert await cz.get_overrides(_FakeDB(row=(None,)), 1) == {}
    assert await cz.get_overrides(_FakeDB(row=("not json at all",)), 1) == {}
    assert await cz.get_overrides(_FakeDB(row=({"assistant.mode": "hidden"},)), 1) == {"assistant.mode": "hidden"}


@pytest.mark.asyncio
async def test_flag_value_returns_the_effective_value_and_rejects_unknown_keys():
    assert await cz.flag_value(_FakeDB(row=("growth", {"assistant.mode": "hidden"})), 7, "assistant.mode") == "hidden"
    with pytest.raises(KeyError):
        await cz.flag_value(_ExplodingDB(), 7, "nope.nope")


# --------------------------------------------------------------------------
# Writes: validate first (no DB touch on refusal), audit, merge SQL.
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_override_validates_before_touching_the_db():
    with pytest.raises(ValueError):  # bad enum value
        await cz.set_override(_ExplodingDB(), 1, "assistant.mode", "sidebar", actor="dev@x")
    with pytest.raises(ValueError):  # unknown key
        await cz.set_override(_ExplodingDB(), 1, "nope.nope", True, actor="dev@x")


@pytest.mark.asyncio
async def test_clear_override_rejects_unknown_keys_before_the_db():
    with pytest.raises(ValueError):
        await cz.clear_override(_ExplodingDB(), 1, "nope.nope", actor="dev@x")


@pytest.mark.asyncio
async def test_set_override_refuses_a_plan_below_the_floor():
    db = _FakeDB(row=("free",))
    with pytest.raises(ValueError) as exc:
        await cz.set_override(db, 1, "assistant.voice", True, actor="dev@x")
    assert "growth" in str(exc.value)  # the human message names the required plan
    assert db.updates == []            # nothing was written


@pytest.mark.asyncio
async def test_set_override_writes_merge_sql_and_audits(monkeypatch):
    events = []

    async def _capture(event_type, *a, **kw):
        events.append((event_type, kw))

    monkeypatch.setattr("app.services.security_events.record_event", _capture)
    db = _FakeDB(row=("growth",))
    entry = await cz.set_override(db, 5, "assistant.voice", True, actor="dev@retaildemo.app")
    assert entry == {"value": True, "source": "override"}
    assert len(db.updates) == 1
    sql, params = db.updates[0]
    assert "jsonb_set" in sql and "SET settings = :" not in sql
    assert params["key"] == "assistant.voice"
    assert params["val"] == "true"  # JSON-encoded, cast to jsonb inside the SQL
    assert events and events[0][0] == "customization_changed"
    assert events[0][1]["tenant_id"] == 5
    assert events[0][1]["actor_email"] == "dev@retaildemo.app"


@pytest.mark.asyncio
async def test_clear_override_writes_and_audits(monkeypatch):
    events = []

    async def _capture(event_type, *a, **kw):
        events.append((event_type, kw))

    monkeypatch.setattr("app.services.security_events.record_event", _capture)
    db = _FakeDB(row=("growth",))
    assert await cz.clear_override(db, 5, "assistant.voice", actor="dev@x") is None
    assert len(db.updates) == 1
    sql, params = db.updates[0]
    assert "jsonb_set" in sql and "- CAST(:key AS text)" in sql
    assert params["key"] == "assistant.voice"
    assert events and events[0][0] == "customization_cleared"
