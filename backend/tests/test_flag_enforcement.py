"""
B7 — per-tenant flag ENFORCEMENT (Platform Console).

The customization ENGINE (`customization.resolve_effective`) lands in a parallel
change; until it merges it raises NotImplementedError. Enforcement must treat
ANY engine exception as "no restriction" (fail-open — an infrastructure failure
or an unmerged engine never takes a surface down), while the existing role and
API-key gates stay the fail-closed access floor. These tests pin that boundary,
the 30s advisory TTL cache, and — structurally — that the four flag families are
actually wired into their call sites (a toggle nothing honours is a Potemkin
toggle).
"""
import ast
import inspect
import textwrap

import pytest

from app.services import customization, flag_enforcement


def _code(fn) -> str:
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    node.decorator_list = []
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        node.body = node.body[1:]
    return ast.unparse(node)


@pytest.fixture(autouse=True)
def clean_cache():
    flag_enforcement.invalidate()
    yield
    flag_enforcement.invalidate()


# --------------------------------------------------------------------------
# Fail-open: engine unmerged / infrastructure down → the flag allows.
# --------------------------------------------------------------------------

async def test_unmerged_engine_fails_open(monkeypatch):
    async def _boom(db, tenant_id):
        raise NotImplementedError("customization engine not merged yet")
    monkeypatch.setattr(customization, "resolve_effective", _boom)
    assert await flag_enforcement.flag_allows(1, "assistant.ai_chat") is True
    assert await flag_enforcement.effective_flags(1) is None


async def test_infrastructure_failure_fails_open(monkeypatch):
    async def _boom(db, tenant_id):
        raise RuntimeError("db down")
    monkeypatch.setattr(customization, "resolve_effective", _boom)
    assert await flag_enforcement.flag_allows(1, "integrations.public_api") is True


async def test_none_tenant_returns_default():
    assert await flag_enforcement.flag_allows(None, "assistant.ai_chat") is True
    assert await flag_enforcement.flag_allows(None, "assistant.ai_chat", default=False) is False


async def test_failures_are_never_cached(monkeypatch):
    """A failed resolve must not poison the cache — once the engine answers,
    the very next request sees it (no 30s of stale fail-open)."""
    state = {"broken": True}

    async def _resolve(db, tenant_id):
        if state["broken"]:
            raise NotImplementedError("not merged yet")
        return {"assistant.ai_chat": {"value": False, "source": "override"}}
    monkeypatch.setattr(customization, "resolve_effective", _resolve)

    assert await flag_enforcement.flag_allows(1, "assistant.ai_chat") is True   # fail-open
    state["broken"] = False                                                      # engine "merges"
    assert await flag_enforcement.flag_allows(1, "assistant.ai_chat") is False  # enforced now


# --------------------------------------------------------------------------
# Enforcement: the effective value decides once the engine answers.
# --------------------------------------------------------------------------

async def test_disabled_flag_is_enforced(monkeypatch):
    async def _flags(tenant_id):
        return {"assistant.ai_chat": {"value": False, "source": "override"}}
    monkeypatch.setattr(flag_enforcement, "effective_flags", _flags)
    assert await flag_enforcement.flag_allows(1, "assistant.ai_chat") is False


async def test_enabled_flag_allows(monkeypatch):
    async def _flags(tenant_id):
        return {"assistant.ai_chat": {"value": True, "source": "default"}}
    monkeypatch.setattr(flag_enforcement, "effective_flags", _flags)
    assert await flag_enforcement.flag_allows(1, "assistant.ai_chat") is True


async def test_missing_or_malformed_entry_falls_back_to_default(monkeypatch):
    async def _flags(tenant_id):
        return {"assistant.voice": "not-a-dict"}
    monkeypatch.setattr(flag_enforcement, "effective_flags", _flags)
    assert await flag_enforcement.flag_allows(1, "assistant.voice") is True
    assert await flag_enforcement.flag_allows(1, "modules.reports", default=False) is False


# --------------------------------------------------------------------------
# TTL cache: hot endpoints don't add a DB round-trip per request.
# --------------------------------------------------------------------------

async def test_ttl_cache_resolves_once_and_invalidate_clears(monkeypatch):
    calls = {"n": 0}

    async def _resolve(db, tenant_id):
        calls["n"] += 1
        return {"assistant.ai_chat": {"value": True, "source": "default"}}
    monkeypatch.setattr(customization, "resolve_effective", _resolve)

    assert await flag_enforcement.flag_allows(1, "assistant.ai_chat") is True
    assert await flag_enforcement.flag_allows(1, "assistant.ai_chat") is True
    assert calls["n"] == 1                      # second call within TTL is a cache hit

    flag_enforcement.invalidate(1)
    assert await flag_enforcement.flag_allows(1, "assistant.ai_chat") is True
    assert calls["n"] == 2                      # invalidate() forces a fresh resolve

    flag_enforcement.invalidate()               # global clear works too
    assert await flag_enforcement.flag_allows(1, "assistant.ai_chat") is True
    assert calls["n"] == 3


async def test_cache_is_per_tenant(monkeypatch):
    calls = {"n": 0}

    async def _resolve(db, tenant_id):
        calls["n"] += 1
        return {"assistant.ai_chat": {"value": True, "source": "default"}}
    monkeypatch.setattr(customization, "resolve_effective", _resolve)

    await flag_enforcement.flag_allows(1, "assistant.ai_chat")
    await flag_enforcement.flag_allows(2, "assistant.ai_chat")
    assert calls["n"] == 2                      # one resolve per tenant, not shared


# --------------------------------------------------------------------------
# The chat route actually refuses when the tenant flag is off (behavioral).
# --------------------------------------------------------------------------

async def test_chat_route_refuses_when_tenant_flag_disabled(monkeypatch):
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.routes.auth import get_current_user

    user = {"id": 3, "email": "yash@retaildemo.app", "role": "store_manager",
            "status": "active", "tenant_id": 1,
            "permissions": {"accessible_stores": [1], "can_use_ai_chat": True}}

    async def _flags(tenant_id):
        return {"assistant.ai_chat": {"value": False, "source": "override"}}
    monkeypatch.setattr(flag_enforcement, "effective_flags", _flags)

    app.dependency_overrides[get_current_user] = lambda: user
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/ai/chat", json={"message": "hi", "stream": False})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 403
    assert "disabled for this workspace" in resp.json()["detail"]


# --------------------------------------------------------------------------
# Structural: the four flag families are wired into their call sites.
# --------------------------------------------------------------------------

def test_ai_chat_handlers_check_the_flag():
    from app.routes import ai
    for handler in (ai.chat, ai.chat_stream):
        code = _code(handler)
        assert "flag_allows" in code, handler.__name__
        assert "assistant.ai_chat" in code, handler.__name__


def test_voice_handlers_check_both_flags():
    from app.routes import ai
    for handler in (ai.voice_transcribe, ai.voice_transcribe_file,
                    ai.voice_synthesize, ai.get_available_voices, ai.voice_chat):
        code = _code(handler)
        assert "flag_allows" in code, handler.__name__
        assert "assistant.ai_chat" in code, handler.__name__
        assert "assistant.voice" in code, handler.__name__


def test_rbac_gates_are_untouched():
    """The sync role gates stay the fail-closed floor — no flag/DB call inside
    them (tests/test_ai_rbac.py depends on their exact DB-free behavior)."""
    from app.routes import ai
    for gate in (ai.require_ai_chat, ai.require_voice_chat):
        code = _code(gate)
        assert "flag_allows" not in code
        assert "await" not in code


def test_public_api_dependency_checks_the_kill_switch():
    from app.routes import public_api
    code = _code(public_api.get_api_context)
    assert "flag_allows" in code
    assert "integrations.public_api" in code
    # Refuse BEFORE metering: the kill-switch must appear before enforce_quota.
    assert code.index("integrations.public_api") < code.index("enforce_quota")


def test_experience_handler_overlays_flags_and_never_widens():
    from app.routes import experience
    assert "effective_flags" in _code(experience.get_experience)
    code = _code(experience._apply_customizations)
    cap_lines = [ln for ln in code.splitlines()
                 if "caps[" in ln and "=" in ln and "caps.get(" in ln]
    assert len(cap_lines) >= 2, "capability overlay lines missing"
    for ln in cap_lines:
        assert " and " in ln, ln     # narrow-only: role hint AND flag
        assert " or " not in ln, ln  # never widen


def test_module_nav_mapping_uses_only_catalog_module_keys():
    from app.routes.experience import _MODULE_NAV_HREFS
    from app.services.customization import FLAG_CATALOG
    for key in _MODULE_NAV_HREFS:
        assert key in FLAG_CATALOG, key
        assert FLAG_CATALOG[key]["category"] == "modules", key


# --------------------------------------------------------------------------
# Experience overlay behavior (pure — drives _apply_customizations directly).
# --------------------------------------------------------------------------

def test_overlay_strips_disabled_module_nav_and_narrows_caps():
    from app.routes.experience import _apply_customizations
    from app.services.role_experience import resolve_config

    cfg = resolve_config("procurement_manager")  # nav has /procurement AND /inventory
    _apply_customizations(cfg, {
        "modules.procurement": {"value": False, "source": "override"},
        "assistant.voice": {"value": False, "source": "override"},
        "assistant.mode": {"value": "hidden", "source": "override"},
    })
    hrefs = [n["href"] for n in cfg["nav"]]
    assert "/procurement" not in hrefs          # disabled module stripped
    assert "/inventory" in hrefs                # enabled module stays
    assert "/today" in hrefs                    # unmapped entries are never stripped
    assert cfg["capabilities"]["voice"] is False
    assert cfg["capabilities"]["ai_chat"] is True
    assert cfg["assistant_mode"] == "hidden"    # explicit override wins


def test_overlay_cannot_widen_capabilities():
    cfg = {"nav": None, "capabilities": {"ai_chat": False, "voice": False},
           "assistant_mode": "panel"}
    from app.routes.experience import _apply_customizations
    _apply_customizations(cfg, {
        "assistant.ai_chat": {"value": True, "source": "override"},
        "assistant.voice": {"value": True, "source": "override"},
    })
    assert cfg["capabilities"] == {"ai_chat": False, "voice": False}


def test_overlay_leaves_full_sidebar_and_non_override_mode_alone():
    from app.routes.experience import _apply_customizations
    cfg = {"nav": None, "capabilities": {"ai_chat": True, "voice": True},
           "assistant_mode": "copilot"}
    _apply_customizations(cfg, {
        "modules.reports": {"value": False, "source": "override"},
        "assistant.mode": {"value": "panel", "source": "default"},  # not an override
    })
    assert cfg["nav"] is None                   # full built-in sidebar untouched
    assert cfg["assistant_mode"] == "copilot"   # default source never overrides
