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

-- Retire the legacy table. CASCADE removes its RLS policies and indexes.
-- Nothing reads or writes it anymore (readers -> view, generator -> stream_raw),
-- and the view does not depend on it.
DROP TABLE IF EXISTS sales CASCADE;
