-- 010_multi_tenancy.sql
-- Multi-tenancy foundation (additive, backward-compatible).
--
-- Introduces a `tenants` table and stamps every existing account/data row with a
-- default "demo" tenant. NO row-level security yet (that lands in a later
-- migration once query scoping is wired), so the running app is unaffected:
-- tenant_id simply defaults to the demo tenant everywhere.

-- 1. Tenants table (plan + white-label + billing fields ready for later phases)
CREATE TABLE IF NOT EXISTS tenants (
    id SERIAL PRIMARY KEY,
    slug VARCHAR(63) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    plan VARCHAR(40) NOT NULL DEFAULT 'free',
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    -- white-label
    brand_name VARCHAR(200),
    logo_url TEXT,
    accent_color VARCHAR(20),
    -- billing linkage (populated in Phase 3)
    stripe_customer_id VARCHAR(120),
    stripe_subscription_id VARCHAR(120),
    trial_ends_at TIMESTAMP WITH TIME ZONE,
    settings JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Default tenant owns all existing seeded data (id pinned to 1)
INSERT INTO tenants (id, slug, name, plan, status, brand_name, accent_color)
VALUES (1, 'demo', 'Lulu Demo', 'enterprise', 'active', 'Lulu Demo', '#0f766e')
ON CONFLICT (id) DO NOTHING;

-- keep the serial sequence ahead of any pinned id
SELECT setval(pg_get_serial_sequence('tenants', 'id'), GREATEST((SELECT MAX(id) FROM tenants), 1));

-- 3. Stamp tenant_id on account + data tables, backfilling existing rows to the
--    demo tenant. NOT NULL DEFAULT 1 backfills automatically on Postgres.
DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['users', 'stores', 'items', 'sales_historical', 'sales_stream_raw']
    LOOP
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = t) THEN
            EXECUTE format(
                'ALTER TABLE %I ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id)',
                t
            );
            EXECUTE format('CREATE INDEX IF NOT EXISTS idx_%s_tenant ON %I(tenant_id)', t, t);
        END IF;
    END LOOP;
END $$;

DO $$ BEGIN RAISE NOTICE 'Multi-tenancy foundation applied (demo tenant = 1)'; END $$;
