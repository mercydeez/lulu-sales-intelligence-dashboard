"""
B4 — outbound webhooks. Unit-covers the security-critical HMAC signing/verify
roundtrip and event-subscription matching, and confirms the management routes
are registered and reject unauthenticated access.
"""
from fastapi.testclient import TestClient

from app.services import webhook_service as wh


def test_sign_and_verify_roundtrip():
    secret = wh.generate_secret()
    body = b'{"event":"webhook.test","data":{"x":1}}'
    sig = wh.sign_payload(secret, body)
    assert len(sig) == 64  # sha256 hex
    assert wh.verify_signature(secret, body, sig)
    assert wh.verify_signature(secret, body, f"sha256={sig}")  # header form


def test_verify_rejects_tampered_body_or_secret():
    secret = wh.generate_secret()
    body = b'{"amount": 100}'
    sig = wh.sign_payload(secret, body)
    assert not wh.verify_signature(secret, b'{"amount": 999}', sig)   # tampered body
    assert not wh.verify_signature(wh.generate_secret(), body, sig)   # wrong secret


def test_generate_secret_is_unique_and_prefixed():
    a, b = wh.generate_secret(), wh.generate_secret()
    assert a != b
    assert a.startswith("whsec_")


def test_event_subscription_matching():
    assert wh._subscribed(["*"], "alert.created")
    assert wh._subscribed(["alert.created", "stock.low"], "stock.low")
    assert not wh._subscribed(["alert.created"], "stock.low")


def test_webhook_routes_registered():
    from app.main import app
    paths = {r.path for r in app.routes}
    assert "/api/webhooks" in paths
    assert "/api/webhooks/test" in paths
    assert "/api/webhooks/{webhook_id}" in paths


def test_webhook_management_requires_auth():
    from app.main import app
    client = TestClient(app)
    assert client.get("/api/webhooks").status_code in (401, 403)
