"""Platform Console — Ops & Readiness panel (B4).

Pins the honesty contract of /api/admin/dev/ops/*:
  * every endpoint is behind require_platform_developer (developers-only surface);
  * the security section exposes COUNTS of validate_security() warnings, never
    the strings (config.py's RS256 branch interpolates exception text into them,
    which can carry filesystem paths/DSNs);
  * one broken subsystem degrades to {"error": "<class name>"} — class name only,
    never exception text — instead of 500ing the whole panel;
  * destructive actions call record_event with the acting developer.
"""
import ast
import asyncio
import inspect
import textwrap

import pytest
from pydantic import ValidationError

from app.routes import platform_ops


def _code(fn) -> str:
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    node.decorator_list = []
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        node.body = node.body[1:]
    return ast.unparse(node)


def _parents(tree: ast.AST) -> dict:
    out = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            out[child] = node
    return out


# --------------------------------------------------------------------------
# Access boundary: platform developers only, on every endpoint.
# --------------------------------------------------------------------------

def test_every_endpoint_requires_a_platform_developer():
    for fn in (platform_ops.ops_status, platform_ops.demo_reset, platform_ops.cache_flush):
        src = _code(fn)
        assert "Depends(require_platform_developer)" in src, (
            f"{fn.__name__} is not gated by require_platform_developer"
        )


def test_registered_under_api_admin():
    from app.routes.registry import ROUTERS
    specs = [(router, prefix) for (router, prefix, _tags) in ROUTERS]
    assert (platform_ops.router, "/api/admin") in specs


# --------------------------------------------------------------------------
# The security section: counts, never the warning strings.
# --------------------------------------------------------------------------

def test_security_section_counts_the_warnings_and_never_returns_them():
    src = _code(platform_ops.ops_status)
    # It really consults the live validator...
    assert "validate_security()" in src
    # ...and exposes only counts derived from it.
    assert "'warnings': len(w)" in src
    assert "startswith('critical')" in src
    # No passthrough of the raw list.
    assert "'warnings': w" not in src


def test_the_warning_strings_are_only_ever_consumed_by_counting():
    """Every Load of the validate_security() result must be a len() argument or
    a comprehension iterable (the startswith('critical') count) — the strings
    themselves must never escape into the response."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(platform_ops.ops_status)))
    parents = _parents(tree)

    # Find the variable(s) assigned from ...validate_security().
    warn_vars = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "validate_security"
        ):
            warn_vars.update(t.id for t in node.targets if isinstance(t, ast.Name))
    assert warn_vars, "the status handler must capture the validate_security() result"

    loads = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Name) and n.id in warn_vars and isinstance(n.ctx, ast.Load)
    ]
    assert loads, "the validate_security() result must actually be consumed"
    for n in loads:
        parent = parents[n]
        counted = (
            isinstance(parent, ast.Call)
            and isinstance(parent.func, ast.Name)
            and parent.func.id == "len"
        ) or isinstance(parent, ast.comprehension)
        assert counted, (
            f"warning strings escape counting via: {ast.unparse(parent)}"
        )


# --------------------------------------------------------------------------
# Section isolation: one broken subsystem never 500s the panel — and its
# error is a class name only, never exception text.
# --------------------------------------------------------------------------

def test_a_broken_section_reports_the_class_name_never_the_text():
    async def boom():
        raise RuntimeError("postgresql://user:s3cret@10.0.0.5/salesdb")

    out = asyncio.run(platform_ops._section(boom))
    assert out == {"error": "RuntimeError"}
    assert "s3cret" not in str(out)


def test_a_healthy_section_passes_through_sync_and_async():
    assert asyncio.run(platform_ops._section(lambda: {"ok": True})) == {"ok": True}

    async def probe():
        return 42

    assert asyncio.run(platform_ops._section(probe)) == 42


def test_the_panel_survives_missing_infrastructure():
    """With no live Postgres/Redis (the testing env), the aggregate must still
    return every section — the config-only ones populated, the infra ones
    degraded honestly (False / missing / error-class), never an exception."""
    out = asyncio.run(platform_ops.ops_status(user={"id": 1, "email": "dev@example.com"}))
    assert set(out) == {
        "payments", "pos", "einvoicing", "quotas", "security",
        "environment", "demo_mode", "worker", "db", "redis",
    }
    # Config-only sections work without infrastructure — a flag, never config text.
    assert set(out["quotas"]) == {"enforcement_on"}
    assert isinstance(out["quotas"]["enforcement_on"], bool)
    # environment + demo_mode are FLAT top-level fields (the console UI reads them
    # as a bare string / bool), not a nested section.
    assert out["environment"] == "testing"
    assert isinstance(out["demo_mode"], bool)
    sec = out["security"]
    assert set(sec) == {"warnings", "critical"}
    assert isinstance(sec["warnings"], int) and isinstance(sec["critical"], int)
    # Per-provider status comes from the real status functions.
    assert out["payments"]["mock"]["implemented"] is True
    assert out["einvoicing"]["mock"] == {"implemented": True, "available": True}
    assert out["einvoicing"]["uae_fta"]["implemented"] is False
    # Infra sections degrade to booleans/parsed-heartbeat shapes, never raise.
    # (bool, not an error dict — on a box with a live local Redis this may be
    # True; in the container verify run both are False.)
    assert isinstance(out["db"], bool)
    assert isinstance(out["redis"], bool)
    assert out["worker"]["diagnostics"]["status"] in ("missing", "unknown", "stale", "ok")
    assert out["worker"]["singletons"]["status"] in ("missing", "unknown", "stale", "ok")


# --------------------------------------------------------------------------
# Guarded ops actions.
# --------------------------------------------------------------------------

def test_cache_flush_scope_refuses_junk():
    with pytest.raises(ValidationError):
        platform_ops.CacheFlushRequest(scope="everything")
    with pytest.raises(ValidationError):
        platform_ops.CacheFlushRequest(scope="inventory_*")  # no patterns, no wildcards
    for ok in ("inventory", "promotions", "alerts", "all"):
        assert platform_ops.CacheFlushRequest(scope=ok).scope == ok


def test_cache_flush_calls_the_matching_invalidators_and_audits():
    src = _code(platform_ops.cache_flush)
    assert "invalidate_{scope}_cache" in src
    assert "record_event(" in src
    assert "'ops_cache_flush'" in src
    assert "severity='medium'" in src


def test_demo_reset_calls_the_selfguarded_service_and_audits_high():
    src = _code(platform_ops.demo_reset)
    assert "reset_demo_tenant(" in src
    assert "record_event(" in src
    assert "'ops_demo_reset'" in src
    assert "severity='high'" in src
    # A refused reset (safety check tripped) is audited too, not swallowed.
    assert "DemoResetRefused" in src
