-- 018_supplier_invoices.sql
-- Supplier invoices + the basis for a 3-way match (Part III-E). Records the
-- supplier's invoice against a PO; matching compares the three legs — ORDERED
-- (PO lines) vs RECEIVED (goods receipts) vs INVOICED (these lines) — and flags
-- quantity/price variances. Strictly a system of record: no payment movement.

CREATE TABLE IF NOT EXISTS supplier_invoices (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    po_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    invoice_number VARCHAR(60) NOT NULL,
    invoice_amount NUMERIC(14,2) NOT NULL DEFAULT 0,
    currency VARCHAR(8) NOT NULL DEFAULT 'AED',
    -- received -> matched | exception ; matched -> approved_for_payment
    status VARCHAR(24) NOT NULL DEFAULT 'received',
    match_status VARCHAR(16),                         -- matched | exception | null
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_invoice_number UNIQUE (tenant_id, invoice_number)
);
CREATE INDEX IF NOT EXISTS idx_supplier_invoices_tenant ON supplier_invoices(tenant_id);
CREATE INDEX IF NOT EXISTS idx_supplier_invoices_po ON supplier_invoices(po_id);

CREATE TABLE IF NOT EXISTS supplier_invoice_lines (
    id SERIAL PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES supplier_invoices(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL,
    unit_cost NUMERIC(12,2) NOT NULL DEFAULT 0,
    line_total NUMERIC(14,2) NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_invoice_lines_invoice ON supplier_invoice_lines(invoice_id);

ALTER TABLE supplier_invoices ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON supplier_invoices;
CREATE POLICY tenant_isolation ON supplier_invoices
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

DO $$ BEGIN RAISE NOTICE 'Supplier invoices ready (basis for 3-way match)'; END $$;
