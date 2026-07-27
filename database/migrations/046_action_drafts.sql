-- =============================================================================
-- 046_action_drafts.sql  (Agentic increment — autonomy level 1)
-- Extends the diagnostics loop one stage: detect → diagnose → recommend → accept
-- → DRAFT (here) → human approves → human executes. The system DRAFTS a concrete,
-- human-approvable artifact from a finding's recommended action (a supplier email,
-- a markdown/promotion proposal, a review task). It NEVER sends or executes anything
-- — approval records a human decision; execution stays with the operator. PO
-- replenishment drafting already exists in procurement (approval_rules); this covers
-- the communication/decision actions the findings loop produces.
--
-- Tenant-scoped + RLS like the rest of the schema.
-- =============================================================================

CREATE TABLE IF NOT EXISTS action_drafts (
    id            SERIAL PRIMARY KEY,
    tenant_id     INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    finding_id    INTEGER REFERENCES findings(id) ON DELETE SET NULL,
    draft_type    TEXT NOT NULL CHECK (draft_type IN
                    ('supplier_email','markdown_proposal','promotion_proposal',
                     'review_task','purchase_order')),
    status        TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft','approved','rejected')),
    title         TEXT NOT NULL,
    summary       TEXT,
    payload       JSONB NOT NULL DEFAULT '{}',   -- the drafted content (subject/body/steps/…)
    source_action_type TEXT,                      -- the finding action_type it was built from
    created_by    TEXT,                           -- 'system' or the user who triggered it
    reviewed_by   TEXT,
    review_note   TEXT,
    reviewed_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_action_drafts_tenant_status
    ON action_drafts (tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_action_drafts_finding ON action_drafts (finding_id);

ALTER TABLE action_drafts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON action_drafts;
CREATE POLICY tenant_isolation ON action_drafts
    USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());

DO $$ BEGIN RAISE NOTICE 'action_drafts: autonomy-L1 human-approved drafts ready (RLS on)'; END $$;
