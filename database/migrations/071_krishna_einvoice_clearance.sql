-- 071 — E10-4: UAE-FTA e-invoice CLEARANCE harness — submission ledger + PIH chain.
--
-- WHAT THIS ADDS. Migration 044 gave invoices a coarse e_invoice_status. Real UAE FTA
-- clearance needs an auditable SUBMISSION per attempt: the exact UBL 2.1 document that
-- was submitted, its cryptographic hash, the PREVIOUS invoice's hash it chains to (PIH
-- — the tamper-evident chain ZATCA/FTA-style clearance requires), the signature, and
-- the clearing house's response. This table is that ledger.
--
-- THE HONEST BOUNDARY (unchanged from einvoicing.py / P1.2):
--   * Only the `mock` clearing house, in the `sandbox` environment, actually clears an
--     invoice — and everything it produces is SANDBOX-labelled and is_production_signed
--     = FALSE, so a sandbox clearance can never be mistaken for a real FTA one.
--   * A real gateway (`uae_fta`) is REFUSED by the service until it is integrated AND
--     the operator is FTA-accredited. Accreditation is an organisational/legal process
--     that code cannot shortcut; this schema is what a real integration will WRITE to,
--     not a claim that clearance has happened.
--   * `is_production_signed` can only be TRUE in the `production` environment — enforced
--     by a CHECK — so no sandbox row can ever assert a production-grade signature.
--
-- LEGAL/TAX: NOT a compliance guarantee. UAE e-invoicing format, PINT-AE/UBL profile,
-- accreditation and signing rules require review by a qualified UAE tax professional
-- before production use.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS / DROP ... IF EXISTS / guarded constraints.

BEGIN;

CREATE TABLE IF NOT EXISTS einvoice_submissions (
    id                    BIGSERIAL PRIMARY KEY,
    tenant_id             INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    invoice_id            INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    provider              TEXT NOT NULL,
    environment           TEXT NOT NULL CHECK (environment IN ('sandbox', 'production')),
    -- building -> submitted -> cleared | rejected | error.
    status                TEXT NOT NULL DEFAULT 'building'
                            CHECK (status IN ('building', 'submitted', 'cleared', 'rejected', 'error')),

    -- The exact document submitted, and its canonical SHA-256 (hex).
    ubl_xml               TEXT,
    invoice_hash          TEXT,
    -- PIH: the invoice_hash of this tenant's previously CLEARED submission. NULL for the
    -- first in the chain. This is what makes the clearance sequence tamper-evident.
    previous_invoice_hash TEXT,

    -- The signature over the document, and whether it is a real production signature.
    -- A sandbox run produces a labelled digest with is_production_signed = FALSE.
    signature             TEXT,
    is_production_signed  BOOLEAN NOT NULL DEFAULT FALSE,

    -- The clearing house's identifiers/response. clearance_ref is SANDBOX- prefixed for
    -- the mock so it can never be confused with a real FTA clearance UUID.
    clearance_ref         TEXT,
    cleared_at            TIMESTAMPTZ,
    rejection_reason      TEXT,
    poll_attempts         INTEGER NOT NULL DEFAULT 0,
    response_payload      JSONB,

    submitted_by          TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A cleared submission must carry the document hash AND a clearance reference — so
-- 'cleared' can never be a bare status with no document or no clearing response behind it.
ALTER TABLE einvoice_submissions DROP CONSTRAINT IF EXISTS einvoice_submissions_cleared_has_proof;
ALTER TABLE einvoice_submissions
    ADD CONSTRAINT einvoice_submissions_cleared_has_proof
    CHECK (status <> 'cleared' OR (clearance_ref IS NOT NULL AND invoice_hash IS NOT NULL));

-- A production-grade signature can only exist in the production environment. A sandbox
-- row asserting a production signature is a contradiction the DB rejects.
ALTER TABLE einvoice_submissions DROP CONSTRAINT IF EXISTS einvoice_submissions_prod_sig_only_in_prod;
ALTER TABLE einvoice_submissions
    ADD CONSTRAINT einvoice_submissions_prod_sig_only_in_prod
    CHECK (is_production_signed = FALSE OR environment = 'production');

CREATE INDEX IF NOT EXISTS ix_einvoice_submissions_invoice ON einvoice_submissions (invoice_id);
-- PIH chain lookup: the tenant's most recent cleared submission.
CREATE INDEX IF NOT EXISTS ix_einvoice_submissions_chain
    ON einvoice_submissions (tenant_id, cleared_at DESC) WHERE status = 'cleared';

ALTER TABLE einvoice_submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE einvoice_submissions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON einvoice_submissions;
CREATE POLICY tenant_isolation ON einvoice_submissions
    USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());

COMMIT;

DO $$ BEGIN
    RAISE NOTICE 'einvoice_submissions ready; only mock/sandbox clears, real FTA refused '
                 'until accredited, production signature impossible in sandbox';
END $$;
