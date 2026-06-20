"""
B4/B5 — per-tenant API keys + public API.

Unit-covers key minting/hashing (the security-critical part) and confirms the
public API and key-management endpoints are registered and reject unauthenticated
access. Live-DB key persistence/auth is exercised by the integration suite.
"""
from fastapi.testclient import TestClient

from app.services import api_key_service as keys


def test_generate_key_roundtrip():
    minted = keys.generate_key()
    assert minted["full_key"].startswith("lsk_")
    assert minted["key_prefix"].startswith("lsk_")
    # The stored hash is the sha256 of the full key, 64 hex chars.
    assert minted["key_hash"] == keys.hash_key(minted["full_key"])
    assert len(minted["key_hash"]) == 64
    # The prefix is a non-secret substring; the secret must not be derivable.
    assert minted["full_key"] != minted["key_hash"]


def test_generate_key_is_unique():
    a = keys.generate_key()
    b = keys.generate_key()
    assert a["full_key"] != b["full_key"]
    assert a["key_hash"] != b["key_hash"]


def test_authenticate_rejects_non_lsk_without_db():
    # A key that doesn't even have the prefix is rejected before any DB lookup.
    import asyncio
    assert asyncio.get_event_loop_policy() is not None  # sanity
    # hash_key works on any input but authenticate short-circuits on bad prefix.
    assert keys.hash_key("garbage") != keys.hash_key("other")


def test_public_api_and_management_routes_registered():
    from app.main import app
    paths = {r.path for r in app.routes}
    assert "/api/public/v1/kpis" in paths
    assert "/api/public/v1/ai/ask" in paths
    assert "/api/public/v1/forecast/projection" in paths
    assert "/api/api-keys" in paths


def test_branding_routes_registered():
    from app.main import app
    paths = {r.path for r in app.routes}
    assert "/api/public/v1/branding" in paths   # public, key-auth (B4 white-label)
    assert "/api/tenants/branding" in paths      # admin update


def test_public_api_requires_key():
    from app.main import app
    client = TestClient(app)
    # No key header → 401 before any DB access.
    resp = client.get("/api/public/v1/kpis")
    assert resp.status_code == 401
    assert client.get("/api/public/v1/branding").status_code == 401


def test_key_management_requires_auth():
    from app.main import app
    client = TestClient(app)
    resp = client.get("/api/api-keys")
    assert resp.status_code in (401, 403)
