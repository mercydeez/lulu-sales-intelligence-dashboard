"""E8-2 — payment gateway integration (Telr / PayTabs), honestly gated.

The same posture as e-invoicing: the lifecycle is built (create a hosted-checkout
PAYMENT INTENT for an invoice → the buyer pays on the gateway's page → the gateway
posts a signed webhook → we reconcile), but a real gateway is REFUSED until its
merchant credentials are configured AND it is added to IMPLEMENTED_PROVIDERS.

TWO THINGS ARE LOAD-BEARING AND NON-NEGOTIABLE:

1. Nothing is ever marked `paid` except by reconciling a webhook whose signature
   VERIFIED. `create_payment_session` only ever produces a `pending` intent + a
   checkout URL; it can never settle a payment. Migration 069's CHECK enforces
   this at the DB (`status='paid'` requires `settled_by_event_id`).

2. Money is not moved by this code. A real merchant integration calls the gateway
   with the operator's credentials; this module builds the request, records the
   intent, verifies the callback signature, and updates state from the gateway's
   ACTUAL response. Without credentials it refuses — it never fabricates a success.

The `mock` provider exists for demoing the FLOW (it returns a checkout URL tagged
`MOCK-`), but even it requires an explicit webhook to settle — so a demo can never
be mistaken for a real collection.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import logger

MOCK_PROVIDER = "mock"
# UAE-focused hosted-checkout gateways. Recognised, but not integrated.
GATEWAY_PROVIDERS = {"telr", "paytabs"}
ALL_PROVIDERS = {MOCK_PROVIDER} | GATEWAY_PROVIDERS

# Providers with an ACTUAL settlement implementation. A gateway being recognised +
# key-configured does NOT mean we can collect through it — the outbound integration
# is not certified/wired. Only `mock` runs the flow end to end (against no real
# money). Adding a real gateway is: implement its create-session + verify-signature
# adapter, then add it here.
IMPLEMENTED_PROVIDERS = {MOCK_PROVIDER}


def _env(provider: str, key: str) -> Optional[str]:
    """A gateway credential, by env-var name — never stored in the DB."""
    return os.getenv(f"{provider.upper()}_{key}")


def _mock_allowed() -> bool:
    """The `mock` gateway is a DEMO tool that settles against no real money and,
    when MOCK_WEBHOOK_SECRET is unset, verifies with a source-code-known default
    secret. It must therefore be UNUSABLE in a real production/staging deployment,
    or anyone able to reach the public webhook could flip a real invoice to `paid`
    for free. Allow it only outside production/staging, or on an explicit demo
    deployment (DEMO_MODE=true) — the same gate the synthetic generator/seed use.
    """
    try:
        from app.config import get_settings
        s = get_settings()
        env = (s.environment or "").lower()
        if env in ("production", "staging"):
            return bool(getattr(s, "demo_mode", False))
        return True
    except Exception:
        # Fail safe: if we cannot determine the environment, do NOT enable mock.
        return False


def is_provider_available(provider: str) -> bool:
    """A provider is usable only if it is IMPLEMENTED and (for a real gateway) its
    merchant credentials are present. `mock` is available only where
    _mock_allowed() permits it (never in real production)."""
    if provider == MOCK_PROVIDER:
        return provider in IMPLEMENTED_PROVIDERS and _mock_allowed()
    if provider in GATEWAY_PROVIDERS:
        has_creds = bool(_env(provider, "MERCHANT_ID") and _env(provider, "API_KEY"))
        return provider in IMPLEMENTED_PROVIDERS and has_creds
    return False


def provider_status() -> Dict[str, Dict[str, Any]]:
    """What an operator sees: which gateways are recognised, configured, usable."""
    out = {}
    for p in sorted(ALL_PROVIDERS):
        implemented = p in IMPLEMENTED_PROVIDERS
        configured = p == MOCK_PROVIDER or bool(_env(p, "MERCHANT_ID") and _env(p, "API_KEY"))
        out[p] = {
            "implemented": implemented,
            "configured": configured,
            "usable": is_provider_available(p),
            "note": (
                "demo flow only; no real money" if p == MOCK_PROVIDER
                else "recognised but not integrated — refused until certified + wired"
                     if not implemented else
                "configured" if configured else "set {P}_MERCHANT_ID + {P}_API_KEY".replace("{P}", p.upper())
            ),
        }
    return out


# ---------------------------------------------------------------------------
# Create a hosted-checkout payment intent for an invoice.
# ---------------------------------------------------------------------------

async def create_payment_session(
    db: AsyncSession, *, tenant_id: int, invoice_id: int, provider: str, created_by: str,
    return_url: Optional[str] = None,
) -> Tuple[Optional[Dict], Optional[str]]:
    """Create a PENDING payment intent + a hosted-checkout URL. Returns (intent, None)
    or (None, error). Never settles — settlement is webhook-only."""
    if provider not in ALL_PROVIDERS:
        return None, f"Unknown payment provider {provider!r}"
    if not is_provider_available(provider):
        return None, (
            f"Payment provider '{provider}' is not available. "
            + ("It is recognised but not yet integrated (refused until certified)."
               if provider in GATEWAY_PROVIDERS and provider not in IMPLEMENTED_PROVIDERS
               else f"Set {provider.upper()}_MERCHANT_ID and {provider.upper()}_API_KEY.")
        )

    inv = (await db.execute(text("""
        SELECT id, total_aed, currency, status, invoice_number
          FROM invoices WHERE id = :id AND tenant_id = :t
    """), {"id": invoice_id, "t": tenant_id})).mappings().fetchone()
    if not inv:
        return None, "Invoice not found for this tenant"
    if inv["status"] == "paid":
        return None, "Invoice is already paid"

    amount = Decimal(str(inv["total_aed"] or 0))
    currency = inv["currency"] or "AED"

    # Build the intent first so we have its id for the gateway's order reference.
    intent_id = (await db.execute(text("""
        INSERT INTO payment_intents (tenant_id, invoice_id, provider, amount_aed, currency,
                                     status, created_by)
        VALUES (:t, :inv, :p, :amt, :cur, 'created', :by)
        RETURNING id
    """), {"t": tenant_id, "inv": invoice_id, "p": provider, "amt": amount,
           "cur": currency, "by": created_by})).scalar()

    try:
        external_ref, checkout_url = await _provider_create_checkout(
            provider, intent_id=intent_id, amount=amount, currency=currency,
            invoice_number=inv["invoice_number"], return_url=return_url)
    except Exception as exc:
        await db.execute(text(
            "UPDATE payment_intents SET status='failed', failure_reason=:r, updated_at=now() WHERE id=:id"),
            {"r": f"checkout creation failed: {exc}", "id": intent_id})
        await db.commit()
        return None, f"Could not create checkout with {provider}: {exc}"

    await db.execute(text("""
        UPDATE payment_intents
           SET status='pending', external_ref=:ref, checkout_url=:url, updated_at=now()
         WHERE id=:id
    """), {"ref": external_ref, "url": checkout_url, "id": intent_id})
    await db.commit()

    return {
        "intent_id": intent_id, "invoice_id": invoice_id, "provider": provider,
        "amount_aed": float(amount), "currency": currency, "status": "pending",
        "checkout_url": checkout_url, "external_ref": external_ref,
    }, None


async def _provider_create_checkout(provider: str, *, intent_id: int, amount: Decimal,
                                    currency: str, invoice_number: str,
                                    return_url: Optional[str]) -> Tuple[str, str]:
    """Ask the gateway to create a hosted-checkout order. Returns (external_ref, url).

    Only `mock` is implemented; real adapters (telr/paytabs) would POST the order to
    the gateway's create-session endpoint with the merchant credentials and return
    the payment page URL from its response — never a synthesised one.
    """
    if provider == MOCK_PROVIDER:
        # A demo checkout URL. It settles ONLY via an explicit webhook, so it can
        # never be mistaken for a real, automatically-completed payment.
        ref = f"MOCK-{intent_id}"
        return ref, f"https://checkout.mock.local/pay/{ref}?amount={amount}&cur={currency}"
    # Real gateways are refused before reaching here (is_provider_available), so this
    # is defence in depth: never fabricate a checkout for an unintegrated gateway.
    raise RuntimeError(f"{provider} checkout is not integrated")


# ---------------------------------------------------------------------------
# Webhook: the ONLY path that can settle a payment.
# ---------------------------------------------------------------------------

def verify_webhook_signature(provider: str, raw_body: bytes, signature: Optional[str]) -> bool:
    """Verify a webhook's authenticity with the provider's signing secret.

    For a real gateway this is the merchant HMAC/secret check its docs prescribe.
    `mock` uses an HMAC over the body with MOCK_WEBHOOK_SECRET, so even the demo
    path exercises a real signature check rather than trusting the caller.
    """
    # Defense in depth: the public webhook is the ONLY path that settles a payment,
    # so the mock gateway's signature must NEVER verify where mock is disallowed
    # (real production). Without this, a mock webhook signed with the known default
    # secret could settle a real invoice even though intent-creation is refused.
    if provider == MOCK_PROVIDER and not _mock_allowed():
        return False
    secret = _env(provider, "WEBHOOK_SECRET")
    if provider == MOCK_PROVIDER and not secret:
        secret = os.getenv("MOCK_WEBHOOK_SECRET", "mock-webhook-secret")
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def handle_webhook(db: AsyncSession, provider: str, raw_body: bytes,
                         signature: Optional[str]) -> Dict[str, Any]:
    """Record a gateway webhook and, if its signature verifies, reconcile the intent.

    Idempotent: a retried webhook (same provider+event_ref) updates nothing twice.
    An UNVERIFIED webhook is recorded (for audit) but NEVER settles a payment.
    """
    verified = verify_webhook_signature(provider, raw_body, signature)
    try:
        body = json.loads(raw_body.decode("utf-8"))
    except Exception:
        body = {}

    event_ref = str(body.get("event_id") or body.get("tran_ref") or body.get("ref") or "")
    external_ref = str(body.get("order_ref") or body.get("cart_id") or body.get("intent_ref") or "")
    result = _normalise_result(body.get("status") or body.get("respStatus") or body.get("result"))

    # Resolve the intent this event belongs to.
    intent = None
    if external_ref:
        intent = (await db.execute(text(
            "SELECT id, tenant_id, invoice_id, status FROM payment_intents "
            "WHERE provider=:p AND external_ref=:r"),
            {"p": provider, "r": external_ref})).mappings().fetchone()

    # Record the event (idempotent). ON CONFLICT keeps the first — a retry is a no-op.
    ev_id = (await db.execute(text("""
        INSERT INTO payment_webhook_events (provider, event_ref, signature_verified,
                                            intent_id, result, payload, processed)
        VALUES (:p, :er, :verified, :iid, :res, CAST(:payload AS JSONB), FALSE)
        ON CONFLICT (provider, event_ref) DO NOTHING
        RETURNING id
    """), {"p": provider, "er": event_ref or f"noref-{id(raw_body)}",
           "verified": verified, "iid": intent["id"] if intent else None,
           "res": result, "payload": json.dumps(body)})).scalar()
    await db.commit()

    if ev_id is None:
        return {"status": "duplicate_ignored", "provider": provider, "event_ref": event_ref}
    if not verified:
        logger.warning(f"[payments] {provider} webhook signature FAILED — recorded, not settling")
        return {"status": "signature_invalid", "event_id": ev_id}
    if not intent:
        return {"status": "no_matching_intent", "event_id": ev_id, "external_ref": external_ref}

    # Reconcile — the only place an intent (and its invoice) can move to paid.
    if result == "paid" and intent["status"] != "paid":
        await db.execute(text("""
            UPDATE payment_intents SET status='paid', settled_by_event_id=:ev, updated_at=now()
             WHERE id=:id
        """), {"ev": ev_id, "id": intent["id"]})
        if intent["invoice_id"]:
            await db.execute(text("""
                UPDATE invoices SET status='paid', paid_at=now(),
                       payment_method=:pm, updated_at=now()
                 WHERE id=:iid AND tenant_id=:t
            """), {"pm": provider, "iid": intent["invoice_id"], "t": intent["tenant_id"]})
    elif result in ("failed", "cancelled"):
        await db.execute(text(
            "UPDATE payment_intents SET status=:s, failure_reason=:r, updated_at=now() WHERE id=:id"),
            {"s": result, "r": f"gateway reported {result}", "id": intent["id"]})

    await db.execute(text("UPDATE payment_webhook_events SET processed=TRUE WHERE id=:id"), {"id": ev_id})
    await db.commit()
    return {"status": "reconciled", "event_id": ev_id, "intent_id": intent["id"], "result": result}


def _normalise_result(raw) -> str:
    s = str(raw or "").lower()
    if s in ("paid", "captured", "success", "authorised", "authorized", "a", "1"):
        return "paid"
    if s in ("failed", "declined", "error", "e"):
        return "failed"
    if s in ("cancelled", "canceled", "c"):
        return "cancelled"
    return "unknown"
