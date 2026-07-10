-- 059_krishna_transaction_grain.sql
-- E2-5 (P1): basket / transaction-grain schema — tables created, deliberately unfilled.
--
-- WHY:
--   Every sale in this system is a DAILY AGGREGATE: sales_historical / sales_stream_raw
--   hold (date, store, item, units). You cannot ask "what else was in the basket?",
--   "what time do returns spike?", "which register voids the most?", or "did this promo
--   cannibalise the item next to it?" — the grain simply does not carry the answers.
--   Shrink, promo cannibalisation and customer intelligence all need line grain.
--
--   The blueprint (docs/EXECUTION_BLUEPRINT_12M.md, E2-5) asks for the schema NOW so the
--   POS connector (E2-1) has somewhere to write, and so E10-8 (waste/expiry) has a
--   foundation — without blocking on either.
--
-- WHAT:
--   transactions       — one row per basket/receipt (header).
--   transaction_lines  — one row per scanned line. Negative qty = a return line,
--                        mirroring the negative-`sales` convention of the daily grain.
--
-- DELIBERATELY NOT DONE — no bridge into sales_fact_view.
--   The E2-1 connector will land daily aggregates in external_sales -> sales_rollup_daily.
--   If transactions ALSO fed sales_fact_view, every revenue number would double-count the
--   moment a real POS source connects. The daily grain stays the source of truth for
--   revenue; this is a parallel, finer grain. See ADR-010.
--
-- NAMING TRAP — three existing tables sound related and are NOT:
--   * inventory_transactions — stock movements (receipts/adjustments), not sales.
--   * employee_transactions  — synthetic per-employee demo rows; tenant-unscoped, no lines.
--   * basket_associations    — the OUTPUT of market-basket analysis (support/confidence),
--                              not its input.
--   Do not backfill this grain from any of them.
--
-- UNITS vs AED (CLAUDE.md): qty is UNITS (NUMERIC so weighed goods work — the daily grain's
-- INTEGER cannot express 0.750 kg). unit_price_aed / discount_aed / *_total_aed are AED.
-- Never render one as the other.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS / DROP POLICY IF EXISTS / guarded constraints.
-- Additive only — nothing existing changes shape.

-- ---------------------------------------------------------------------------
-- 1. transactions — the basket header
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transactions (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id),
    store_id            INTEGER NOT NULL REFERENCES stores(id),

    txn_time            TIMESTAMP WITH TIME ZONE NOT NULL,
    -- A plain column, not a generated cast: timestamptz::date is not IMMUTABLE, so it
    -- cannot be indexed or generated. The connector sets it from the store's local day.
    txn_date            DATE NOT NULL,

    -- Connector identity. UNIQUE(tenant, source, txn_ref) makes ingestion idempotent:
    -- replaying a POS export cannot duplicate a receipt.
    source              VARCHAR(40) NOT NULL DEFAULT 'pos',
    txn_ref             VARCHAR(120) NOT NULL,

    register_id         VARCHAR(40),
    cashier_employee_id INTEGER REFERENCES employees(id),   -- nullable: employees are seeded
    customer_ref        VARCHAR(80),                        -- opaque loyalty id; never PII
    payment_method      VARCHAR(30),

    -- voided / refunded are the loss-prevention wedge; they are NOT deletions.
    status              VARCHAR(20) NOT NULL DEFAULT 'completed'
                        CHECK (status IN ('completed', 'voided', 'refunded')),

    total_aed           NUMERIC(12, 2) NOT NULL DEFAULT 0,
    discount_total_aed  NUMERIC(12, 2) NOT NULL DEFAULT 0,
    tax_total_aed       NUMERIC(12, 2),

    -- E0-8 provenance convention: anything fabricated says so.
    is_synthetic        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE transactions IS
    'E2-5 basket grain (header). Created unfilled; the POS connector (E2-1) writes here '
    'where the source supports line detail. Revenue stays sourced from the DAILY grain '
    '(sales_fact_view / sales_rollup_daily) — this is a parallel grain, never UNIONed in, '
    'or a connected POS would double-count. See ADR-010. Unrelated to inventory_transactions, '
    'employee_transactions and basket_associations.';
COMMENT ON COLUMN transactions.customer_ref IS
    'Opaque loyalty/customer identifier from the POS. Never store PII here.';
COMMENT ON COLUMN transactions.txn_date IS
    'Store-local calendar day of txn_time. A plain column because timestamptz::date is not '
    'IMMUTABLE and so cannot be a generated/indexed expression.';

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_transactions_source_ref') THEN
        ALTER TABLE transactions ADD CONSTRAINT uq_transactions_source_ref
            UNIQUE (tenant_id, source, txn_ref);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_transactions_tenant ON transactions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_transactions_scan   ON transactions(tenant_id, store_id, txn_date);
CREATE INDEX IF NOT EXISTS idx_transactions_time   ON transactions(tenant_id, txn_time);

-- ---------------------------------------------------------------------------
-- 2. transaction_lines — what was actually scanned
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transaction_lines (
    id             BIGSERIAL PRIMARY KEY,
    transaction_id BIGINT NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    line_no        INTEGER NOT NULL,
    item_id        INTEGER NOT NULL REFERENCES items(id),

    -- UNITS. NUMERIC(10,3) so weighed goods (0.750 kg) are expressible; the daily
    -- grain's INTEGER cannot hold them. Negative = return line.
    qty            NUMERIC(10, 3) NOT NULL,

    unit_price_aed NUMERIC(10, 2) NOT NULL,          -- matches items.unit_price_aed
    discount_aed   NUMERIC(10, 2) NOT NULL DEFAULT 0,
    line_total_aed NUMERIC(12, 2) NOT NULL,

    -- The invariant, enforced rather than merely documented: a connector that computes
    -- the line total differently from the parts fails loudly instead of quietly skewing
    -- margin. Tolerance covers rounding at 2dp.
    CONSTRAINT ck_transaction_lines_total
        CHECK (ABS(line_total_aed - (qty * unit_price_aed - discount_aed)) <= 0.01)
);

COMMENT ON TABLE transaction_lines IS
    'E2-5 basket grain (lines). qty is UNITS (negative = return); *_aed columns are money. '
    'No tenant_id: scoped through its parent transaction, matching the house pattern used by '
    'purchase_order_lines / goods_receipt_lines / supplier_invoice_lines (migration 020).';

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_transaction_lines_line_no') THEN
        ALTER TABLE transaction_lines ADD CONSTRAINT uq_transaction_lines_line_no
            UNIQUE (transaction_id, line_no);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_transaction_lines_txn  ON transaction_lines(transaction_id);
CREATE INDEX IF NOT EXISTS idx_transaction_lines_item ON transaction_lines(item_id);

-- ---------------------------------------------------------------------------
-- 3. RLS — header by tenant_id, lines through the parent (migration 020 pattern)
-- ---------------------------------------------------------------------------
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON transactions;
CREATE POLICY tenant_isolation ON transactions
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

ALTER TABLE transaction_lines ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON transaction_lines;
CREATE POLICY tenant_isolation ON transaction_lines USING (
    EXISTS (SELECT 1 FROM transactions t
            WHERE t.id = transaction_id AND t.tenant_id = current_tenant_id()));

-- FORCE so even the table owner is filtered once USE_RLS_ROLE points at app_rw.
-- (The superuser app account still bypasses by design — see migration 020's header.)
ALTER TABLE transactions      FORCE ROW LEVEL SECURITY;
ALTER TABLE transaction_lines FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    RAISE NOTICE 'E2-5: transactions + transaction_lines created (empty). '
                 'Revenue still reads the daily grain — no bridge, by design (ADR-010).';
END $$;
