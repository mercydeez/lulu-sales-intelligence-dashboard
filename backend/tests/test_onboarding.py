"""
Self-serve onboarding (go-to-market): signup → tenant + owner (+ sample data),
invite teammates, onboarding checklist.

Unit-covers the password/slug guards that run before any DB access and confirms
the routes are registered with the right auth posture. Full provisioning against
a live DB is exercised by the integration suite.
"""
import pytest
from fastapi.testclient import TestClient

from app.services import tenant_provisioning as prov
from tests.conftest import registered_paths


def test_slugify_is_url_safe():
    assert prov._slugify("Açme  Foods & Co!!") == "a-me-foods-co"
    assert prov._slugify("") == "tenant"
    assert prov._slugify("!!!") == "tenant"


@pytest.mark.asyncio
async def test_signup_rejects_weak_password_before_db():
    # validate_password_strength runs before any DB call, so this needs no DB.
    user_id, error = await prov.create_tenant_with_owner(
        company="Acme", email="x@acme.io", password="weak",
        first_name="A", last_name="B", seed_demo=False,
    )
    assert user_id is None
    assert error and "12 characters" in error


@pytest.mark.asyncio
async def test_invite_rejects_bad_role_before_db():
    invite, error = await prov.invite_user(
        tenant_id=1, email="t@acme.io", first_name="T", last_name="M", role="emperor",
    )
    assert invite is None
    assert error and "Invalid role" in error


def test_onboarding_routes_registered():
    from app.main import app
    paths = registered_paths(app)
    assert "/api/auth/signup" in paths
    assert "/api/auth/invite" in paths
    assert "/api/auth/onboarding" in paths


def test_signup_validation_rejects_missing_fields():
    from app.main import app
    client = TestClient(app)
    resp = client.post("/api/auth/signup", json={"email": "a@b.com"})
    assert resp.status_code == 422  # pydantic validation, no DB


def test_signup_weak_password_returns_400():
    from app.main import app
    client = TestClient(app)
    resp = client.post("/api/auth/signup", json={
        "company_name": "Acme", "email": "owner@acme.io", "password": "short",
        "first_name": "A", "last_name": "B", "seed_sample_data": False,
    })
    assert resp.status_code == 400


def test_invite_and_onboarding_require_auth():
    from app.main import app
    client = TestClient(app)
    assert client.post("/api/auth/invite", json={
        "email": "t@b.com", "first_name": "T", "last_name": "M"}).status_code in (401, 403)
    assert client.get("/api/auth/onboarding").status_code == 401
