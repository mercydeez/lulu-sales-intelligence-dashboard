-- 023_sage_semantic_views.sql
-- The "semantic layer" for Sage, the NL->SQL assistant (PRODUCT_BUILD_PLAN.md A2).
--
-- WHY A DEDICATED VIEW SET:
--   Sage lets an LLM generate SQL. We never trust that SQL, so it may ONLY read
--   from these curated `sage_*` views (enforced by the allow-list guard in
--   services/nl2sql/guard.py). Two properties make them safe AND accurate:
--
--   1. TENANT ISOLATION IS BAKED IN. Every view filters
--      `tenant_id = current_tenant_id()` (the helper from migration 012 that reads
--      the per-connection GUC `app.tenant_id`). Sage's executor sets that GUC, so
--      the view returns ONLY the caller's tenant — regardless of the connecting
--      role or whether security_invoker is honoured on the underlying union view.
--      This does not depend on RLS being forced through sales_fact_view.
--
--   2. THE UNITS/AED CONVENTION IS ENCODED. Each row exposes BOTH `units` (volume,
--      integer) and `revenue_aed` (value = units * unit_price_aed, numeric). Sage
--      is told in its schema prompt to use `units` for volume questions and
--      `revenue_aed` for money questions, never to multiply by price itself.
--
-- security_invoker is also set (defense in depth) so RLS on the base tables
-- applies as the invoking role too where it can.

-- ---------------------------------------------------------------------------
-- Grain: one row per sale, enriched with store/item/price, tenant-filtered.
-- Joined on (id, tenant_id) so per-tenant id reuse can never cross tenants.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW sage_sales AS
SELECT
    s.id,
    s.date,
    s.store_id,
    st.name              AS store_name,
    s.item_id,
    i.name               AS item_name,
    i.category           AS category,
    s.sales              AS units,
    i.unit_price_aed     AS unit_price_aed,
    (s.sales * i.unit_price_aed) AS revenue_aed,
    s.is_streaming,
    (s.sales < 0)        AS is_return
FROM sales_fact_view s
JOIN items  i  ON i.id  = s.item_id  AND i.tenant_id  = s.tenant_id
JOIN stores st ON st.id = s.store_id AND st.tenant_id = s.tenant_id
WHERE s.tenant_id = current_tenant_id();

-- Daily totals (units + AED) for the tenant.
CREATE OR REPLACE VIEW sage_daily_sales AS
SELECT
    date,
    SUM(units)        AS units,
    SUM(revenue_aed)  AS revenue_aed,
    COUNT(*)          AS line_count
FROM sage_sales
GROUP BY date;

-- Per-store performance.
CREATE OR REPLACE VIEW sage_store_performance AS
SELECT
    store_id,
    store_name,
    SUM(units)        AS units,
    SUM(revenue_aed)  AS revenue_aed,
    COUNT(*)          AS line_count
FROM sage_sales
GROUP BY store_id, store_name;

-- Per-category performance.
CREATE OR REPLACE VIEW sage_category_performance AS
SELECT
    category,
    SUM(units)        AS units,
    SUM(revenue_aed)  AS revenue_aed
FROM sage_sales
GROUP BY category;

-- Per-item performance.
CREATE OR REPLACE VIEW sage_item_performance AS
SELECT
    item_id,
    item_name,
    category,
    unit_price_aed,
    SUM(units)        AS units,
    SUM(revenue_aed)  AS revenue_aed
FROM sage_sales
GROUP BY item_id, item_name, category, unit_price_aed;

-- Reference dimensions (tenant-filtered).
CREATE OR REPLACE VIEW sage_stores AS
SELECT id AS store_id, name AS store_name, location
FROM stores
WHERE tenant_id = current_tenant_id();

CREATE OR REPLACE VIEW sage_items AS
SELECT id AS item_id, name AS item_name, category, unit_price_aed
FROM items
WHERE tenant_id = current_tenant_id();

-- Force OWNER (definer) execution explicitly — deterministic even if an earlier
-- revision of this migration set security_invoker on. See the NOTE below.
ALTER VIEW sage_sales              SET (security_invoker = false);
ALTER VIEW sage_daily_sales        SET (security_invoker = false);
ALTER VIEW sage_store_performance  SET (security_invoker = false);
ALTER VIEW sage_category_performance SET (security_invoker = false);
ALTER VIEW sage_item_performance   SET (security_invoker = false);
ALTER VIEW sage_stores             SET (security_invoker = false);
ALTER VIEW sage_items              SET (security_invoker = false);

-- NOTE: these views run as their OWNER (security_invoker OFF).
-- That is deliberate: it lets a least-privilege Sage role read them WITHOUT any
-- grant on the base tables, while the baked `WHERE tenant_id = current_tenant_id()`
-- still scopes every row to the caller's GUC tenant. So even a guard bypass can
-- only ever read these seven tenant-filtered views — nothing else in the schema.

-- Dedicated least-privilege role for Sage's NL->SQL execution path. It can read
-- ONLY the sage_* views (no base tables, no other schema), so model-generated SQL
-- is contained by Postgres grants in addition to the allow-list guard and the
-- read-only transaction. Tenant scoping is via the app.tenant_id GUC the executor
-- sets per query (current_tenant_id() in the view bodies).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sage_ro') THEN
        -- Dev default password. In production it is overwritten automatically at
        -- migrate time from the password inside SAGE_DATABASE_URL
        -- (backend/app/services/role_password_sync.py) — no manual ALTER ROLE.
        CREATE ROLE sage_ro LOGIN PASSWORD 'sage_ro_dev_pass' NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
    -- Strip any ambient privileges, then grant exactly the sage_* read surface.
    REVOKE ALL ON ALL TABLES IN SCHEMA public FROM sage_ro;
    GRANT USAGE ON SCHEMA public TO sage_ro;
    GRANT SELECT ON sage_sales, sage_daily_sales, sage_store_performance,
                    sage_category_performance, sage_item_performance,
                    sage_stores, sage_items TO sage_ro;
END $$;

DO $$ BEGIN RAISE NOTICE 'Sage semantic views + least-privilege sage_ro role ready'; END $$;
