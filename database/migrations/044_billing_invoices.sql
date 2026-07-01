-- =============================================================================
-- 044_billing_invoices.sql  (UAE SaaS Phase 4 — manual billing + VAT invoices)
-- Subscriptions + VAT-aware invoices for the UAE reality: manual invoice, bank
-- transfer and purchase-order modes FIRST (no payment gateway required), with the
-- provider stored so Stripe/Telr/PayTabs/etc. can be added later without redesign.
-- Money is modelled in AED with explicit VAT. Tenant-scoped + RLS.
--
-- LEGAL/TAX: invoice + VAT modelling only. NOT a compliance guarantee. Draft —
-- requires review by a qualified UAE legal/tax professional before production/
-- customer use (VAT treatment, invoice format, e-invoicing, corporate tax).
-- =============================================================================

-- 1. Subscriptions ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS subscriptions (
    id                     SERIAL PRIMARY KEY,
    tenant_id              INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    plan                   VARCHAR(40) NOT NULL DEFAULT 'free',
    status                 TEXT NOT NULL DEFAULT 'trialing'
                             CHECK (status IN ('trialing','active','past_due','cancelled','manual')),
    billing_provider       TEXT NOT NULL DEFAULT 'manual'
                             CHECK (billing_provider IN ('manual','bank_transfer','purchase_order',
                                                         'stripe','telr','paytabs','network','checkout')),
    billing_cycle          TEXT NOT NULL DEFAULT 'monthly' CHECK (billing_cycle IN ('monthly','annual')),
    currency               CHAR(3) NOT NULL DEFAULT 'AED',
    current_period_start   TIMESTAMPTZ,
    current_period_end     TIMESTAMPTZ,
    trial_ends_at          TIMESTAMPTZ,
    external_customer_id   VARCHAR(120),   -- only ever a provider's opaque id, never a secret
    external_subscription_id VARCHAR(120),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_subscriptions_tenant ON subscriptions (tenant_id);

-- 2. Invoices ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS invoices (
    id                  SERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    invoice_number      TEXT NOT NULL UNIQUE,
    status              TEXT NOT NULL DEFAULT 'draft'
                          CHECK (status IN ('draft','issued','paid','void','credited')),
    billing_provider    TEXT NOT NULL DEFAULT 'manual',

    -- Supplier (the platform) — snapshotted onto the invoice at issue time.
    supplier_legal_name TEXT,
    supplier_trn        VARCHAR(15),
    -- Customer (the tenant) — snapshotted from tenant_billing_profile.
    customer_legal_name TEXT,
    customer_trn        VARCHAR(15),

    -- Money (AED). VAT is explicit; never fold VAT into the subtotal.
    currency            CHAR(3) NOT NULL DEFAULT 'AED',
    subtotal_aed        NUMERIC(14,2) NOT NULL DEFAULT 0,
    vat_rate            NUMERIC(5,4)  NOT NULL DEFAULT 0.05,   -- UAE standard rate 5%
    vat_amount_aed      NUMERIC(14,2) NOT NULL DEFAULT 0,
    total_aed           NUMERIC(14,2) NOT NULL DEFAULT 0,

    -- Period + procurement
    period_start        DATE,
    period_end          DATE,
    po_number           TEXT,
    payment_terms       TEXT,            -- e.g. "Net 30"
    payment_instructions TEXT,          -- bank transfer details (free text)
    payment_method      TEXT,            -- bank_transfer | card | cash | cheque
    issued_at           TIMESTAMPTZ,
    due_at              TIMESTAMPTZ,
    paid_at             TIMESTAMPTZ,

    -- E-invoicing future-readiness (UAE e-invoicing mandate is phased in).
    e_invoice_status        TEXT DEFAULT 'not_submitted'
                              CHECK (e_invoice_status IN ('not_submitted','submitted','accepted','rejected')),
    e_invoice_provider      TEXT,
    e_invoice_external_id   TEXT,
    e_invoice_payload       JSONB,
    e_invoice_submitted_at  TIMESTAMPTZ,
    e_invoice_accepted_at   TIMESTAMPTZ,
    e_invoice_rejected_reason TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_invoices_tenant ON invoices (tenant_id, created_at DESC);

-- 3. Invoice line items -----------------------------------------------------
CREATE TABLE IF NOT EXISTS invoice_lines (
    id                SERIAL PRIMARY KEY,
    invoice_id        INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    description       TEXT NOT NULL,
    quantity          NUMERIC(12,2) NOT NULL DEFAULT 1,
    unit_price_aed    NUMERIC(14,2) NOT NULL DEFAULT 0,
    line_subtotal_aed NUMERIC(14,2) NOT NULL DEFAULT 0,
    vat_rate          NUMERIC(5,4)  NOT NULL DEFAULT 0.05,
    vat_amount_aed    NUMERIC(14,2) NOT NULL DEFAULT 0,
    line_total_aed    NUMERIC(14,2) NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_invoice_lines_invoice ON invoice_lines (invoice_id);

-- 4. RLS (tenant-scoped). Lines scope through their parent invoice (like the
--    procurement line tables in migration 020).
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON subscriptions;
CREATE POLICY tenant_isolation ON subscriptions
    USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());

ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON invoices;
CREATE POLICY tenant_isolation ON invoices
    USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());

ALTER TABLE invoice_lines ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON invoice_lines;
CREATE POLICY tenant_isolation ON invoice_lines USING (
    EXISTS (SELECT 1 FROM invoices i WHERE i.id = invoice_id AND i.tenant_id = current_tenant_id()));

DO $$ BEGIN RAISE NOTICE 'billing: subscriptions + VAT invoices + lines ready (RLS on)'; END $$;
