-- 068 — E10-2 completion: tenant isolation-tier PROVISIONING control plane.
--
-- Before this, isolation.py recorded a tenant's tier and fail-closed 503'd anything
-- but `shared` — an anti-mis-sell guard, but no provisioning. This adds the missing
-- control plane: a governed lifecycle that tracks a tenant being moved onto isolated
-- infrastructure, plus the data-plane primitive for `dedicated_schema` (create a
-- private schema with the tenant's own copies of the core transactional tables).
--
-- HONEST SCOPE, proven and documented rather than glossed:
--   * `dedicated_schema` gives the tenant a private Postgres schema holding isolated
--     copies of the CORE TENANT TABLES (their rows are physically separate, not
--     commingled in the shared tables). Their session routes via search_path.
--   * A Postgres VIEW binds to the schema of its referenced tables AT CREATION time,
--     NOT at query time (verified). So the ~32 shared analytics views in `public`
--     would still read public data for a dedicated tenant. Replicating that whole
--     view/matview stack per tenant — and applying every future migration to every
--     tenant schema — is a larger data-plane project; it is NOT done here and is
--     called out in docs/product/ISOLATION_TIERS.md as the remaining step.
--   * `dedicated_db` (a fully separate database, built by the normal migrate job — no
--     view problem) is the operator-provisioned path; the control plane records and
--     governs it, the DB creation + per-tenant routing is an infra step (runbook).
--
-- The KEY behavioural change: a dedicated tier goes from "never servable (always
-- 503)" to "servable only once provisioning is recorded `active`", still failing
-- closed otherwise. isolation.py now consults this table, not just the flag.

BEGIN;

CREATE TABLE IF NOT EXISTS tenant_provisioning (
    id             SERIAL PRIMARY KEY,
    tenant_id      INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    tier           TEXT NOT NULL
                     CHECK (tier IN ('shared', 'dedicated_schema', 'dedicated_db')),
    -- Lifecycle: requested -> provisioning -> active | failed; active -> deprovisioning -> deprovraioned.
    status         TEXT NOT NULL DEFAULT 'requested'
                     CHECK (status IN ('requested', 'provisioning', 'active',
                                       'failed', 'deprovisioning', 'deprovisioned')),
    -- The provisioned target: schema name for dedicated_schema; a DB name/URL ref
    -- for dedicated_db (never the password — an env-var name, like the transports).
    schema_name    TEXT,
    db_ref         TEXT,
    error          TEXT,
    requested_by   TEXT,
    requested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    activated_at   TIMESTAMPTZ,
    deprovisioned_at TIMESTAMPTZ,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- One live provisioning record per tenant (a tenant is on exactly one tier).
    UNIQUE (tenant_id)
);

-- A failed provisioning must say why — a bare 'failed' is not actionable.
ALTER TABLE tenant_provisioning DROP CONSTRAINT IF EXISTS tenant_provisioning_failure_has_reason;
ALTER TABLE tenant_provisioning
    ADD CONSTRAINT tenant_provisioning_failure_has_reason
    CHECK (status <> 'failed' OR (error IS NOT NULL AND length(btrim(error)) > 0));

-- An active dedicated_schema must name its schema; an active dedicated_db its db_ref.
ALTER TABLE tenant_provisioning DROP CONSTRAINT IF EXISTS tenant_provisioning_active_has_target;
ALTER TABLE tenant_provisioning
    ADD CONSTRAINT tenant_provisioning_active_has_target
    CHECK (
        status <> 'active'
        OR tier = 'shared'
        OR (tier = 'dedicated_schema' AND schema_name IS NOT NULL)
        OR (tier = 'dedicated_db' AND db_ref IS NOT NULL)
    );

CREATE INDEX IF NOT EXISTS ix_tenant_provisioning_active
    ON tenant_provisioning (tenant_id)
    WHERE status = 'active';

-- Control-plane table: super-admin only, not tenant-scoped, so NO RLS policy (it
-- describes cross-tenant infrastructure state; access is gated in the route layer).

-- ---------------------------------------------------------------------------
-- Data-plane primitive: create a dedicated schema with the tenant's own copies
-- of the core transactional tables. LIKE ... INCLUDING ALL clones columns,
-- defaults, constraints and indexes. The clones carry tenant_id + are RLS-ready.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION provision_tenant_schema(p_tenant_id INTEGER)
RETURNS TEXT
LANGUAGE plpgsql AS $$
DECLARE
    v_schema TEXT := format('tenant_%s', p_tenant_id);
    v_tbl    TEXT;
    -- The tenant's own transactional/PII data. NOT the partitioned synthetic
    -- stream (demo-only) and NOT the shared reference/control tables.
    v_tables TEXT[] := ARRAY[
        'stores', 'items', 'suppliers', 'sales_historical', 'inventory',
        'purchase_orders', 'promotions', 'item_costs'
    ];
BEGIN
    EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I', v_schema);
    FOREACH v_tbl IN ARRAY v_tables LOOP
        -- Only clone tables that actually exist in public (schema evolves).
        IF to_regclass(format('public.%I', v_tbl)) IS NOT NULL
           AND to_regclass(format('%I.%I', v_schema, v_tbl)) IS NULL THEN
            EXECUTE format('CREATE TABLE %I.%I (LIKE public.%I INCLUDING ALL)',
                           v_schema, v_tbl, v_tbl);
        END IF;
    END LOOP;
    RETURN v_schema;
END $$;

CREATE OR REPLACE FUNCTION deprovision_tenant_schema(p_tenant_id INTEGER, p_force BOOLEAN DEFAULT FALSE)
RETURNS BOOLEAN
LANGUAGE plpgsql AS $$
DECLARE
    v_schema TEXT := format('tenant_%s', p_tenant_id);
BEGIN
    IF to_regclass(format('%I.stores', v_schema)) IS NULL AND NOT p_force THEN
        RETURN FALSE;  -- nothing to drop
    END IF;
    -- CASCADE drops the tenant's isolated tables. Guarded by the caller: only ever
    -- invoked for a tenant explicitly being deprovisioned.
    EXECUTE format('DROP SCHEMA IF EXISTS %I CASCADE', v_schema);
    RETURN TRUE;
END $$;

COMMIT;

DO $$ BEGIN
    RAISE NOTICE 'tenant provisioning control plane ready; dedicated tiers served only when status=active';
END $$;
