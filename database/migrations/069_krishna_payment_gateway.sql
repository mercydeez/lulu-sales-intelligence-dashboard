-- 069 — E8-2: payment gateway (Telr / PayTabs) — intents + webhook ledger.
--
-- WHAT THIS DOES AND DOES NOT DO. It records a PAYMENT INTENT (a request to collect
-- an invoice's total through a hosted checkout) and every webhook the gateway sends
-- back. It NEVER marks an invoice paid on its own: a payment reaches 'paid' only
-- when a webhook with a VERIFIED signature says the gateway settled it. No money
-- moves through this schema — it is the reconciliation ledger a real merchant
-- integration writes to.
--
-- Like the e-invoicing providers, a real gateway (telr/paytabs) is REFUSED at the
-- service layer until its merchant credentials are configured AND it is added to
-- services/payments.IMPLEMENTED_PROVIDERS. The `mock` provider produces a demo
-- checkout URL but still requires an explicit webhook to settle — so nothing is
-- ever fabricated as paid.

BEGIN;

CREATE TABLE IF NOT EXISTS payment_intents (
    id             SERIAL PRIMARY KEY,
    tenant_id      INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    invoice_id     INTEGER REFERENCES invoices(id) ON DELETE SET NULL,
    provider       TEXT NOT NULL,
    amount_aed     NUMERIC(12,2) NOT NULL CHECK (amount_aed >= 0),
    currency       TEXT NOT NULL DEFAULT 'AED',
    -- created -> pending (checkout issued) -> paid | failed | cancelled | expired.
    status         TEXT NOT NULL DEFAULT 'created'
                     CHECK (status IN ('created', 'pending', 'paid', 'failed',
                                       'cancelled', 'expired')),
    -- The gateway's own order/reference id; the hosted checkout URL the buyer visits.
    external_ref   TEXT,
    checkout_url   TEXT,
    -- A payment only becomes 'paid' via a verified webhook; this records which one.
    settled_by_event_id INTEGER,
    failure_reason TEXT,
    created_by     TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A paid intent must name the verified webhook that settled it — so 'paid' can
-- never be set by anything other than reconciling a real gateway event.
ALTER TABLE payment_intents DROP CONSTRAINT IF EXISTS payment_intents_paid_has_event;
ALTER TABLE payment_intents
    ADD CONSTRAINT payment_intents_paid_has_event
    CHECK (status <> 'paid' OR settled_by_event_id IS NOT NULL);

CREATE INDEX IF NOT EXISTS ix_payment_intents_tenant ON payment_intents (tenant_id, status);
CREATE INDEX IF NOT EXISTS ix_payment_intents_external ON payment_intents (provider, external_ref);

ALTER TABLE payment_intents ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_intents FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON payment_intents;
CREATE POLICY tenant_isolation ON payment_intents
    USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());

-- Every webhook the gateway sends, with whether its signature verified. The
-- reconciler reads these; an unverified event is recorded but never settles a payment.
CREATE TABLE IF NOT EXISTS payment_webhook_events (
    id                 SERIAL PRIMARY KEY,
    provider           TEXT NOT NULL,
    event_ref          TEXT,               -- the gateway's event/transaction id
    signature_verified BOOLEAN NOT NULL DEFAULT FALSE,
    intent_id          INTEGER REFERENCES payment_intents(id) ON DELETE SET NULL,
    result             TEXT,               -- 'paid' | 'failed' | 'cancelled' | 'unknown'
    payload            JSONB,
    processed          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Idempotency: a gateway may retry a webhook; one row per (provider, event_ref).
    UNIQUE (provider, event_ref)
);

CREATE INDEX IF NOT EXISTS ix_payment_webhook_intent ON payment_webhook_events (intent_id);

-- Webhook events are cross-tenant infrastructure (the gateway posts them without a
-- tenant session); the reconciler resolves the tenant via the intent. Not RLS-scoped.

COMMIT;

DO $$ BEGIN
    RAISE NOTICE 'payment intents + webhook ledger ready; paid requires a verified webhook';
END $$;
