-- =============================================================================
-- 047_import_jobs.sql  (CSV import — real-data ingestion for pilots)
-- History/audit of CSV imports a tenant has run. The actual data lands in the
-- canonical tables (stores/items/sales_historical/inventory); this records what
-- was imported, by whom, and with what result, so an operator can see and trust
-- the data pipeline. Tenant-scoped + RLS.
-- =============================================================================

CREATE TABLE IF NOT EXISTS import_jobs (
    id           SERIAL PRIMARY KEY,
    tenant_id    INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    import_type  TEXT NOT NULL,
    filename     TEXT,
    status       TEXT NOT NULL DEFAULT 'completed'
                   CHECK (status IN ('completed','partial','failed')),
    total_rows   INTEGER NOT NULL DEFAULT 0,
    imported_rows INTEGER NOT NULL DEFAULT 0,
    skipped_rows INTEGER NOT NULL DEFAULT 0,
    error_rows   INTEGER NOT NULL DEFAULT 0,
    mapping      JSONB NOT NULL DEFAULT '{}',
    notes        JSONB NOT NULL DEFAULT '{}',   -- sample skip reasons, etc.
    created_by   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_import_jobs_tenant ON import_jobs (tenant_id, created_at DESC);

ALTER TABLE import_jobs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON import_jobs;
CREATE POLICY tenant_isolation ON import_jobs
    USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());

DO $$ BEGIN RAISE NOTICE 'import_jobs: CSV import history ready (RLS on)'; END $$;
