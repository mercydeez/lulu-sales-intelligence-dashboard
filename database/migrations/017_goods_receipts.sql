-- 017_goods_receipts.sql
-- Goods receipt / receiving (Part III-E continued). When an approved PO is sent
-- and stock arrives, receiving records what actually came in — per line, partial
-- or full — moving the PO to 'partially_received' or 'received'. This is the
-- middle leg of the eventual 3-way match (ordered → received → invoiced).

-- Cumulative received quantity per PO line (drives partial/full status).
ALTER TABLE purchase_order_lines
    ADD COLUMN IF NOT EXISTS received_qty INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS goods_receipts (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    po_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    receipt_number VARCHAR(40) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'complete',   -- 'partial' | 'complete'
    received_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    notes TEXT,
    received_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_receipt_number UNIQUE (tenant_id, receipt_number)
);
CREATE INDEX IF NOT EXISTS idx_goods_receipts_tenant ON goods_receipts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_goods_receipts_po ON goods_receipts(po_id);

CREATE TABLE IF NOT EXISTS goods_receipt_lines (
    id SERIAL PRIMARY KEY,
    receipt_id INTEGER NOT NULL REFERENCES goods_receipts(id) ON DELETE CASCADE,
    po_line_id INTEGER NOT NULL REFERENCES purchase_order_lines(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    received_qty INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_receipt_lines_receipt ON goods_receipt_lines(receipt_id);

-- RLS on the tenant-scoped receipts table (lines inherit via po/receipt joins).
ALTER TABLE goods_receipts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON goods_receipts;
CREATE POLICY tenant_isolation ON goods_receipts
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

DO $$ BEGIN RAISE NOTICE 'Goods receipts ready (receiving against purchase orders)'; END $$;
