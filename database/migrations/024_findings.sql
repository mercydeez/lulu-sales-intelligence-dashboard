-- 024_findings.sql
-- The diagnostics "findings" contract (PRODUCT_BUILD_PLAN.md A3).
--
-- A finding is one explainable problem the system detected: a rule fired, with the
-- evidence (the numbers) and a human sentence. The Node BullMQ worker WRITES these
-- (deterministic rules over the data); the backend API + dashboard + Sage READ them.
-- Keeping the contract in SQL is what lets the Python app and the Node worker share
-- it without coupling code.

CREATE TABLE IF NOT EXISTS findings (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   INTEGER NOT NULL DEFAULT 1,
    rule        TEXT NOT NULL,                       -- e.g. 'revenue_drop'
    category    TEXT NOT NULL DEFAULT 'general',     -- sales | returns | forecast | inventory
    severity    TEXT NOT NULL DEFAULT 'medium'
                CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    title       TEXT NOT NULL,                       -- short headline
    detail      TEXT NOT NULL,                       -- the explanation sentence
    evidence    JSONB NOT NULL DEFAULT '{}'::jsonb,  -- the numbers behind it
    entity_type TEXT,                                -- store | item | category | global
    entity_id   TEXT,
    entity_name TEXT,
    metric_value NUMERIC,                            -- headline number (e.g. pct change)
    status      TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'acknowledged', 'resolved')),
    -- tenant+rule+entity+time-window: upsert target so re-runs UPDATE rather than
    -- pile up duplicates, and a new window yields a fresh finding.
    dedupe_key  TEXT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    resolved_by TEXT,
    UNIQUE (tenant_id, dedupe_key)
);

CREATE INDEX IF NOT EXISTS idx_findings_tenant_status
    ON findings (tenant_id, status, severity);
CREATE INDEX IF NOT EXISTS idx_findings_tenant_detected
    ON findings (tenant_id, detected_at DESC);

-- Tenant isolation (same pattern as migration 012): RLS keyed off the app.tenant_id GUC.
ALTER TABLE findings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON findings;
CREATE POLICY tenant_isolation ON findings
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

-- The Node worker connects as a writer; app_rw is the non-owner request-path role.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
        GRANT SELECT, INSERT, UPDATE ON findings TO app_rw;
        GRANT USAGE, SELECT ON SEQUENCE findings_id_seq TO app_rw;
    END IF;
END $$;

DO $$ BEGIN RAISE NOTICE 'findings table ready (diagnostics contract)'; END $$;
