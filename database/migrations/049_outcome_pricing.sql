-- =============================================================================
-- 049_outcome_pricing.sql  (Outcome-based pricing — the measure-loop capstone)
-- Ties (part of) the fee to PROVEN outcomes. The measure loop already records which
-- accepted recommendations actually worked (findings.outcome_status = 'improved').
-- Here a human CONFIRMS the AED value realised per improved finding; the fee = base
-- + a share of CONFIRMED value, with a savings guarantee that waives the variable
-- portion if the bar isn't met. The platform never fabricates a saving — the bill
-- is only ever based on value a human signed off. Tenant-scoped + RLS.
-- =============================================================================

CREATE TABLE IF NOT EXISTS outcome_pricing_plans (
    tenant_id                  INTEGER PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    base_fee_aed               NUMERIC(12,2) NOT NULL DEFAULT 0,
    value_share_pct            NUMERIC(5,2)  NOT NULL DEFAULT 0,   -- % of confirmed realised value
    savings_guarantee_multiple NUMERIC(5,2)  NOT NULL DEFAULT 0,   -- save >= N x base fee, or variable waived
    currency                   CHAR(3) NOT NULL DEFAULT 'AED',
    active                     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE outcome_pricing_plans ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON outcome_pricing_plans;
CREATE POLICY tenant_isolation ON outcome_pricing_plans
    USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());

CREATE TABLE IF NOT EXISTS value_realizations (
    id                  SERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    finding_id          INTEGER NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    estimated_value_aed NUMERIC(12,2),                       -- optional suggestion (never fabricated)
    confirmed_value_aed NUMERIC(12,2),                       -- operator-confirmed AED saved/recovered
    method              TEXT,                                -- how it was quantified
    status              TEXT NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending','confirmed','dismissed')),
    note                TEXT,
    confirmed_by        TEXT,
    confirmed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (finding_id)
);
CREATE INDEX IF NOT EXISTS ix_value_realizations_tenant
    ON value_realizations (tenant_id, status, confirmed_at DESC);
ALTER TABLE value_realizations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON value_realizations;
CREATE POLICY tenant_isolation ON value_realizations
    USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());

DO $$ BEGIN RAISE NOTICE 'outcome pricing: plans + confirmed value realizations ready (RLS on)'; END $$;
