-- =============================================================================
-- Retail IQ — PRODUCTION database bootstrap (E0-4)
-- =============================================================================
-- Purpose: on a FRESH production Postgres volume, create the BASE SCHEMA that the
-- numbered migrations (database/migrations/00*.sql, applied by the `migrate`
-- service) build on top of — e.g. migration 001 does `ALTER TABLE stores ...`,
-- migration 007 unions `sales_historical` + `sales_stream_raw` into
-- `sales_fact_view`. Those tables must exist before the migrations run.
--
-- This is the SCHEMA-ONLY, production-safe counterpart of database/init.sql.
-- It DELIBERATELY contains NO demo/seed data:
--   * NO demo stores / items / prices / regions
--   * NO demo users (atharva/krishna/yash) or permissions
--   * NO train.csv import, NO synthetic sales, NO date-shifted history
-- Real tenant data is loaded through the product (CSV import / onboarding). The
-- first admin user is provisioned by the operator, NOT seeded here
-- (see docs/runbooks/DEPLOY_PIPELINE.md).
--
-- The structure mirrors database/init.sql exactly (minus the seed rows) so the
-- migrations apply identically in dev and production. All statements are
-- idempotent (IF NOT EXISTS / OR REPLACE / duplicate-object guards).
-- =============================================================================

-- --- Core sales schema -------------------------------------------------------
CREATE TABLE IF NOT EXISTS stores (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    location VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS items (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(50),
    unit_price_aed DECIMAL(10, 2) DEFAULT 10.00,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Immutable historical sales (bulk-loaded per tenant via the product, not here).
CREATE TABLE IF NOT EXISTS sales_historical (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    store_id INTEGER NOT NULL REFERENCES stores(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    sales INTEGER NOT NULL, -- allows negative values for returns
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Append-only streaming sales (UUID for dedup).
CREATE TABLE IF NOT EXISTS sales_stream_raw (
    id SERIAL PRIMARY KEY,
    event_id UUID NOT NULL UNIQUE,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    store_id INTEGER NOT NULL REFERENCES stores(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    sales INTEGER NOT NULL, -- allows negative values for returns
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS predictions (
    id SERIAL PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    prediction_date DATE NOT NULL,
    predicted_sales FLOAT NOT NULL,
    confidence_lower FLOAT,
    confidence_upper FLOAT,
    model_version VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(prediction_date, store_id, item_id)
);

CREATE INDEX IF NOT EXISTS idx_sales_historical_date ON sales_historical(date);
CREATE INDEX IF NOT EXISTS idx_sales_historical_store_item ON sales_historical(store_id, item_id);
CREATE INDEX IF NOT EXISTS idx_sales_stream_timestamp ON sales_stream_raw(timestamp);
CREATE INDEX IF NOT EXISTS idx_sales_stream_store_item ON sales_stream_raw(store_id, item_id);

-- tenant_id lives on the base tables so sales_fact_view can carry it (migration
-- 010 also adds it idempotently). Keeping it here makes re-runs safe.
ALTER TABLE sales_historical ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1;
ALTER TABLE sales_stream_raw  ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1;

CREATE OR REPLACE VIEW sales_fact_view AS
SELECT
    id, date, store_id, item_id, sales,
    FALSE AS is_streaming, 'historical'::text AS source, created_at, tenant_id
FROM sales_historical
UNION ALL
SELECT
    id + 1000000000 AS id, timestamp::date AS date, store_id, item_id, sales,
    TRUE AS is_streaming, 'streaming'::text AS source,
    COALESCE(created_at, timestamp) AS created_at, tenant_id
FROM sales_stream_raw;

-- --- Auth / RBAC schema ------------------------------------------------------
DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('super_admin', 'regional_manager', 'store_manager', 'analyst');
EXCEPTION WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE user_status AS ENUM ('active', 'inactive', 'locked', 'pending');
EXCEPTION WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS regions (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE stores ADD COLUMN IF NOT EXISTS region_id INTEGER REFERENCES regions(id);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    role user_role NOT NULL DEFAULT 'analyst',
    status user_status NOT NULL DEFAULT 'active',
    phone VARCHAR(20),
    job_title VARCHAR(100),
    department VARCHAR(100),
    failed_login_attempts INTEGER DEFAULT 0,
    locked_until TIMESTAMP WITH TIME ZONE,
    password_changed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    must_change_password BOOLEAN DEFAULT FALSE,
    two_factor_enabled BOOLEAN DEFAULT FALSE,
    two_factor_secret VARCHAR(100),
    last_login_at TIMESTAMP WITH TIME ZONE,
    last_login_ip VARCHAR(45),
    last_activity_at TIMESTAMP WITH TIME ZONE,
    preferences JSONB DEFAULT '{}',
    notification_settings JSONB DEFAULT '{"email": true, "in_app": true, "sms": false}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_permissions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    region_id INTEGER REFERENCES regions(id),
    store_id INTEGER REFERENCES stores(id),
    can_view BOOLEAN DEFAULT TRUE,
    can_edit BOOLEAN DEFAULT FALSE,
    can_delete BOOLEAN DEFAULT FALSE,
    can_export BOOLEAN DEFAULT FALSE,
    can_manage_users BOOLEAN DEFAULT FALSE,
    can_manage_inventory BOOLEAN DEFAULT FALSE,
    can_manage_promotions BOOLEAN DEFAULT FALSE,
    can_view_financials BOOLEAN DEFAULT FALSE,
    can_approve_transfers BOOLEAN DEFAULT FALSE,
    valid_from DATE DEFAULT CURRENT_DATE,
    valid_until DATE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    user_email VARCHAR(255),
    action VARCHAR(50) NOT NULL,
    resource_type VARCHAR(100),
    resource_id VARCHAR(100),
    description TEXT,
    old_values JSONB,
    new_values JSONB,
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_user_permissions_user ON user_permissions(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at DESC);

DO $$ BEGIN
    RAISE NOTICE 'prod-init: base schema ready (no demo/seed data). Migrations apply next.';
END $$;
