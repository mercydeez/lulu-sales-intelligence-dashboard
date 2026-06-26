"""
AI assistant (Sage) RBAC + safety tests.

Covers the gaps that the legacy in-app chat path had:
  - P0.1 every chat data query is scoped to the caller's accessible stores
  - (P0.2 server-side permission gate / P0.3 session isolation / P0.4 guardrails
     are added alongside their implementation steps.)

These are unit-level: we override get_current_user and patch the chat service so
we assert the *route* hands the right RBAC scope down, without needing a live DB.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from app.main import app
from app.routes.auth import get_current_user

# Mock users (mirror tests/test_rbac.py)
MOCK_SUPER_ADMIN = {
    "id": 1, "email": "atharva@retaildemo.app", "role": "super_admin",
    "status": "active", "tenant_id": 1,
    "permissions": {"accessible_stores": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], "can_use_ai_chat": True},
}
MOCK_REGIONAL_MANAGER = {
    "id": 2, "email": "krishna@retaildemo.app", "role": "regional_manager",
    "status": "active", "tenant_id": 1,
    "permissions": {"accessible_stores": [1, 2, 3], "can_use_ai_chat": True},
}
MOCK_STORE_MANAGER = {
    "id": 3, "email": "yash@retaildemo.app", "role": "store_manager",
    "status": "active", "tenant_id": 1,
    "permissions": {"accessible_stores": [1], "can_use_ai_chat": True},
}


@pytest.fixture(autouse=True)
def clean_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


async def _ask(user, message="show me all stores performance"):
    """POST a non-streaming chat as `user`, capturing the scope passed to the service."""
    app.dependency_overrides[get_current_user] = lambda: user
    with patch("app.routes.ai.get_chat_response", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = "ok"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/ai/chat", json={"message": message, "stream": False})
        return resp, mock_chat


def _allowed_stores_arg(mock_chat):
    """get_chat_response(session_id, message, tenant_id, role, allowed_stores)."""
    args = mock_chat.call_args.args
    return args[4] if len(args) > 4 else mock_chat.call_args.kwargs.get("allowed_stores")


# --- P0.1: store-level scoping -------------------------------------------------

@pytest.mark.asyncio
async def test_store_manager_scope():
    """A store manager's chat is scoped to exactly their store(s)."""
    resp, mock_chat = await _ask(MOCK_STORE_MANAGER)
    assert resp.status_code == 200
    assert _allowed_stores_arg(mock_chat) == [1]


@pytest.mark.asyncio
async def test_regional_manager_scope():
    """A regional manager is scoped to their region's stores."""
    resp, mock_chat = await _ask(MOCK_REGIONAL_MANAGER)
    assert resp.status_code == 200
    assert _allowed_stores_arg(mock_chat) == [1, 2, 3]


@pytest.mark.asyncio
async def test_super_admin_unrestricted():
    """Super admin passes an empty scope (= all stores in the tenant)."""
    resp, mock_chat = await _ask(MOCK_SUPER_ADMIN)
    assert resp.status_code == 200
    assert _allowed_stores_arg(mock_chat) == []


# --- _sale_scope helper --------------------------------------------------------

def test_sale_scope_adds_store_filter_when_restricted():
    from app.services.ai_assistant import _sale_scope
    restricted = str(_sale_scope(1, [1, 2]))
    unrestricted = str(_sale_scope(1, []))
    # Restricted clause references store_id; unrestricted does not.
    assert "store_id" in restricted
    assert "tenant_id" in restricted
    assert "store_id" not in unrestricted
    assert "tenant_id" in unrestricted
