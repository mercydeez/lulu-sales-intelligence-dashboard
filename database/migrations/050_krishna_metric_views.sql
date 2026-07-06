-- 050_krishna_metric_views.sql
-- E6-1 (P0): canonical metric SQL views — ONE source of truth for the numbers.
--
-- WHY:
--   The same metric math lived in two languages: routes/kpis.py (Python) and
--   worker/src/rules.js (JavaScript) both hand-wrote `SUM(sales * unit_price_aed)`,
--   the 7-day-recent-vs-prior-7-day window, and the change ratio. Two definitions
--   of "AED revenue" and "week-over-week change" can silently drift. This migration
--   moves that arithmetic into shared views so kpis.py and the 5 worker rules become
--   thin readers that compute NO metric math — they only threshold and format.
--
--   The existing `sage_sales` view (023) already encodes revenue_aed but self-filters
--   by current_tenant_id() (a per-connection GUC the worker never sets), so it is not
--   reusable by the diagnostics worker. These metric_* views instead carry a tenant_id
--   COLUMN and let the caller scope with `WHERE tenant_id = $1`, matching how BOTH the
--   worker (app-layer loop, BYPASSRLS) and kpis.py (explicit tenant param) already work.
--
-- CONVENTIONS (kept identical to the code being replaced, so numbers are byte-for-byte):
--   * VALUE  = revenue_aed = units * unit_price_aed (numeric).  VOLUME = units (integer).
--   * All windows are rolling relative to CURRENT_DATE, exactly as the inline SQL.
--   * JOIN SURFACES mirror each original query so behaviour is preserved on real data:
--       - metric_sales_fact  joins items ONLY  (kpis totals + category/return-rate rules).
--       - metric_store_wow    joins stores      (store/laggard rules need store_name).
--       - metric_returns_wow  reads sales_fact_view DIRECTLY (returnSpike had no item join).
--   * security_invoker = true (021/026 house style: separate ALTER VIEW) so RLS on the
--     base tables follows the caller; app_rw stays tenant-scoped through the view while
--     the BYPASSRLS worker still scans every tenant via its own WHERE clause.
--
-- Idempotent: CREATE OR REPLACE VIEW + ALTER … SET; additive only (no drops/renames).

-- ---------------------------------------------------------------------------
-- Base: one row per sale, enriched with item price/category. THE revenue
-- definition. Items-only join on (id, tenant_id) — same surface kpis.py used
-- (JOIN items), but tenant-matched so per-tenant id reuse can never bleed a
-- price across tenants. Carries created_at / is_streaming for kpis.py.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW metric_sales_fact AS
SELECT
    s.tenant_id,
    s.id,
    s.date,
    s.created_at,
    s.is_streaming,
    s.store_id,
    s.item_id,
    i.category                    AS category,
    s.sales                       AS units,
    i.unit_price_aed              AS unit_price_aed,
    (s.sales * i.unit_price_aed)  AS revenue_aed,
    (s.sales < 0)                 AS is_return
FROM sales_fact_view s
JOIN items i ON i.id = s.item_id AND i.tenant_id = s.tenant_id;

ALTER VIEW metric_sales_fact SET (security_invoker = true);

-- ---------------------------------------------------------------------------
-- Per-store week-over-week revenue. Serves TWO rules from one definition:
--   revenue_drop  (change <= -0.15)  and  laggard_store (change < chain_avg - 0.05).
-- Joins stores for store_name — the surface the worker's store rules already used.
-- chain_avg_change is the tenant mean of `change`; because change is NULL when
-- rev_prior = 0 (NULLIF) and window AVG ignores NULLs, the average is taken over
-- exactly the stores with rev_prior > 0 — matching rules.js's old `WHERE rev_prior > 0`.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW metric_store_wow AS
WITH per_store AS (
    SELECT
        f.tenant_id, f.store_id, st.name AS store_name,
        COALESCE(SUM(f.revenue_aed) FILTER (
            WHERE f.date >= CURRENT_DATE - INTERVAL '7 days'), 0) AS rev_recent,
        COALESCE(SUM(f.revenue_aed) FILTER (
            WHERE f.date >= CURRENT_DATE - INTERVAL '14 days'
              AND f.date <  CURRENT_DATE - INTERVAL '7 days'), 0) AS rev_prior
    FROM metric_sales_fact f
    JOIN stores st ON st.id = f.store_id AND st.tenant_id = f.tenant_id
    GROUP BY f.tenant_id, f.store_id, st.name
)
SELECT
    tenant_id, store_id, store_name, rev_recent, rev_prior,
    (rev_recent - rev_prior) / NULLIF(rev_prior, 0) AS change,
    AVG((rev_recent - rev_prior) / NULLIF(rev_prior, 0))
        OVER (PARTITION BY tenant_id) AS chain_avg_change,
    AVG((rev_recent - rev_prior) / NULLIF(rev_prior, 0))
        OVER (PARTITION BY tenant_id)
      - (rev_recent - rev_prior) / NULLIF(rev_prior, 0) AS gap_pp
FROM per_store;

ALTER VIEW metric_store_wow SET (security_invoker = true);

-- ---------------------------------------------------------------------------
-- Per-category week-over-week revenue. Serves category_slump (change <= -0.2).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW metric_category_wow AS
WITH per_cat AS (
    SELECT
        tenant_id, category,
        COALESCE(SUM(revenue_aed) FILTER (
            WHERE date >= CURRENT_DATE - INTERVAL '7 days'), 0) AS rev_recent,
        COALESCE(SUM(revenue_aed) FILTER (
            WHERE date >= CURRENT_DATE - INTERVAL '14 days'
              AND date <  CURRENT_DATE - INTERVAL '7 days'), 0) AS rev_prior
    FROM metric_sales_fact
    GROUP BY tenant_id, category
)
SELECT
    tenant_id, category, rev_recent, rev_prior,
    (rev_recent - rev_prior) / NULLIF(rev_prior, 0) AS change
FROM per_cat;

ALTER VIEW metric_category_wow SET (security_invoker = true);

-- ---------------------------------------------------------------------------
-- Tenant-wide returned units, week-over-week. Serves return_spike; the noise
-- floor (recent >= 50) and trigger (change >= 0.4) stay as thresholds in the rule.
-- Reads sales_fact_view DIRECTLY (units only) — the original returnSpike joined
-- neither items nor stores, so returns are never dropped by a missing item row.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW metric_returns_wow AS
WITH r AS (
    SELECT
        tenant_id,
        COALESCE(SUM(ABS(sales)) FILTER (
            WHERE sales < 0 AND date >= CURRENT_DATE - INTERVAL '7 days'), 0) AS returns_recent_units,
        COALESCE(SUM(ABS(sales)) FILTER (
            WHERE sales < 0 AND date >= CURRENT_DATE - INTERVAL '14 days'
                           AND date <  CURRENT_DATE - INTERVAL '7 days'), 0) AS returns_prior_units
    FROM sales_fact_view
    GROUP BY tenant_id
)
SELECT
    tenant_id, returns_recent_units, returns_prior_units,
    -- ::numeric so this is a TRUE fraction. returned units are integer (bigint);
    -- without the cast this would be integer division and truncate every spike
    -- below +100% to 0, silently disabling the return_spike rule (E6-1 review catch).
    (returns_recent_units - returns_prior_units)::numeric
        / NULLIF(returns_prior_units, 0) AS change
FROM r;

ALTER VIEW metric_returns_wow SET (security_invoker = true);

-- ---------------------------------------------------------------------------
-- Per-category 30-day return rate + tenant mean. Serves high_return_rate
-- (rate > GREATEST(mean_rate * 1.5, 0.05)). mean_rate is the tenant window average
-- of rate; rate is NULL when gross_units = 0, so AVG(rate) OVER averages only the
-- categories with gross units — matching the old `WHERE gross_units > 0` before AVG.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW metric_category_return_rate AS
WITH c AS (
    SELECT
        tenant_id, category,
        COALESCE(SUM(units) FILTER (
            WHERE units > 0 AND date >= CURRENT_DATE - INTERVAL '30 days'), 0) AS gross_units,
        COALESCE(SUM(-units) FILTER (
            WHERE units < 0 AND date >= CURRENT_DATE - INTERVAL '30 days'), 0) AS return_units
    FROM metric_sales_fact
    GROUP BY tenant_id, category
), r AS (
    SELECT
        tenant_id, category, gross_units, return_units,
        return_units::numeric / NULLIF(gross_units, 0) AS rate
    FROM c
)
SELECT
    tenant_id, category, gross_units, return_units, rate,
    AVG(rate) OVER (PARTITION BY tenant_id) AS mean_rate
FROM r;

ALTER VIEW metric_category_return_rate SET (security_invoker = true);

-- ---------------------------------------------------------------------------
-- Grants. worker_rw (029) is NOT covered by app_rw's default privileges, so it
-- needs explicit SELECT; grant app_rw too so the RLS request path can read them.
-- security_invoker means both roles also rely on their existing SELECT on the
-- base relations (sales_fact_view/items/stores) — already granted in 020 and 029.
-- ---------------------------------------------------------------------------
GRANT SELECT ON
    metric_sales_fact,
    metric_store_wow,
    metric_category_wow,
    metric_returns_wow,
    metric_category_return_rate
TO worker_rw, app_rw;

DO $$ BEGIN
    RAISE NOTICE 'metric_* views ready (canonical revenue + WoW/returns; read by kpis.py and worker rules)';
END $$;
