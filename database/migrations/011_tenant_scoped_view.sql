-- 011_tenant_scoped_view.sql
-- Expose tenant_id on the unified sales_fact_view so reads can be tenant-scoped.
-- CREATE OR REPLACE keeps the existing columns/order and appends tenant_id at the
-- end (the only shape Postgres allows for a view replace), so existing readers
-- are unaffected.

CREATE OR REPLACE VIEW sales_fact_view WITH (security_invoker = true) AS
SELECT
    id,
    date,
    store_id,
    item_id,
    sales,
    FALSE AS is_streaming,
    'historical'::text AS source,
    created_at,
    tenant_id
FROM sales_historical
UNION ALL
SELECT
    id + 1000000000 AS id,
    timestamp::date AS date,
    store_id,
    item_id,
    sales,
    TRUE AS is_streaming,
    'streaming'::text AS source,
    COALESCE(created_at, timestamp) AS created_at,
    tenant_id
FROM sales_stream_raw;

DO $$ BEGIN RAISE NOTICE 'sales_fact_view now exposes tenant_id'; END $$;
