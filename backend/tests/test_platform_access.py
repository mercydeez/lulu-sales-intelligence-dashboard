"""Platform Console foundation — the platform-operator boundary.

`super_admin` is a TENANT role (every self-signup owner gets it), so it can never
gate cross-tenant surfaces by itself. These tests defend the boundary that can:

  usable = users.is_platform_developer AND (allowlist empty OR email in allowlist)

fail-closed on both sides, and NEVER implied by role.
"""
import ast
import inspect
import pathlib
import textwrap

import pytest

from app.services import platform_access as pa
from app.services import customization as cz


def _find_migration(name: str) -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for base in here.parents:
        cand = base / "database" / "migrations" / name
        if cand.is_file():
            return cand
    return here.parents[2] / "database" / "migrations" / name


MIGRATION = _find_migration("072_krishna_platform_developer.sql")


def _code(fn) -> str:
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    node.decorator_list = []
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        node.body = node.body[1:]
    return ast.unparse(node)


# --------------------------------------------------------------------------
# The pure check.
# --------------------------------------------------------------------------

def test_flag_alone_grants_when_no_allowlist(monkeypatch):
    monkeypatch.setenv("PLATFORM_DEVELOPER_EMAILS", "")
    from app.config import get_settings
    get_settings.cache_clear()
    assert pa.is_platform_developer({"is_platform_developer": True, "email": "krishna@retaildemo.app"}) is True
    get_settings.cache_clear()


def test_super_admin_without_flag_is_refused():
    """The load-bearing property: role never implies platform access."""
    assert pa.is_platform_developer({"role": "super_admin", "email": "owner@customer.com"}) is False
    assert pa.is_platform_developer({"role": "super_admin", "is_platform_developer": False}) is False


def test_allowlist_is_an_AND_gate(monkeypatch):
    monkeypatch.setenv("PLATFORM_DEVELOPER_EMAILS", "krishna@retaildemo.app, atharva@retaildemo.app")
    from app.config import get_settings
    get_settings.cache_clear()
    try:
        # flag + on-list -> allowed
        assert pa.is_platform_developer({"is_platform_developer": True, "email": "Krishna@RetailDemo.app"}) is True
        # flag + off-list -> refused (a tampered DB row alone can't mint access)
        assert pa.is_platform_developer({"is_platform_developer": True, "email": "evil@x.com"}) is False
        # on-list without the flag -> refused (allowlist alone never grants)
        assert pa.is_platform_developer({"is_platform_developer": False, "email": "krishna@retaildemo.app"}) is False
    finally:
        monkeypatch.delenv("PLATFORM_DEVELOPER_EMAILS", raising=False)
        get_settings.cache_clear()


def test_empty_or_missing_user_is_refused():
    assert pa.is_platform_developer({}) is False
    assert pa.is_platform_developer(None) is False


@pytest.mark.asyncio
async def test_dependency_403s_non_developers():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await pa.require_platform_developer({"role": "super_admin", "email": "owner@customer.com"})
    assert exc.value.status_code == 403


def test_refusal_never_depends_on_the_audit_write():
    """record_event is best-effort inside the deny path — a broken event pipeline
    must not turn a refusal into a crash (or worse, a pass)."""
    code = _code(pa.require_platform_developer)
    assert "record_event" in code
    assert "except Exception" in code
    # The 403 raise is OUTSIDE the try (after it), so it survives an audit failure.
    assert code.rindex("raise HTTPException") > code.rindex("except Exception")


# --------------------------------------------------------------------------
# Migration guards.
# --------------------------------------------------------------------------

def test_migration_adds_flag_and_seeds_only_the_three_devs():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    ddl = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    assert "add column if not exists is_platform_developer boolean not null default false" in ddl
    for dev in ("atharva@retaildemo.app", "krishna@retaildemo.app", "yash@retaildemo.app"):
        assert dev in ddl
    # It must not blanket-grant by role.
    assert "role = 'super_admin'" not in ddl and "role='super_admin'" not in ddl


def test_user_dict_carries_the_flag():
    """Both user-dict builders include is_platform_developer, so the dependency and
    the frontend read the same fact."""
    import app.services.auth_service as asvc
    src = inspect.getsource(asvc)
    assert src.count("is_platform_developer") >= 3  # login SELECT + login dict + get_user_by_id


# --------------------------------------------------------------------------
# Customization catalog contract (pinned interface for the console units).
# --------------------------------------------------------------------------

def test_catalog_entries_are_well_formed():
    for key, entry in cz.FLAG_CATALOG.items():
        assert entry["category"] in ("modules", "assistant", "interface", "integrations", "limits"), key
        assert entry["type"] in ("bool", "enum", "int"), key
        assert "enforced_by" in entry and entry["enforced_by"], key
        if entry["type"] == "enum":
            assert entry["default"] in entry["options"], key
        if entry.get("plan_min"):
            assert entry["plan_min"] in cz.PLAN_ORDER, key


def test_validate_value_enforces_types():
    ok, _ = cz.validate_value("assistant.ai_chat", True)
    assert ok
    ok, err = cz.validate_value("assistant.ai_chat", "yes")
    assert not ok and "boolean" in err
    ok, err = cz.validate_value("assistant.mode", "sidebar")
    assert not ok and "one of" in err
    ok, err = cz.validate_value("limits.export_rows", 10)
    assert not ok and ">=" in err
    ok, err = cz.validate_value("nope.nope", 1)
    assert not ok and "Unknown" in err


def test_plan_gating_orders_plans():
    assert cz.plan_allows("assistant.voice", "growth") is True
    assert cz.plan_allows("assistant.voice", "free") is False
    assert cz.plan_allows("assistant.ai_chat", "free") is True  # no plan_min
