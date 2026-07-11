"""Regression tests for two Critical audit findings on tenant binding.

C1 — Cookie-authenticated requests bound the Postgres RLS tenant GUC to tenant 1.
     `resolve_request_tenant` only read the Authorization: Bearer header / API key /
     SSE ticket, never the httpOnly `access_token` cookie — which is the browser's
     ONLY transport since E0-5. So every browser request fell through to the
     default tenant 1 and the RLS backstop bound to the wrong tenant.

C2 — Refreshing an access token dropped tenant_id. `refresh_access_token` rebuilt
     the user from a SELECT that omitted `tenant_id`, so the rotated access token
     carried tenant_id=None (RLS fell back to tenant 1) AND a super_admin's
     permissions were computed unscoped (cross-tenant store access).

These are DB-free: C1 only decodes a JWT; C2 mocks the user lookup so the assertion
is purely "does the refreshed token keep the tenant claim + scope permissions".
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.auth_service import (
    AuthService, create_access_token, create_refresh_token, decode_token,
)
from app.services.database import resolve_request_tenant, tenant_context


def _req(cookies=None, headers=None, query=None):
    """Minimal Request stand-in for resolve_request_tenant (dict-backed .get)."""
    r = MagicMock()
    r.headers = headers or {}
    r.cookies = cookies or {}
    r.query_params = query or {}
    return r


def _access(tenant_id=7, user_id=1):
    return create_access_token({
        "user_id": user_id, "email": "u@t.example", "role": "analyst",
        "tenant_id": tenant_id,
    })


# ---------------------------------------------------------------------------
# C1 — the RLS tenant must be resolved from every access-token transport.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_c1_cookie_binds_rls_to_real_tenant():
    """REGRESSION: an httpOnly access_token cookie must bind RLS to its tenant,
    not the tenant-1 default. This is the browser path (cookie-only since E0-5)."""
    resolved = await resolve_request_tenant(_req(cookies={"access_token": _access(tenant_id=7)}))
    assert resolved == 7
    assert tenant_context.get() == 7


@pytest.mark.asyncio
async def test_c1_bearer_still_binds_tenant():
    """The Authorization: Bearer path (API/legacy clients) must be unchanged."""
    resolved = await resolve_request_tenant(
        _req(headers={"authorization": f"Bearer {_access(tenant_id=4)}"})
    )
    assert resolved == 4


@pytest.mark.asyncio
async def test_c1_sse_ticket_still_binds_tenant():
    """The SSE ?ticket= path must be unchanged."""
    resolved = await resolve_request_tenant(_req(query={"ticket": _access(tenant_id=9)}))
    assert resolved == 9


@pytest.mark.asyncio
async def test_c1_no_credentials_fails_safe_to_tenant_1():
    """No token of any kind → fail safe to tenant 1 (auth dependency still 401s)."""
    resolved = await resolve_request_tenant(_req())
    assert resolved == 1


@pytest.mark.asyncio
async def test_c1_bearer_precedence_over_cookie():
    """If both are present, the explicit Bearer header wins (documented order)."""
    resolved = await resolve_request_tenant(_req(
        headers={"authorization": f"Bearer {_access(tenant_id=2)}"},
        cookies={"access_token": _access(tenant_id=8)},
    ))
    assert resolved == 2


# ---------------------------------------------------------------------------
# C2 — refreshing a token must preserve tenant_id (claim + permission scope).
# ---------------------------------------------------------------------------

def _fake_session_cm(user_row):
    """async-context-manager returning a session whose execute() yields user_row."""
    result = MagicMock()
    result.fetchone.return_value = user_row
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.mark.asyncio
async def test_c2_refresh_preserves_tenant_id(fake_redis):
    """REGRESSION: the rotated access token must still carry tenant_id, and the
    permission lookup must be scoped to that tenant."""
    refresh = create_refresh_token({
        "user_id": 1, "email": "owner@t7.example", "role": "super_admin",
        "tenant_id": 7,
    })

    user_row = MagicMock()
    user_row._mapping = {
        "id": 1, "email": "owner@t7.example", "first_name": "O", "last_name": "W",
        "role": "super_admin", "status": "active", "job_title": None,
        "department": None, "tenant_id": 7,
    }

    perms = AsyncMock(return_value={"accessible_stores": [], "accessible_regions": []})
    with patch("app.services.auth_service.async_session", return_value=_fake_session_cm(user_row)), \
         patch.object(AuthService, "_get_user_permissions", perms):
        tokens = await AuthService.refresh_access_token(refresh)

    assert tokens is not None, "refresh should succeed for an active user"
    # The rotated ACCESS token keeps the tenant claim (drives the RLS GUC).
    td = decode_token(tokens.access_token)
    assert td is not None and td.tenant_id == 7

    # Permissions were scoped to the tenant (the super_admin cross-tenant leak fix):
    # _get_user_permissions(session, user_id, role, tenant_id) — 4th positional arg.
    assert perms.await_args.args[3] == 7


@pytest.mark.asyncio
async def test_c2_refreshed_user_row_includes_tenant_id(fake_redis):
    """The rebuilt user object exposes tenant_id (returned to the client on refresh)."""
    refresh = create_refresh_token({
        "user_id": 2, "email": "a@t3.example", "role": "analyst", "tenant_id": 3,
    })
    user_row = MagicMock()
    user_row._mapping = {
        "id": 2, "email": "a@t3.example", "first_name": "A", "last_name": "N",
        "role": "analyst", "status": "active", "job_title": None,
        "department": None, "tenant_id": 3,
    }
    perms = AsyncMock(return_value={"accessible_stores": [1], "accessible_regions": []})
    with patch("app.services.auth_service.async_session", return_value=_fake_session_cm(user_row)), \
         patch.object(AuthService, "_get_user_permissions", perms):
        tokens = await AuthService.refresh_access_token(refresh)

    assert tokens is not None
    assert tokens.user.get("tenant_id") == 3


# ---------------------------------------------------------------------------
# Hardening (discovered during the High review) — the SSE stream ticket is an
# access-typed token, so it must carry tenant_id like every other access token;
# resolve_request_tenant reads it from a ?ticket= to bind the RLS GUC.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_ticket_carries_tenant_id():
    from app.routes.auth import issue_stream_ticket
    res = await issue_stream_ticket(user={
        "id": 1, "email": "u@t.example", "role": "analyst", "tenant_id": 5,
    })
    td = decode_token(res["ticket"])
    assert td is not None and td.tenant_id == 5
    # And it round-trips through the RLS tenant resolver via the ticket transport.
    assert await resolve_request_tenant(_req(query={"ticket": res["ticket"]})) == 5
