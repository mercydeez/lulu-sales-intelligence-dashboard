-- 020_force_rls_app_role.sql
-- Production RLS hardening (B2): a dedicated NON-OWNER application role (app_rw)
-- with FORCE ROW LEVEL SECURITY on every tenant table, so tenant isolation is
-- enforced by Postgres itself — not just the app layer.
--
-- Why this is safe for the running stack: the app currently connects as the
-- bootstrap superuser (salesuser), which BYPASSes RLS — so startup, migrations,
-- seeding, the data generator, and background warmers keep working unfiltered.
-- Point the app's request path at app_rw (a plain, non-superuser, non-owner
-- role) to turn enforcement on (services/database.py, USE_RLS_ROLE flag).
--
-- app_rw is filtered by the tenant_isolation policies keyed off the per-connection
-- `app.tenant_id` GUC (migration 012). With no GUC set it sees only the demo
-- tenant (current_tenant_id() falls back to 1).

-- 1. The non-owner application role -----------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
        -- Dev default password. In production it is overwritten automatically at
        -- migrate time from the password inside RLS_DATABASE_URL
        -- (backend/app/services/role_password_sync.py) — no manual ALTER ROLE.
        CREATE ROLE app_rw LOGIN PASSWORD 'app_rw_dev_pass';
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_rw;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_rw;
-- Future tables/sequences (created by later migrations) inherit the grants.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO app_rw;

-- 2. Policies on the remaining tenant-stamped tables (keys + webhooks) -------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['tenant_api_keys', 'tenant_webhooks']
    LOOP
        IF EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = t AND column_name = 'tenant_id') THEN
            EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
            EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
            EXECUTE format(
                'CREATE POLICY tenant_isolation ON %I '
                'USING (tenant_id = current_tenant_id()) '
                'WITH CHECK (tenant_id = current_tenant_id())', t);
        END IF;
    END LOOP;
END $$;

-- 3. Line tables have no tenant_id — scope them through their parent --------
ALTER TABLE purchase_order_lines ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON purchase_order_lines;
CREATE POLICY tenant_isolation ON purchase_order_lines USING (
    EXISTS (SELECT 1 FROM purchase_orders po
            WHERE po.id = po_id AND po.tenant_id = current_tenant_id()));

ALTER TABLE goods_receipt_lines ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON goods_receipt_lines;
CREATE POLICY tenant_isolation ON goods_receipt_lines USING (
    EXISTS (SELECT 1 FROM goods_receipts r
            WHERE r.id = receipt_id AND r.tenant_id = current_tenant_id()));

ALTER TABLE supplier_invoice_lines ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON supplier_invoice_lines;
CREATE POLICY tenant_isolation ON supplier_invoice_lines USING (
    EXISTS (SELECT 1 FROM supplier_invoices i
            WHERE i.id = invoice_id AND i.tenant_id = current_tenant_id()));

-- 4. FORCE RLS on every protected table so even a table owner is filtered ----
--    (The superuser app account still bypasses — that's intentional, see header.)
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'users', 'stores', 'items', 'sales_historical', 'sales_stream_raw',
        'suppliers', 'product_suppliers', 'purchase_orders', 'purchase_order_lines',
        'goods_receipts', 'goods_receipt_lines', 'supplier_invoices',
        'supplier_invoice_lines', 'approval_rules', 'tenant_api_keys', 'tenant_webhooks'
    ]
    LOOP
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = t) THEN
            EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        END IF;
    END LOOP;
END $$;

DO $$ BEGIN RAISE NOTICE 'FORCE RLS + app_rw non-owner role ready (point the app request path at app_rw to enforce)'; END $$;
