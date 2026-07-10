"""E8-2 — payment gateway (Telr / PayTabs), honestly gated.

The lifecycle is built end to end (create a hosted-checkout intent → gateway posts a
signed webhook → we reconcile), but two properties are load-bearing and are what
these tests defend:

  1. A real gateway is REFUSED until it is added to IMPLEMENTED_PROVIDERS *and* its
     merchant credentials are present — recognising `telr`/`paytabs` is not enough.
     Credentials are read by ENV-VAR name, never stored in the DB.
  2. Nothing is EVER marked `paid` except by reconciling a webhook whose signature
     verified. `create_payment_session` can only ever produce a `pending` intent;
     settlement lives solely behind the `verified` gate in `handle_webhook`, and
     migration 069's CHECK enforces `status='paid' → settled_by_event_id` at the DB.

The live DB round-trip (create intent → invalid-signature webhook is recorded but
does NOT settle → valid-signature webhook settles intent + invoice → duplicate is
idempotent) is verified against the running stack in the commit; these are the cheap
DB-free structural + behavioural guards.
"""
import ast
import hashlib
import hmac
import inspect
import pathlib
import textwrap

import pytest

from app.services import payments


def _find_migration(name: str) -> pathlib.Path:
    """Locate a migration by walking up from this test — robust to the repo layout
    (backend/ and database/ siblings) AND the container layout (both under /app)."""
    here = pathlib.Path(__file__).resolve()
    for base in here.parents:
        cand = base / "database" / "migrations" / name
        if cand.is_file():
            return cand
    return here.parents[2] / "database" / "migrations" / name  # repo default


MIGRATION = _find_migration("069_krishna_payment_gateway.sql")


def _code(fn) -> str:
    """Source of a function with its docstring + decorators stripped, so assertions
    describe the CODE, not a comment that happens to mention a keyword."""
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    node.decorator_list = []
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        node.body = node.body[1:]
    return ast.unparse(node)


# --------------------------------------------------------------------------
# Provider gating — a recognised gateway is not a usable one.
# --------------------------------------------------------------------------

def test_only_mock_is_implemented():
    assert payments.IMPLEMENTED_PROVIDERS == {payments.MOCK_PROVIDER}
    assert payments.GATEWAY_PROVIDERS == {"telr", "paytabs"}
    assert payments.ALL_PROVIDERS == {"mock", "telr", "paytabs"}


def test_mock_is_always_available():
    assert payments.is_provider_available("mock") is True


def test_real_gateway_refused_even_with_credentials(monkeypatch):
    # A real gateway with full credentials is STILL refused: it is not integrated.
    monkeypatch.setenv("TELR_MERCHANT_ID", "m")
    monkeypatch.setenv("TELR_API_KEY", "k")
    assert payments.is_provider_available("telr") is False


def test_unknown_provider_is_not_available():
    assert payments.is_provider_available("stripe") is False


def test_provider_status_is_honest():
    st = payments.provider_status()
    assert set(st) == {"mock", "paytabs", "telr"}
    assert st["mock"]["usable"] is True and st["mock"]["implemented"] is True
    for p in ("telr", "paytabs"):
        assert st[p]["usable"] is False
        assert st[p]["implemented"] is False
        # The note tells the operator WHY it is refused, not a vague failure.
        assert "not integrated" in st[p]["note"]


# --------------------------------------------------------------------------
# Credentials are env-var names, never DB-stored plaintext.
# --------------------------------------------------------------------------

def test_credentials_read_from_env_by_name(monkeypatch):
    monkeypatch.setenv("PAYTABS_MERCHANT_ID", "MID")
    assert payments._env("paytabs", "MERCHANT_ID") == "MID"
    assert payments._env("paytabs", "API_KEY") is None


def test_no_credential_is_read_from_the_database():
    """Availability + signature checks must look up env vars, never a DB secret."""
    for fn in (payments.is_provider_available, payments.verify_webhook_signature):
        code = _code(fn)
        assert "_env(" in code or "os.getenv(" in code
        assert "SELECT" not in code  # never fetch a secret from the DB


# --------------------------------------------------------------------------
# Webhook signature verification (the gate for settlement).
# --------------------------------------------------------------------------

def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_valid_signature_verifies():
    body = b'{"event_id":"e1","order_ref":"MOCK-1","status":"paid"}'
    good = _sign("mock-webhook-secret", body)  # the default MOCK_WEBHOOK_SECRET
    assert payments.verify_webhook_signature("mock", body, good) is True


def test_wrong_signature_is_rejected():
    body = b'{"event_id":"e1","status":"paid"}'
    assert payments.verify_webhook_signature("mock", body, "deadbeef") is False


def test_missing_signature_is_rejected():
    assert payments.verify_webhook_signature("mock", b"{}", None) is False


def test_tampered_body_breaks_the_signature():
    body = b'{"amount":10}'
    sig = _sign("mock-webhook-secret", body)
    assert payments.verify_webhook_signature("mock", b'{"amount":9999}', sig) is False


def test_real_gateway_with_no_secret_cannot_verify():
    # No TELR_WEBHOOK_SECRET configured → any signature fails closed.
    assert payments.verify_webhook_signature("telr", b"{}", "anything") is False


# --------------------------------------------------------------------------
# create_payment_session can never settle; it refuses unusable providers.
# --------------------------------------------------------------------------

class _ExplodingDB:
    """A DB that fails loudly if touched — proves the refusal happens BEFORE any
    query, i.e. an unusable provider never reaches the invoice/intent tables."""
    async def execute(self, *a, **k):
        raise AssertionError("DB was queried for an unavailable provider")

    async def commit(self):
        raise AssertionError("DB commit for an unavailable provider")


@pytest.mark.asyncio
async def test_create_session_refuses_unintegrated_gateway_before_db():
    intent, err = await payments.create_payment_session(
        _ExplodingDB(), tenant_id=1, invoice_id=1, provider="telr", created_by="a")
    assert intent is None
    assert "not available" in err and "not yet integrated" in err


@pytest.mark.asyncio
async def test_create_session_rejects_unknown_provider():
    intent, err = await payments.create_payment_session(
        _ExplodingDB(), tenant_id=1, invoice_id=1, provider="stripe", created_by="a")
    assert intent is None and "Unknown payment provider" in err


def test_create_session_never_sets_status_paid():
    """The create path may write 'created' / 'pending' / 'failed' — never 'paid'.
    (Reading `inv['status'] == 'paid'` to reject an already-paid invoice is fine; what
    is forbidden is SETTING an intent to paid outside the verified-webhook path.)"""
    code = _code(payments.create_payment_session)
    # The only way 'paid' could be a WRITE target is `SET status='paid'`; a read
    # comparison unparses to `inv['status'] == 'paid'`, which does not match this.
    assert "status='paid'" not in code


# --------------------------------------------------------------------------
# Settlement is gated on a verified signature — structurally.
# --------------------------------------------------------------------------

def test_settlement_is_unreachable_without_verification():
    """In handle_webhook the `paid` UPDATE must sit AFTER an early `if not verified`
    return, so an unverified event can never settle a payment."""
    code = _code(payments.handle_webhook)
    assert "if not verified:" in code
    assert "status='paid'" in code  # the reconcile UPDATE exists
    # The guard precedes the settlement.
    assert code.index("if not verified:") < code.index("status='paid'")


def test_settlement_records_the_event_that_caused_it():
    """A settled intent points at the webhook event id (mirrors the DB CHECK)."""
    code = _code(payments.handle_webhook)
    assert "settled_by_event_id=:ev" in code


def test_normalise_result_maps_gateway_vocab():
    assert payments._normalise_result("captured") == "paid"
    assert payments._normalise_result("A") == "paid"
    assert payments._normalise_result("declined") == "failed"
    assert payments._normalise_result("canceled") == "cancelled"
    assert payments._normalise_result("weird") == "unknown"


# --------------------------------------------------------------------------
# Migration guards.
# --------------------------------------------------------------------------

def test_migration_enforces_paid_requires_event():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    # A stripped, comment-free view so we assert on DDL, not the explanatory header.
    ddl = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    assert "payment_intents_paid_has_event" in ddl
    assert "status <> 'paid' or settled_by_event_id is not null" in ddl


def test_migration_scopes_intents_by_rls_and_dedupes_webhooks():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    ddl = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    assert "enable row level security" in ddl and "force row level security" in ddl
    assert "tenant_isolation" in ddl
    # Webhook idempotency: one row per (provider, event_ref).
    assert "unique (provider, event_ref)" in ddl


# --------------------------------------------------------------------------
# Route + middleware wiring.
# --------------------------------------------------------------------------

def test_intent_creation_is_admin_only():
    from app.routes import payments as routes
    code = _code(routes.create_intent)
    assert "_require_admin(user)" in code


def test_webhook_is_public_and_signature_authed():
    from app.routes import payments as routes
    code = _code(routes.webhook)
    # No auth dependency (a gateway has no session); it reads a signature header.
    assert "get_current_user" not in code
    assert "X-Signature" in code or "Signature" in code
    assert "handle_webhook" in code


def test_webhook_path_is_csrf_exempt():
    from app.middleware import CSRFMiddleware
    assert any("/api/payments/webhook/" in p for p in CSRFMiddleware.EXEMPT_PREFIXES)


def test_router_is_registered_under_api_payments():
    from app.routes.registry import ROUTERS
    assert any(prefix == "/api/payments" for _, prefix, _ in ROUTERS)
