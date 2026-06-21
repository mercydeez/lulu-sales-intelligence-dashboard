-- 013_seed_second_tenant.sql
-- A second, fully-isolated tenant ("Northwind Foods", id=2) so multi-tenant
-- isolation is visible end-to-end (B2): its own stores, items, ~120 days of
-- historical sales, and a super_admin login. Tenant 1 (Meridian Retail) and tenant 2
-- must never see each other's rows once every read is tenant-scoped + RLS is on.
--
-- Idempotent: each block self-guards on "does tenant 2 already have this?" so a
-- re-run (or a fresh volume that already seeded) is a no-op.

-- 1. Tenant row -------------------------------------------------------------
INSERT INTO tenants (id, slug, name, plan, status, brand_name, accent_color)
VALUES (2, 'northwind', 'Northwind Foods', 'pro', 'active', 'Northwind', '#7c3aed')
ON CONFLICT (id) DO NOTHING;
SELECT setval(pg_get_serial_sequence('tenants', 'id'), GREATEST((SELECT MAX(id) FROM tenants), 2));

-- The base data (stores/items/users/sales) is seeded with EXPLICIT ids, which
-- leaves their SERIAL sequences at 1. Advance each sequence past its max so the
-- SERIAL inserts below (and later app-side signups) don't collide on id=1.
SELECT setval(pg_get_serial_sequence('stores', 'id'), GREATEST((SELECT MAX(id) FROM stores), 1));
SELECT setval(pg_get_serial_sequence('items', 'id'), GREATEST((SELECT MAX(id) FROM items), 1));
SELECT setval(pg_get_serial_sequence('users', 'id'), GREATEST((SELECT MAX(id) FROM users), 1));
SELECT setval(pg_get_serial_sequence('sales_historical', 'id'), GREATEST((SELECT MAX(id) FROM sales_historical), 1));

-- 2. Stores (only if tenant 2 has none) -------------------------------------
INSERT INTO stores (name, location, tenant_id)
SELECT v.name, v.location, 2
FROM (VALUES
    ('Northwind Central', 'Abu Dhabi'),
    ('Northwind Marina', 'Dubai')
) AS v(name, location)
WHERE NOT EXISTS (SELECT 1 FROM stores WHERE tenant_id = 2);

-- 3. Items (only if tenant 2 has none) --------------------------------------
INSERT INTO items (name, category, unit_price_aed, tenant_id)
SELECT v.name, v.category, v.price, 2
FROM (VALUES
    ('NW Basmati Rice 5kg',   'Rice & Grains', 32.00),
    ('NW Olive Oil 1L',       'Condiments',    28.50),
    ('NW Fresh Milk 2L',      'Dairy',          9.75),
    ('NW Arabic Bread',       'Bakery',         4.25),
    ('NW Mineral Water 12pk', 'Beverages',     15.00),
    ('NW Chicken Breast 1kg', 'Meat & Poultry',24.00),
    ('NW Cheddar 500g',       'Dairy',         19.50),
    ('NW Dates 1kg',          'Snacks',        21.00)
) AS v(name, category, price)
WHERE NOT EXISTS (SELECT 1 FROM items WHERE tenant_id = 2);

-- 4. ~120 days of historical sales for every tenant-2 store × item ----------
--    Deterministic weekly seasonality + weekend bump + per-item base level so
--    the forecasting engine and inventory math have a realistic series.
INSERT INTO sales_historical (date, store_id, item_id, sales, tenant_id)
SELECT
    d::date,
    st.id,
    it.id,
    GREATEST(0, ROUND(
        (15 + (it.id % 7) * 6)                                    -- per-item base
        * (1 + 0.30 * sin(2 * pi() * EXTRACT(doy FROM d) / 7))    -- weekly cycle
        + CASE WHEN EXTRACT(dow FROM d) IN (5, 6)                 -- weekend bump
               THEN (15 + (it.id % 7) * 6) * 0.4 ELSE 0 END
    ))::int AS sales,
    2
FROM generate_series(
        CURRENT_DATE - INTERVAL '120 days',
        CURRENT_DATE - INTERVAL '1 day',
        INTERVAL '1 day'
     ) AS d
CROSS JOIN stores st
CROSS JOIN items it
WHERE st.tenant_id = 2
  AND it.tenant_id = 2
  AND NOT EXISTS (SELECT 1 FROM sales_historical WHERE tenant_id = 2);

-- 5. A super_admin login for tenant 2 (password: Demo@2026!) ----------------
INSERT INTO users (email, password_hash, first_name, last_name, role, status,
                   job_title, department, tenant_id)
VALUES (
    'owner@northwind.ae',
    '$2b$12$H5K0AMsU34kndvqz4reAkOOZ5QmINt67ZriaLAHJc5bCzK64SUv/i',
    'Nadia', 'Al Mansouri', 'super_admin', 'active',
    'Owner', 'Executive Leadership', 2
)
ON CONFLICT (email) DO NOTHING;

DO $$ BEGIN RAISE NOTICE 'Seeded tenant 2 (Northwind Foods): stores, items, sales, owner@northwind.ae'; END $$;
