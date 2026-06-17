-- =============================================================================
-- Migration 007: Unify sales storage onto the 3-tier design (GAP H1 / Phase 2.1)
-- =============================================================================
-- Single source of truth:
--   sales_historical  -> immutable CSV history
--   sales_stream_raw  -> append-only live events (generator writes here)
--   sales_fact_view   -> UNION the readers query
-- The legacy `sales` table is retired. This migration is idempotent and safe
-- to run on both fresh and existing databases.
--
-- The view is shaped as a drop-in for the old `sales` table (same columns:
-- id, date, store_id, item_id, sales, is_streaming, created_at) so the ORM
-- `Sale` model and all raw-SQL readers work unchanged. Streaming ids are
-- offset by 1,000,000,000 so ids stay unique across the union (the ORM
-- identity map would otherwise collapse colliding rows).
-- =============================================================================

CREATE OR REPLACE VIEW sales_fact_view AS
SELECT
    id,
    date,
    store_id,
    item_id,
    sales,
    FALSE AS is_streaming,
    'historical'::text AS source,
    created_at
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
    COALESCE(created_at, timestamp) AS created_at
FROM sales_stream_raw;

-- The analytics materialized views (migration 003) were defined on the legacy
-- `sales` table. Drop them, retire the table, then recreate them on the unified
-- view so fresh and existing databases converge on the same schema.
DROP MATERIALIZED VIEW IF EXISTS mv_daily_sales_by_store;
DROP MATERIALIZED VIEW IF EXISTS mv_weekly_sales_by_category;
DROP MATERIALIZED VIEW IF EXISTS mv_hourly_sales_pattern;

-- Retire the legacy table. CASCADE removes its RLS policies and indexes.
-- Nothing reads or writes it anymore (readers -> view, generator -> stream_raw),
-- and the view does not depend on it.
DROP TABLE IF EXISTS sales CASCADE;

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_daily_sales_by_store AS
SELECT
    date,
    store_id,
    COUNT(*) as transaction_count,
    SUM(CASE WHEN sales > 0 THEN sales ELSE 0 END) as total_sales,
    SUM(CASE WHEN sales < 0 THEN ABS(sales) ELSE 0 END) as total_returns,
    SUM(sales) as net_sales,
    AVG(sales) as avg_sale,
    COUNT(DISTINCT item_id) as unique_items
FROM sales_fact_view
GROUP BY date, store_id;
CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_daily_store ON mv_daily_sales_by_store(date, store_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_weekly_sales_by_category AS
SELECT
    DATE_TRUNC('week', s.date) as week_start,
    i.category,
    SUM(s.sales) as total_sales,
    COUNT(*) as transaction_count,
    COUNT(DISTINCT s.store_id) as stores_count
FROM sales_fact_view s
JOIN items i ON s.item_id = i.id
GROUP BY DATE_TRUNC('week', s.date), i.category;
CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_weekly_category ON mv_weekly_sales_by_category(week_start, category);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_hourly_sales_pattern AS
SELECT
    EXTRACT(DOW FROM created_at) as day_of_week,
    EXTRACT(HOUR FROM created_at) as hour_of_day,
    store_id,
    COUNT(*) as transaction_count,
    SUM(sales) as total_sales,
    AVG(sales) as avg_sales
FROM sales_fact_view
WHERE created_at >= CURRENT_DATE - INTERVAL '90 days'
GROUP BY EXTRACT(DOW FROM created_at), EXTRACT(HOUR FROM created_at), store_id;
CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_hourly_pattern ON mv_hourly_sales_pattern(day_of_week, hour_of_day, store_id);
