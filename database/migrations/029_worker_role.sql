-- 029_worker_role.sql
-- Least-privilege DB role for the diagnostics worker (P1 security hardening).
--
-- Before: the Node/BullMQ worker connected as the bootstrap SUPERUSER, so a bug
-- or compromise in worker code had read/write access to EVERY table — including
-- users and password_hash. In reality the worker only reads sales/items/stores
-- and writes the `findings` contract, scanning all tenants in a loop with
-- explicit `tenant_id = $1` app-layer scoping (worker/src/rules.js, findings.js).
--
-- worker_rw is a non-owner, non-superuser LOGIN role granted SELECT on exactly
-- the relations the rules read, plus SELECT/INSERT/UPDATE on `findings`. It
-- carries BYPASSRLS so the existing cross-tenant scan keeps working unchanged
-- (same trust model as the owner-path background jobs — tenant scoping is in the
-- worker's own WHERE clauses), but its TABLE surface is reduced to the
-- diagnostics domain: no users, credentials, procurement, API keys, webhooks.
-- Point the worker's WORKER_DATABASE_URL at this role.

-- 1. The role ---------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'worker_rw') THEN
        -- Dev default password; OVERRIDE in production: ALTER ROLE worker_rw PASSWORD '...'
        CREATE ROLE worker_rw LOGIN PASSWORD 'worker_rw_dev_pass' BYPASSRLS;
    ELSE
        -- Idempotent: ensure attributes AND the login password are present even if the
        -- role pre-existed. Setting the password only in the CREATE branch was a bug —
        -- a role created on an earlier volume took this ELSE path and was left WITHOUT a
        -- password, so the worker failed auth. Always (re)assert it. (Repaired on already
        -- migrated volumes by 035.)
        ALTER ROLE worker_rw LOGIN BYPASSRLS PASSWORD 'worker_rw_dev_pass';
    END IF;
END $$;

-- 2. Minimal grants ---------------------------------------------------------
GRANT USAGE ON SCHEMA public TO worker_rw;

-- Reads: the rules query sales_fact_view (security_invoker → the querying role
-- also needs SELECT on its base tables), joined to items + stores. listTenantIds
-- reads stores.
GRANT SELECT ON sales_fact_view, sales_historical, sales_stream_raw, items, stores TO worker_rw;

-- Writes: the `findings` table is the worker's ONLY output.
GRANT SELECT, INSERT, UPDATE ON findings TO worker_rw;
GRANT USAGE, SELECT ON SEQUENCE findings_id_seq TO worker_rw;

DO $$ BEGIN RAISE NOTICE 'worker_rw least-privilege role ready (reads sales/items/stores, writes findings only)'; END $$;
