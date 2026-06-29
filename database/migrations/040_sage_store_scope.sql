-- 040_sage_store_scope.sql
-- Store-level RBAC for the Sage SQL path (Sage v3, Phase 1).
--
-- WHY: the sage_* views (migration 023) scope every row to the caller's TENANT
-- via current_tenant_id() / the app.tenant_id GUC, but NOT to the caller's
-- accessible STORES. A regional/store manager querying through Sage could read
-- every store in the tenant. Sage v3's invariant is that tenant_id, role AND
-- allowed_stores reach every SQL call and no node may widen scope.
--
-- HOW (mirrors the tenant GUC pattern): the executor sets a second per-connection
-- GUC `app.allowed_store_ids` (a Postgres int-array literal, e.g. '{3,4}'; empty
-- or unset => no restriction == super_admin / all stores in the tenant). The
-- sales grain view `sage_sales` and the store dimension `sage_stores` add a store
-- filter; because every other sales view (daily/store/category/item performance)
-- derives FROM sage_sales, they inherit the scoping automatically. Item-only
-- dimensions (sage_items) and the v2 domain views have no store_id and stay
-- tenant-scoped.
--
-- This is DB-enforced: even a guard bypass or a hand-written sage_ro query sees
-- only the permitted stores, exactly like RLS.

-- ---------------------------------------------------------------------------
-- Helper: the accessible-store allow-list for the connection (GUC -> NULL).
-- Returns NULL when the GUC is unset/empty/'{}' (meaning: no restriction).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION current_allowed_store_ids() RETURNS int[] AS $$
    SELECT CASE
        WHEN COALESCE(current_setting('app.allowed_store_ids', true), '') IN ('', '{}')
            THEN NULL
        ELSE string_to_array(
                 trim(both '{}' FROM current_setting('app.allowed_store_ids', true)),
                 ','
             )::int[]
    END;
$$ LANGUAGE sql STABLE;

-- A row's store is in scope when there is no restriction, or it is in the list.
CREATE OR REPLACE FUNCTION sage_store_in_scope(p_store_id int) RETURNS boolean AS $$
    SELECT current_allowed_store_ids() IS NULL
        OR p_store_id = ANY (current_allowed_store_ids());
$$ LANGUAGE sql STABLE;

-- ---------------------------------------------------------------------------
-- Re-create sage_sales with the store filter (columns/order UNCHANGED, so the
-- downstream aggregate views and the guard allow-list are unaffected).
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
WHERE s.tenant_id = current_tenant_id()
  AND sage_store_in_scope(s.store_id);

-- Store dimension: same store filter so a manager can't enumerate other stores.
-- Columns must match the current view EXACTLY (migration 028 added `zone`), since
-- CREATE OR REPLACE VIEW cannot add/drop/reorder columns.
CREATE OR REPLACE VIEW sage_stores AS
SELECT id AS store_id, name AS store_name, location, zone
FROM stores
WHERE tenant_id = current_tenant_id()
  AND sage_store_in_scope(id);

-- Preserve owner (definer) execution set in migration 023.
ALTER VIEW sage_sales  SET (security_invoker = false);
ALTER VIEW sage_stores SET (security_invoker = false);

DO $$ BEGIN RAISE NOTICE 'Sage store-level scoping (app.allowed_store_ids GUC) ready'; END $$;
