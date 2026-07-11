"""Regression tests for Critical finding C4 — the mock payment provider must not
be usable, and its webhook must not settle, in a real production deployment.

The mock gateway settles against no real money and, when MOCK_WEBHOOK_SECRET is
unset (as it will be in production), verifies with a source-code-known default
secret. The public webhook is the ONLY settlement path, so if mock were live in
production anyone reaching it could flip a real invoice to `paid` for free.

`_mock_allowed()` gates it to non-production (or an explicit DEMO_MODE box). These
tests pin: refused in production/staging, allowed in dev/testing and demo-prod,
and — defense in depth — the mock webhook cannot even verify in production.
"""
import hashlib
import hmac
from types import SimpleNamespace

import pytest

from app.services import payments

_DEFAULT_SECRET = b"mock-webhook-secret"  # payments.verify_webhook_signature fallback


def _force_env(monkeypatch, environment, demo_mode=False):
    """Make payments._mock_allowed() see a chosen environment/demo flag."""
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: SimpleNamespace(environment=environment, demo_mode=demo_mode),
    )


def _mock_paid_webhook():
    body = b'{"event_id":"e1","order_ref":"MOCK-1","status":"paid"}'
    sig = hmac.new(_DEFAULT_SECRET, body, hashlib.sha256).hexdigest()
    return body, sig


@pytest.mark.parametrize("env", ["development", "testing"])
def test_mock_available_outside_production(monkeypatch, env):
    _force_env(monkeypatch, env)
    assert payments.is_provider_available("mock") is True


@pytest.mark.parametrize("env", ["production", "staging"])
def test_mock_refused_in_production_and_staging(monkeypatch, env):
    _force_env(monkeypatch, env, demo_mode=False)
    assert payments.is_provider_available("mock") is False


def test_mock_allowed_on_demo_production_box(monkeypatch):
    """A demo deployment on a prod-env host (DEMO_MODE=true) may run the demo flow —
    consistent with how the synthetic generator/seed are gated."""
    _force_env(monkeypatch, "production", demo_mode=True)
    assert payments.is_provider_available("mock") is True


def test_mock_webhook_cannot_verify_in_production(monkeypatch):
    """The settlement gate: a mock webhook signed with the known default secret
    must NOT verify in production, so it can never settle a real invoice."""
    _force_env(monkeypatch, "production", demo_mode=False)
    body, sig = _mock_paid_webhook()
    assert payments.verify_webhook_signature("mock", body, sig) is False


def test_mock_webhook_verifies_where_allowed(monkeypatch):
    """In dev/demo the mock webhook still verifies (the demo flow must work)."""
    _force_env(monkeypatch, "development")
    body, sig = _mock_paid_webhook()
    assert payments.verify_webhook_signature("mock", body, sig) is True


class _ExplodingDB:
    async def execute(self, *a, **k):
        raise AssertionError("DB touched for a refused mock provider")

    async def commit(self):
        raise AssertionError("commit for a refused mock provider")


@pytest.mark.asyncio
async def test_create_session_refuses_mock_in_production(monkeypatch):
    """Intent creation must refuse mock in production BEFORE any DB work."""
    _force_env(monkeypatch, "production", demo_mode=False)
    intent, err = await payments.create_payment_session(
        _ExplodingDB(), tenant_id=1, invoice_id=1, provider="mock", created_by="a")
    assert intent is None
    assert "not available" in err


def test_mock_fails_safe_when_environment_unknown(monkeypatch):
    """If the environment cannot be resolved, mock must fail SAFE (disabled)."""
    def _boom():
        raise RuntimeError("settings unavailable")
    monkeypatch.setattr("app.config.get_settings", _boom)
    assert payments.is_provider_available("mock") is False
