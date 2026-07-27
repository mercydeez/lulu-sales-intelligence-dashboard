-- =============================================================================
-- Migration 008: performance index for the hot sales-aggregation path
-- =============================================================================
-- The dashboard's inventory/analytics/alert queries all hit sales_fact_view
-- (sales_historical UNION ALL sales_stream_raw) with the shape:
--     WHERE date >= CURRENT_DATE - INTERVAL 'N days'
--     GROUP BY store_id, item_id          (and variants grouping by date)
--
-- EXPLAIN ANALYZE on that query showed the historical side (the 900k-row table)
-- using idx_sales_historical_date but then heap-scanning to fetch
-- store_id/item_id/sales for the aggregation. A covering index lets the planner
-- serve those columns from the index itself (index-only scan after VACUUM).
--
-- Plain CREATE INDEX (not CONCURRENTLY) because the migration runner executes
-- each script inside a transaction. IF NOT EXISTS keeps it idempotent.
--
-- NB: we intentionally do NOT add an index for the stream side's date filter.
-- The view exposes date as ("timestamp")::date, and a timestamptz->date cast is
-- only STABLE (timezone-dependent), not IMMUTABLE, so Postgres rejects it as an
-- index expression. sales_stream_raw already has idx_sales_stream_timestamp and
-- stays small at demo scale (~1 row / 10s), so its seq scan is cheap.

CREATE INDEX IF NOT EXISTS idx_sales_hist_date_store_item
    ON sales_historical (date, store_id, item_id) INCLUDE (sales);
