-- 061_krishna_diagnostic_metric_views.sql
-- E3-5: the SQL half of diagnostic rules 6-12.
--
-- WHY:
--   The worker had five rules. The blueprint asks for seven more — stockout,
--   dead-stock growth, forecast miss, price anomaly, supplier-late, category
--   share shift, zero-sales SKU — taking diagnostic depth from 5 to 12.
--
--   E6-1's rule stands: the worker computes NO metric math in JavaScript. Every
--   number a rule thresholds on is defined once, here, in a view that the Python
--   side can read too. That is what stops the two languages drifting on what
--   "revenue", "share" or "dead stock" means.
--
-- HOUSE STYLE (copied from 050/058):
--   * tenant_id is a COLUMN, not a current_tenant_id() self-filter — the worker
--     runs as BYPASSRLS and scopes with `WHERE tenant_id = $1`.
--   * security_invoker = true, so RLS follows the caller for the app.
--   * GRANT SELECT to worker_rw + app_rw.
--
-- NOTES ON THE DATA WE ACTUALLY HAVE (no invented sources):
--   * `inventory` carries no tenant_id — it is scoped through stores.
--   * There is no stock-level history table, so "stockout days streak" cannot be
--     computed. metric_inventory_state reports what IS knowable: currently out of
--     stock, and how long since the item last sold. We measure what exists.
--   * There is no forecast table. The app's declared baseline is seasonal-naive
--     (the same weekday a week earlier), which is exactly computable in SQL — so
--     metric_forecast_miss scores against that, rather than pretending to invoke
--     the Python model.
--   * purchase_orders has no expected_delivery_date; "overdue" is derived as
--     sent_at + the supplier's lead time.
--   * transactions/transaction_lines (059) are deliberately EMPTY. No rule reads them.
--
-- Idempotent: CREATE OR REPLACE VIEW + ALTER + GRANT. Additive only.

-- ---------------------------------------------------------------------------
-- 6. Inventory state — stockouts and staleness (what a snapshot CAN tell us)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW metric_inventory_state AS
SELECT
    st.tenant_id,
    inv.store_id,
    st.name                                   AS store_name,
    inv.item_id,
    it.name                                   AS item_name,
    it.category,
    inv.current_stock,
    inv.reorder_point,
    inv.average_daily_sales,
    inv.last_sale_date,
    (inv.current_stock * it.unit_price_aed)   AS stock_retail_aed,
    (CURRENT_DATE - inv.last_sale_date)       AS days_since_last_sale,
    (inv.current_stock <= 0)                  AS is_out_of_stock,
    (inv.current_stock > 0 AND inv.current_stock <= inv.reorder_point) AS is_below_reorder
FROM inventory inv
JOIN stores st ON st.id = inv.store_id
JOIN items  it ON it.id = inv.item_id AND it.tenant_id = st.tenant_id;

ALTER VIEW metric_inventory_state SET (security_invoker = true);
COMMENT ON VIEW metric_inventory_state IS
    'E3-5: current stock posture per store-item. There is no stock-level history, so a '
    'true stockout-days streak is not derivable — days_since_last_sale is what the data supports.';

-- ---------------------------------------------------------------------------
-- 7. Dead stock, and whether it is GROWING (recent 30d vs the prior 30d)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW metric_dead_stock_growth AS
WITH sold AS (
    SELECT tenant_id, store_id, item_id,
           SUM(units) FILTER (WHERE date >= CURRENT_DATE - INTERVAL '30 days') AS units_recent,
           SUM(units) FILTER (WHERE date >= CURRENT_DATE - INTERVAL '60 days'
                                AND date <  CURRENT_DATE - INTERVAL '30 days') AS units_prior
      FROM metric_sales_fact
     WHERE date >= CURRENT_DATE - INTERVAL '60 days'
     GROUP BY tenant_id, store_id, item_id
)
SELECT
    s.tenant_id,
    COUNT(*) FILTER (WHERE COALESCE(sold.units_recent, 0) <= 0 AND s.current_stock > 0) AS dead_skus_recent,
    COUNT(*) FILTER (WHERE COALESCE(sold.units_prior, 0)  <= 0 AND s.current_stock > 0) AS dead_skus_prior,
    COALESCE(SUM(s.stock_retail_aed) FILTER (
        WHERE COALESCE(sold.units_recent, 0) <= 0 AND s.current_stock > 0), 0)          AS dead_value_recent_aed,
    COALESCE(SUM(s.stock_retail_aed) FILTER (
        WHERE COALESCE(sold.units_prior, 0)  <= 0 AND s.current_stock > 0), 0)          AS dead_value_prior_aed
FROM metric_inventory_state s
LEFT JOIN sold
       ON sold.tenant_id = s.tenant_id
      AND sold.store_id  = s.store_id
      AND sold.item_id   = s.item_id
GROUP BY s.tenant_id;

ALTER VIEW metric_dead_stock_growth SET (security_invoker = true);

-- ---------------------------------------------------------------------------
-- 8. Forecast miss vs the SEASONAL-NAIVE baseline (same weekday, a week earlier)
--    This is the app's own declared baseline (forecasting v2), so a "miss" here
--    means the same thing it means in the Forecast Lab.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW metric_forecast_miss AS
WITH daily AS (
    SELECT tenant_id, store_id, date, SUM(units) AS units
      FROM metric_sales_fact
     WHERE date >= CURRENT_DATE - INTERVAL '21 days'
     GROUP BY tenant_id, store_id, date
),
paired AS (
    SELECT d.tenant_id, d.store_id, d.date, d.units AS actual, b.units AS naive
      FROM daily d
      JOIN daily b ON b.tenant_id = d.tenant_id
                  AND b.store_id  = d.store_id
                  AND b.date      = d.date - 7
     WHERE d.date >= CURRENT_DATE - INTERVAL '7 days'
)
SELECT
    p.tenant_id,
    p.store_id,
    st.name                                             AS store_name,
    SUM(p.actual)                                       AS actual_units,
    SUM(p.naive)                                        AS naive_units,
    SUM(ABS(p.actual - p.naive))                        AS abs_error_units,
    -- WAPE against the naive baseline. NULL (never 0) when there is nothing to divide by.
    CASE WHEN SUM(p.actual) > 0
         THEN ROUND(SUM(ABS(p.actual - p.naive))::numeric / SUM(p.actual), 4)
    END                                                 AS wape,
    COUNT(*)                                            AS days_compared
FROM paired p
JOIN stores st ON st.id = p.store_id
GROUP BY p.tenant_id, p.store_id, st.name;

ALTER VIEW metric_forecast_miss SET (security_invoker = true);
COMMENT ON VIEW metric_forecast_miss IS
    'E3-5: WAPE of the last 7 days against the seasonal-naive (t-7) baseline the app '
    'publishes. wape is NULL, never 0, when there were no actual units to divide by.';

-- ---------------------------------------------------------------------------
-- 9. Price anomaly — selling at or below cost (E2-3 point-in-time cost)
--    Items with NO cost period are ABSENT, not zero: a reader must never infer
--    "no margin problem" from "no cost data".
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW metric_price_anomaly AS
SELECT
    m.tenant_id,
    m.item_id,
    i.name                                                       AS item_name,
    m.category,
    SUM(m.units)                                                 AS units_30d,
    ROUND(SUM(m.revenue_aed)::numeric, 2)                        AS revenue_30d_aed,
    ROUND(SUM(m.cogs_aed)::numeric, 2)                           AS cogs_30d_aed,
    ROUND(SUM(m.gross_margin_aed)::numeric, 2)                   AS margin_30d_aed,
    CASE WHEN SUM(m.revenue_aed) > 0
         THEN ROUND(SUM(m.gross_margin_aed)::numeric / SUM(m.revenue_aed), 4)
    END                                                          AS margin_ratio,
    MAX(m.unit_price_aed)                                        AS unit_price_aed,
    MAX(m.unit_cost_aed)                                         AS unit_cost_aed
FROM metric_margin_fact m
JOIN items i ON i.id = m.item_id AND i.tenant_id = m.tenant_id
WHERE m.date >= CURRENT_DATE - INTERVAL '30 days'
  AND m.cogs_aed IS NOT NULL          -- no cost period => not evaluated, not "fine"
  AND m.units > 0
GROUP BY m.tenant_id, m.item_id, i.name, m.category;

ALTER VIEW metric_price_anomaly SET (security_invoker = true);
COMMENT ON VIEW metric_price_anomaly IS
    'E3-5: 30d margin per item, only for items whose sales fall inside a cost period. '
    'Items without cost are ABSENT — never assume a missing row means a healthy margin.';

-- ---------------------------------------------------------------------------
-- 10. Supplier late — POs sent but not received past the supplier's lead time.
--     purchase_orders has no expected_delivery_date; it is derived.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW metric_supplier_overdue AS
SELECT
    po.tenant_id,
    po.supplier_id,
    sp.name                                                          AS supplier_name,
    COUNT(*)                                                         AS overdue_pos,
    ROUND(SUM(po.total_amount)::numeric, 2)                          AS overdue_value_aed,
    MAX((CURRENT_DATE - (po.sent_at::date + COALESCE(sp.lead_time_days, 7))))
                                                                     AS max_days_overdue,
    ROUND(AVG((CURRENT_DATE - (po.sent_at::date + COALESCE(sp.lead_time_days, 7))))::numeric, 1)
                                                                     AS avg_days_overdue
FROM purchase_orders po
JOIN suppliers sp ON sp.id = po.supplier_id
WHERE po.status IN ('sent', 'approved')
  AND po.sent_at IS NOT NULL
  AND (po.sent_at::date + COALESCE(sp.lead_time_days, 7)) < CURRENT_DATE
GROUP BY po.tenant_id, po.supplier_id, sp.name;

ALTER VIEW metric_supplier_overdue SET (security_invoker = true);

-- ---------------------------------------------------------------------------
-- 11. Category share shift — is a category losing its slice of the chain?
--     Share, not revenue: a category can grow and still be losing ground.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW metric_category_share AS
WITH windows AS (
    SELECT tenant_id, category,
           COALESCE(SUM(revenue_aed) FILTER (WHERE date >= CURRENT_DATE - INTERVAL '7 days'), 0) AS rev_recent,
           COALESCE(SUM(revenue_aed) FILTER (WHERE date >= CURRENT_DATE - INTERVAL '14 days'
                                               AND date <  CURRENT_DATE - INTERVAL '7 days'), 0) AS rev_prior
      FROM metric_sales_fact
     WHERE date >= CURRENT_DATE - INTERVAL '14 days' AND category IS NOT NULL
     GROUP BY tenant_id, category
),
totals AS (
    SELECT tenant_id, SUM(rev_recent) AS tot_recent, SUM(rev_prior) AS tot_prior
      FROM windows GROUP BY tenant_id
)
SELECT
    w.tenant_id,
    w.category,
    w.rev_recent,
    w.rev_prior,
    CASE WHEN t.tot_recent > 0 THEN ROUND((w.rev_recent / t.tot_recent)::numeric, 4) END AS share_recent,
    CASE WHEN t.tot_prior  > 0 THEN ROUND((w.rev_prior  / t.tot_prior )::numeric, 4) END AS share_prior,
    CASE WHEN t.tot_recent > 0 AND t.tot_prior > 0
         THEN ROUND(((w.rev_recent / t.tot_recent) - (w.rev_prior / t.tot_prior))::numeric * 100, 2)
    END                                                                                  AS shift_pp
FROM windows w
JOIN totals  t ON t.tenant_id = w.tenant_id;

ALTER VIEW metric_category_share SET (security_invoker = true);
COMMENT ON VIEW metric_category_share IS
    'E3-5: share of chain revenue, recent 7d vs prior 7d, in percentage POINTS (shift_pp). '
    'A category can grow in AED and still lose share.';

-- ---------------------------------------------------------------------------
-- 12. Zero-sales SKU — stock on the shelf, nothing sold in 30 days.
--     Disjoint from stockout by construction (current_stock > 0).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW metric_zero_sales_sku AS
SELECT
    s.tenant_id,
    s.store_id,
    s.store_name,
    s.item_id,
    s.item_name,
    s.category,
    s.current_stock,
    s.stock_retail_aed,
    s.days_since_last_sale
FROM metric_inventory_state s
WHERE s.current_stock > 0
  AND NOT EXISTS (
      SELECT 1 FROM metric_sales_fact m
       WHERE m.tenant_id = s.tenant_id
         AND m.store_id  = s.store_id
         AND m.item_id   = s.item_id
         AND m.date >= CURRENT_DATE - INTERVAL '30 days'
         AND m.units > 0
  );

ALTER VIEW metric_zero_sales_sku SET (security_invoker = true);

-- ---------------------------------------------------------------------------
-- Grants — the worker reads as the least-privilege worker_rw role (migration 029)
--
-- These views are security_invoker=true, so they execute with the CALLER's
-- privileges: granting the view alone is not enough, the caller also needs SELECT
-- on the base tables. worker_rw previously had SELECT on only
-- {stores, items, sales_*, findings, notifications}, so every new rule failed with
-- "permission denied for table inventory" and was swallowed by the per-rule catch.
--
-- Read-only, and the minimum the new rules touch. worker_rw already carries
-- BYPASSRLS by design (it scans every tenant and scopes with WHERE tenant_id = $1).
-- ---------------------------------------------------------------------------
GRANT SELECT ON inventory, purchase_orders, suppliers, item_costs TO worker_rw;

-- Migration 058 created metric_margin_fact but never granted it — the price-anomaly
-- rule (and any future margin reader) could not see it. Fixed here.
GRANT SELECT ON metric_margin_fact TO worker_rw, app_rw;

GRANT SELECT ON
    metric_inventory_state,
    metric_dead_stock_growth,
    metric_forecast_miss,
    metric_price_anomaly,
    metric_supplier_overdue,
    metric_category_share,
    metric_zero_sales_sku
TO worker_rw, app_rw;

DO $$ BEGIN
    RAISE NOTICE 'E3-5 metric views ready — rules 6-12 threshold and format, they compute nothing.';
END $$;
