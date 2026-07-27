-- 016_procurement.sql
-- Procure-to-pay system of RECORD (Part III-E) — the first "system of action"
-- rung. Turns the forecast-driven reorder suggestions (B1.7) into real, grouped
-- draft purchase orders that flow through approval. Money movement (invoice /
-- payment / 3-way match) is intentionally deferred — partner for that later.
--
-- Entities: Supplier, Product↔Supplier (cost / MOQ / lead time), PurchaseOrder,
-- PurchaseOrderLine. All tenant-scoped (app-layer + RLS).

-- 1. Suppliers --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS suppliers (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    contact_email VARCHAR(255),
    contact_phone VARCHAR(40),
    lead_time_days INTEGER NOT NULL DEFAULT 7,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_suppliers_tenant ON suppliers(tenant_id);

-- 2. Product ↔ Supplier (catalog: who supplies an item, at what cost/MOQ) ----
CREATE TABLE IF NOT EXISTS product_suppliers (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    unit_cost NUMERIC(12,2) NOT NULL DEFAULT 0,
    moq INTEGER NOT NULL DEFAULT 1,                 -- minimum order quantity
    lead_time_days INTEGER NOT NULL DEFAULT 7,
    is_preferred BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_product_supplier UNIQUE (tenant_id, item_id, supplier_id)
);
CREATE INDEX IF NOT EXISTS idx_product_suppliers_tenant ON product_suppliers(tenant_id);
CREATE INDEX IF NOT EXISTS idx_product_suppliers_item ON product_suppliers(item_id);

-- 3. Purchase orders --------------------------------------------------------
CREATE TABLE IF NOT EXISTS purchase_orders (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    po_number VARCHAR(40) NOT NULL,
    -- draft -> pending_approval -> approved -> sent -> received | cancelled
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    total_amount NUMERIC(14,2) NOT NULL DEFAULT 0,
    currency VARCHAR(8) NOT NULL DEFAULT 'AED',
    source VARCHAR(30) NOT NULL DEFAULT 'manual',   -- 'forecast_reorder' | 'manual'
    notes TEXT,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    approved_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    approved_at TIMESTAMP WITH TIME ZONE,
    sent_at TIMESTAMP WITH TIME ZONE,
    received_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT uq_po_number UNIQUE (tenant_id, po_number)
);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_tenant ON purchase_orders(tenant_id);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_supplier ON purchase_orders(supplier_id);

-- 4. Purchase order lines ---------------------------------------------------
CREATE TABLE IF NOT EXISTS purchase_order_lines (
    id SERIAL PRIMARY KEY,
    po_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL,
    unit_cost NUMERIC(12,2) NOT NULL DEFAULT 0,
    line_total NUMERIC(14,2) NOT NULL DEFAULT 0,
    days_of_cover NUMERIC(8,1),                      -- snapshot of the forecast signal
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_po_lines_po ON purchase_order_lines(po_id);

-- 5. RLS (defense-in-depth, same pattern as migration 012) ------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['suppliers', 'product_suppliers', 'purchase_orders']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I '
            'USING (tenant_id = current_tenant_id()) '
            'WITH CHECK (tenant_id = current_tenant_id())', t);
    END LOOP;
END $$;

-- 6. Demo seed: suppliers + product catalog for the demo tenant (id=1) so the
--    forecast → draft-PO flow works out of the box. New SERIAL ids only (no
--    explicit ids), so sequences stay correct.
INSERT INTO suppliers (tenant_id, name, contact_email, lead_time_days)
SELECT 1, v.name, v.email, v.lt
FROM (VALUES
    ('Gulf Wholesale Distributors', 'orders@gulfwholesale.ae', 5),
    ('Emirates Fresh Supply Co',    'sales@emiratesfresh.ae', 3),
    ('National Foods Trading',      'po@nationalfoods.ae',    7)
) AS v(name, email, lt)
WHERE NOT EXISTS (SELECT 1 FROM suppliers WHERE tenant_id = 1);

-- Link every demo item to one supplier (round-robin), wholesale cost ~60% of
-- retail, MOQ 50.
WITH sup AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY id) - 1 AS rn FROM suppliers WHERE tenant_id = 1
), n AS (SELECT GREATEST(COUNT(*), 1) AS c FROM sup)
INSERT INTO product_suppliers (tenant_id, item_id, supplier_id, unit_cost, moq, lead_time_days, is_preferred)
SELECT 1, i.id, sup.id, ROUND(i.unit_price_aed * 0.6, 2), 50, 7, TRUE
FROM items i
JOIN n ON TRUE
JOIN sup ON sup.rn = (i.id % n.c)
WHERE i.tenant_id = 1
  AND NOT EXISTS (SELECT 1 FROM product_suppliers WHERE tenant_id = 1);

DO $$ BEGIN RAISE NOTICE 'Procurement system-of-record ready (suppliers, catalog, POs)'; END $$;
