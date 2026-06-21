-- 023_risk_findings.sql
-- Proactive intelligence (Risk Radar): persisted, ranked, deduped risk findings.
-- The scan service (services/intelligence/risk_scans.py) upserts findings keyed
-- by (tenant_id, dedupe_key); the dashboard + Sage read the open ones by score.

CREATE TABLE IF NOT EXISTS risk_findings (
    id          SERIAL PRIMARY KEY,
    tenant_id   INTEGER NOT NULL DEFAULT 1,
    type        VARCHAR(50)  NOT NULL,   -- stockout_risk | demand_drop | return_spike | dead_stock
    severity    VARCHAR(20)  NOT NULL,   -- high | medium | low
    score       NUMERIC      NOT NULL DEFAULT 0,  -- ranking weight (higher = more urgent)
    title       TEXT         NOT NULL,
    detail      TEXT,
    store_id    INTEGER,
    item_id     INTEGER,
    metric      JSONB,                   -- supporting numbers for the UI
    dedupe_key  VARCHAR(200) NOT NULL,
    status      VARCHAR(20)  NOT NULL DEFAULT 'open',  -- open | resolved
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_risk_findings_dedupe
    ON risk_findings (tenant_id, dedupe_key);
CREATE INDEX IF NOT EXISTS ix_risk_findings_open
    ON risk_findings (tenant_id, status, score DESC);

-- RLS, mirroring the other tenant tables (keyed off the app.tenant_id GUC).
ALTER TABLE risk_findings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON risk_findings;
CREATE POLICY tenant_isolation ON risk_findings
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());
ALTER TABLE risk_findings FORCE ROW LEVEL SECURITY;

-- app_rw inherits table privileges via ALTER DEFAULT PRIVILEGES (migration 020),
-- but grant explicitly so this works even if 020 ran on an older database.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON risk_findings TO app_rw;
        GRANT USAGE, SELECT ON SEQUENCE risk_findings_id_seq TO app_rw;
    END IF;
END $$;

DO $$ BEGIN RAISE NOTICE 'risk_findings ready (RLS + FORCE)'; END $$;
