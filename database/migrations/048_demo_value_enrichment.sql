-- =============================================================================
-- 048_demo_value_enrichment.sql  (Pilot-in-a-box)
-- Enriches the DEMO TENANT's inventory (tenant 1 = Meridian) so the /value (ROI)
-- screen tells a complete, believable AED story out of the box: unit cost (→ cash
-- at cost + GMROI), realistic last-sale dates, a handful of genuine stockouts and
-- a dead-stock tail. This is DEMO data on the demo tenant only (clearly labelled as
-- demo across the app) — NOT a claim about any real customer's numbers. Deterministic
-- + idempotent (re-running yields the same result).
-- =============================================================================

UPDATE inventory i SET
    -- 65% of retail = a realistic grocery cost (≈35% gross margin). Demo only.
    unit_cost = ROUND(it.unit_price_aed * 0.65, 2),
    -- Most rows sold recently; a deterministic ~1/11 tail hasn't sold in 75 days
    -- (dead stock); everything else within the last few days.
    last_sale_date = CASE
        WHEN ((i.store_id * 50 + i.item_id) % 11) = 0 THEN CURRENT_DATE - 75
        ELSE CURRENT_DATE - ((i.item_id % 6))
    END,
    -- A deterministic ~1/17 of moving items are currently OUT of stock → stockout
    -- opportunity-loss shows up in AED.
    current_stock = CASE
        WHEN ((i.store_id * 50 + i.item_id) % 17) = 0 AND i.average_daily_sales > 0 THEN 0
        ELSE i.current_stock
    END,
    updated_at = CURRENT_TIMESTAMP
FROM items it
WHERE it.id = i.item_id AND it.tenant_id = 1;

DO $$ BEGIN RAISE NOTICE 'demo value enrichment applied (tenant 1 inventory: cost + last_sale_date + stockouts)'; END $$;
