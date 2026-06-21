"""
Tests for server-side store-level scoping (RBAC).
Verifies that store managers, regional managers, and super admins are correctly scoped
and prevented from accessing unauthorized store data.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException

from app.main import app
from app.routes.auth import get_current_user, can_access_store, get_accessible_store_ids
from app.services.database import get_db

# Mock users
MOCK_SUPER_ADMIN = {
    "id": 1,
    "email": "atharva@retaildemo.app",
    "role": "super_admin",
    "status": "active",
    "permissions": {
        "accessible_stores": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "accessible_regions": ["dubai", "abu_dhabi", "northern_emirates"],
        "can_view": True,
    }
}

MOCK_REGIONAL_MANAGER = {
    "id": 2,
    "email": "krishna@retaildemo.app",
    "role": "regional_manager",
    "status": "active",
    "permissions": {
        "accessible_stores": [1, 2, 3],
        "accessible_regions": ["dubai"],
        "can_view": True,
    }
}

MOCK_STORE_MANAGER = {
    "id": 3,
    "email": "yash@retaildemo.app",
    "role": "store_manager",
    "status": "active",
    "permissions": {
        "accessible_stores": [1],
        "accessible_regions": [],
        "can_view": True,
    }
}


@pytest.fixture(autouse=True)
def clean_dependency_overrides():
    """Clean up dependency overrides after each test."""
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def mock_db_session():
    """Mock DB session that returns empty lists/mocks for all queries."""
    db = AsyncMock()
    
    # Mock execute return values
    mock_result = AsyncMock()
    mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    mock_result.fetchall = MagicMock(return_value=[])
    mock_result.fetchone = MagicMock(return_value=None)
    mock_result.scalar = MagicMock(return_value=0)
    mock_result.one = MagicMock(return_value=MagicMock(
        avg_score=4.5, avg_sales=100.0, avg_rating=4.8, avg_attendance=95.0,
        total_transactions=10, record_count=1,
        transactions=10, sales=100.0, avg_transaction=10.0
    ))
    
    db.execute = AsyncMock(return_value=mock_result)
    db.scalar = AsyncMock(return_value=0)
    return db


@pytest.mark.asyncio
async def test_sales_rbac_store_manager(mock_db_session):
    """Store manager (Yash) can only access their store's sales."""
    app.dependency_overrides[get_current_user] = lambda: MOCK_STORE_MANAGER
    app.dependency_overrides[get_db] = lambda: mock_db_session
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Request store 1 (allowed)
        resp1 = await client.get("/api/sales/?store_id=1")
        assert resp1.status_code == 200
        
        # Request store 2 (forbidden)
        resp2 = await client.get("/api/sales/?store_id=2")
        assert resp2.status_code == 403


@pytest.mark.asyncio
async def test_sales_rbac_regional_manager(mock_db_session):
    """Regional manager (Krishna) can access regional stores but not other regions."""
    app.dependency_overrides[get_current_user] = lambda: MOCK_REGIONAL_MANAGER
    app.dependency_overrides[get_db] = lambda: mock_db_session
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Request store 2 (allowed - in Dubai region)
        resp1 = await client.get("/api/sales/?store_id=2")
        assert resp1.status_code == 200
        
        # Request store 4 (forbidden - Abu Dhabi store)
        resp2 = await client.get("/api/sales/?store_id=4")
        assert resp2.status_code == 403


@pytest.mark.asyncio
async def test_sales_rbac_super_admin(mock_db_session):
    """Super admin (Atharva) can access any store."""
    app.dependency_overrides[get_current_user] = lambda: MOCK_SUPER_ADMIN
    app.dependency_overrides[get_db] = lambda: mock_db_session
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Request store 4 (allowed)
        resp1 = await client.get("/api/sales/?store_id=4")
        assert resp1.status_code == 200


@pytest.mark.asyncio
async def test_metrics_rbac(mock_db_session):
    """Metrics endpoint enforces store access permissions."""
    app.dependency_overrides[get_db] = lambda: mock_db_session
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Store Manager requesting store 1 (allowed)
        app.dependency_overrides[get_current_user] = lambda: MOCK_STORE_MANAGER
        resp1 = await client.get("/api/sales/metrics?store_id=1")
        assert resp1.status_code == 200
        
        # Store Manager requesting store 2 (forbidden)
        resp2 = await client.get("/api/sales/metrics?store_id=2")
        assert resp2.status_code == 403


@pytest.mark.asyncio
async def test_predictions_rbac(mock_db_session):
    """Predictions endpoint enforces store access permissions."""
    app.dependency_overrides[get_db] = lambda: mock_db_session
    
    # Mock predictor service to bypass real calculations
    with patch("app.routes.sales.predictor.predict", new_callable=AsyncMock) as mock_predict:
        # When allowed, returning empty predictions raises a 404 (No data found)
        mock_predict.return_value = []
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Store Manager requesting store 1 (allowed -> returns 404 since no mock data)
            app.dependency_overrides[get_current_user] = lambda: MOCK_STORE_MANAGER
            resp1 = await client.get("/api/sales/predictions?store_id=1")
            assert resp1.status_code == 404
            
            # Store Manager requesting store 2 (forbidden -> 403)
            resp2 = await client.get("/api/sales/predictions?store_id=2")
            assert resp2.status_code == 403


@pytest.mark.asyncio
async def test_history_rbac(mock_db_session):
    """History endpoint enforces store access permissions."""
    app.dependency_overrides[get_db] = lambda: mock_db_session
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Store Manager requesting store 1 (allowed)
        app.dependency_overrides[get_current_user] = lambda: MOCK_STORE_MANAGER
        resp1 = await client.get("/api/history?store=1")
        assert resp1.status_code == 200
        
        # Store Manager requesting store 2 (forbidden)
        resp2 = await client.get("/api/history?store=2")
        assert resp2.status_code == 403


@pytest.mark.asyncio
async def test_employees_rbac(mock_db_session):
    """Employees endpoints enforce store access permissions."""
    # Setup dependencies
    app.dependency_overrides[get_db] = lambda: mock_db_session
    
    # Setup mock sessioncontext manager yielding mock_db_session
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_db_session
    
    with patch("app.routes.employees.async_session") as mock_session_maker:
        mock_session_maker.return_value = mock_context
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Store Manager requesting store 1 (allowed)
            app.dependency_overrides[get_current_user] = lambda: MOCK_STORE_MANAGER
            resp1 = await client.get("/api/employees/employees?store_id=1")
            assert resp1.status_code == 200
            
            # Store Manager requesting store 2 (forbidden)
            resp2 = await client.get("/api/employees/employees?store_id=2")
            assert resp2.status_code == 403
