-- 031_data_sources_tenant.sql
-- Tenant-scope the connected data sources (M2). Previously global: any admin could
-- see/manage every tenant's external data-source configs. Add tenant_id (+ RLS),
-- backfill existing rows to the demo tenant, and let the app filter by tenant.

ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_data_sources_tenant ON data_sources (tenant_id);

-- RLS as defense in depth (same model as the other tenant tables).
ALTER TABLE data_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_sources FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON data_sources;
CREATE POLICY tenant_isolation ON data_sources
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON data_sources TO app_rw;

DO $$ BEGIN RAISE NOTICE 'data_sources now tenant-scoped (tenant_id + RLS)'; END $$;
