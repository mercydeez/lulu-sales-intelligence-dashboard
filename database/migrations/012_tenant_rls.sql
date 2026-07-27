-- 012_tenant_rls.sql
-- Postgres Row-Level Security as defense-in-depth UNDER the application-layer
-- tenant scoping (B2). App-layer scoping (every read filters `tenant_id`) stays
-- the primary control; RLS is the backstop so a missed filter can't leak across
-- tenants.
--
-- Design (deliberately non-breaking for the current single-role setup):
--   * Each tenant table gets a policy keyed off the per-connection GUC
--     `app.tenant_id` (set by the app at the start of every DB session — see
--     services/database.py). `current_setting('app.tenant_id', true)` returns
--     NULL when unset; the policy then falls back to the demo tenant (1) so
--     existing tooling/migrations keep working.
--   * RLS is ENABLEd but NOT FORCEd here. The app currently connects as the
--     table owner, which bypasses non-forced RLS — so enabling policies cannot
--     break the running app. The commented block at the bottom shows how to make
--     it enforcing in production by running the app as a dedicated non-owner
--     role (`app_rw`), which is the correct hardening step.

-- ---------------------------------------------------------------------------
-- Helper: resolve the active tenant for the connection (GUC -> demo fallback).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS INTEGER AS $$
    SELECT COALESCE(NULLIF(current_setting('app.tenant_id', true), '')::int, 1);
$$ LANGUAGE sql STABLE;

-- ---------------------------------------------------------------------------
-- Enable RLS + add a tenant-isolation policy on every tenant-stamped table.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['users', 'stores', 'items', 'sales_historical', 'sales_stream_raw']
    LOOP
        IF EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = t AND column_name = 'tenant_id') THEN
            EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
            EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
            EXECUTE format(
                'CREATE POLICY tenant_isolation ON %I '
                'USING (tenant_id = current_tenant_id()) '
                'WITH CHECK (tenant_id = current_tenant_id())', t);
        END IF;
    END LOOP;
END $$;

-- ---------------------------------------------------------------------------
-- Production hardening (run manually with a DBA — intentionally NOT executed
-- here so the owner-connected dev/app stack is unaffected):
--
--   CREATE ROLE app_rw LOGIN PASSWORD '<set-me>';
--   GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_rw;
--   GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO app_rw;
--   -- Force RLS so even table-owner-like access is filtered:
--   ALTER TABLE users            FORCE ROW LEVEL SECURITY;
--   ALTER TABLE stores           FORCE ROW LEVEL SECURITY;
--   ALTER TABLE items            FORCE ROW LEVEL SECURITY;
--   ALTER TABLE sales_historical FORCE ROW LEVEL SECURITY;
--   ALTER TABLE sales_stream_raw FORCE ROW LEVEL SECURITY;
--   -- Point the app's DATABASE_URL at app_rw (a non-owner role) so policies bind.
-- ---------------------------------------------------------------------------

DO $$ BEGIN RAISE NOTICE 'Tenant RLS policies enabled (GUC app.tenant_id, demo fallback)'; END $$;
