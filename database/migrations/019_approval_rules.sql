-- 019_approval_rules.sql
-- Configurable, per-tenant purchase approval policy (Part III-E). Lets a tenant
-- set the amount under which a forecast-generated PO is auto-approved (low-value
-- orders flow without a human), while larger POs stay in 'draft' for review.

CREATE TABLE IF NOT EXISTS approval_rules (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL UNIQUE REFERENCES tenants(id) ON DELETE CASCADE,
    auto_approve_under NUMERIC(14,2) NOT NULL DEFAULT 0,   -- 0 = never auto-approve
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE approval_rules ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON approval_rules;
CREATE POLICY tenant_isolation ON approval_rules
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

DO $$ BEGIN RAISE NOTICE 'Approval rules ready (auto-approve threshold per tenant)'; END $$;
