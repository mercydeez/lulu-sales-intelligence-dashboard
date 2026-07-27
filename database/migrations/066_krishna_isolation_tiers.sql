-- 066 — E10-2: record what isolation a tenant was actually sold.
--
-- Three tiers, in increasing separation:
--
--   shared         one database, one schema, separated by tenant_id + RLS.
--                  This is what the platform implements today.
--   dedicated_schema  one database, a schema per tenant.
--   dedicated_db      a database per tenant.
--
-- ONLY 'shared' IS IMPLEMENTED. The other two are recorded, not honoured, and
-- the application FAILS CLOSED for a tenant on a tier it cannot serve
-- (settings.supported_isolation_tiers, services/isolation.py). A tenant sold
-- dedicated-database isolation and quietly served from the shared pool is a
-- compliance lie that would survive right up until an auditor asked — refusing to
-- serve them is loud, immediate, and true.
--
-- The column therefore does not enable anything. It makes the promise explicit,
-- and makes breaking it impossible to do silently.

BEGIN;

ALTER TABLE tenants ADD COLUMN IF NOT EXISTS isolation_tier TEXT NOT NULL DEFAULT 'shared';

ALTER TABLE tenants DROP CONSTRAINT IF EXISTS tenants_isolation_tier_check;
ALTER TABLE tenants
    ADD CONSTRAINT tenants_isolation_tier_check
    CHECK (isolation_tier IN ('shared', 'dedicated_schema', 'dedicated_db'));

COMMENT ON COLUMN tenants.isolation_tier IS
    'Isolation the tenant was sold. Only ''shared'' is implemented; the app '
    'refuses to serve a tenant on any other tier rather than silently downgrade them.';

-- Every existing tenant is, in fact, shared. Say so.
UPDATE tenants SET isolation_tier = 'shared' WHERE isolation_tier IS NULL;

CREATE INDEX IF NOT EXISTS ix_tenants_isolation_tier
    ON tenants (isolation_tier)
    WHERE isolation_tier <> 'shared';

COMMIT;

DO $$ BEGIN
    RAISE NOTICE 'tenants.isolation_tier added; only shared is served, others fail closed';
END $$;
