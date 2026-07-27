-- 074_retention_orchestration.sql
-- Retention & Commercial Orchestration (vertical slice 1).
--
-- Adds the missing customer layer + campaign decisioning tables. Everything
-- else is REUSED, not duplicated:
--   * procurement  -> suppliers / product_suppliers / purchase_orders (016)
--   * approvals    -> approval_rules threshold (019)
--   * inventory    -> inventory / inventory_transactions / stock_transfers (002)
--   * cost/margin  -> items.unit_price_aed (005) + item_costs / unit_cost_aed (058)
--
-- HONESTY: every customer + purchase row here is SYNTHETIC (is_synthetic=true,
-- archetype label kept on the row). Seed is fully deterministic — no random():
-- dates/items/flags derive from modular arithmetic over the row number, so
-- repeated seeds and repeated environments produce identical data.
--
-- Money is NUMERIC end-to-end. Idempotent: IF NOT EXISTS / guarded seed.

-- ---------------------------------------------------------------------------
-- 1. customers — synthetic loyalty identity (opaque ref, no PII, no sensitive
--    attributes: archetype describes BEHAVIOUR only, never demographics)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    customer_ref VARCHAR(40) NOT NULL,
    home_store_id INTEGER NOT NULL REFERENCES stores(id),
    archetype VARCHAR(30) NOT NULL,
    consent_marketing BOOLEAN NOT NULL DEFAULT TRUE,
    contact_cap_month INTEGER NOT NULL DEFAULT 4,
    contacts_this_month INTEGER NOT NULL DEFAULT 0,
    is_synthetic BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_customers_ref UNIQUE (tenant_id, customer_ref)
);
CREATE INDEX IF NOT EXISTS idx_customers_tenant ON customers(tenant_id);

COMMENT ON TABLE customers IS
    'Synthetic loyalty layer for the retention module. customer_ref is opaque '
    '(never PII); archetype is a behavioural label used for honest demo data, '
    'NEVER a decision feature on protected attributes.';

-- ---------------------------------------------------------------------------
-- 2. customer_purchases — event history feeding churn features. A PARALLEL
--    grain: never UNIONed into sales_fact_view (same rule as transactions,
--    ADR-010) so revenue is never double-counted.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customer_purchases (
    id BIGSERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    store_id INTEGER NOT NULL REFERENCES stores(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    purchase_date DATE NOT NULL,
    qty NUMERIC(10,3) NOT NULL DEFAULT 1,
    amount_aed NUMERIC(12,2) NOT NULL,
    was_promo BOOLEAN NOT NULL DEFAULT FALSE,
    is_return BOOLEAN NOT NULL DEFAULT FALSE,
    is_synthetic BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_customer_purchases_scan
    ON customer_purchases(tenant_id, customer_id, purchase_date DESC);

-- ---------------------------------------------------------------------------
-- 3. retention_campaigns — the persisted state machine + budget position.
--    Budget invariants live HERE as CHECK constraints (DB is the source of
--    truth); the service additionally uses FOR UPDATE + guarded UPDATEs.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS retention_campaigns (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    objective VARCHAR(40) NOT NULL DEFAULT 'churn_retention',
    -- draft -> audience_ready -> simulated -> pending_approval -> approved
    --   -> active <-> paused -> completed -> measured ; cancelled from any
    -- pre-completion state. Transitions validated by retention_service.
    status VARCHAR(30) NOT NULL DEFAULT 'draft',
    paused_reason TEXT,
    store_id INTEGER NOT NULL REFERENCES stores(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    starts_on DATE NOT NULL,
    ends_on DATE NOT NULL,
    max_discount_pct NUMERIC(5,2) NOT NULL DEFAULT 15,
    min_margin_pct NUMERIC(5,2) NOT NULL DEFAULT 10,
    discount_budget_aed NUMERIC(14,2) NOT NULL,
    budget_reserved_aed NUMERIC(14,2) NOT NULL DEFAULT 0,
    budget_spent_aed NUMERIC(14,2) NOT NULL DEFAULT 0,
    control_pct NUMERIC(5,2) NOT NULL DEFAULT 10,
    churn_threshold NUMERIC(4,3) NOT NULL DEFAULT 0.5,
    safety_stock_units INTEGER NOT NULL DEFAULT 20,
    contact_cap_month INTEGER NOT NULL DEFAULT 4,
    simulation JSONB,
    model_version VARCHAR(40),
    policy_version VARCHAR(40) NOT NULL DEFAULT 'policy_v1',
    requisition_po_id INTEGER REFERENCES purchase_orders(id) ON DELETE SET NULL,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    approved_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    approved_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_retention_dates CHECK (ends_on >= starts_on),
    CONSTRAINT ck_retention_budget_nonneg
        CHECK (discount_budget_aed >= 0 AND budget_reserved_aed >= 0 AND budget_spent_aed >= 0),
    CONSTRAINT ck_retention_spend_within_budget
        CHECK (budget_spent_aed <= discount_budget_aed)
);
CREATE INDEX IF NOT EXISTS idx_retention_campaigns_tenant ON retention_campaigns(tenant_id);

-- ---------------------------------------------------------------------------
-- 4. campaign_offers — audience row + decision + offer, one per customer.
--    The full decision trace (scores, snapshots, reason codes) lives on the
--    row so every action is reproducible after prices change.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS campaign_offers (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    campaign_id INTEGER NOT NULL REFERENCES retention_campaigns(id) ON DELETE CASCADE,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    store_id INTEGER NOT NULL REFERENCES stores(id),
    cohort VARCHAR(10) NOT NULL CHECK (cohort IN ('treatment', 'control')),
    churn_score NUMERIC(4,3) NOT NULL,
    response_prob NUMERIC(4,3) NOT NULL DEFAULT 0,
    action VARCHAR(30) NOT NULL DEFAULT 'NO_ACTION',
    item_id INTEGER REFERENCES items(id),
    discount_pct NUMERIC(5,2) NOT NULL DEFAULT 0,
    unit_price_aed NUMERIC(12,2),          -- price snapshot at decision time
    unit_cost_aed NUMERIC(12,4),           -- cost snapshot at decision time
    expected_value_aed NUMERIC(12,2) NOT NULL DEFAULT 0,
    reason_codes JSONB NOT NULL DEFAULT '[]',
    status VARCHAR(20) NOT NULL DEFAULT 'planned'
        CHECK (status IN ('planned', 'issued', 'redeemed', 'expired', 'suppressed')),
    issued_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE,
    redeemed_at TIMESTAMP WITH TIME ZONE,
    redemption_key VARCHAR(80),
    redemption_amount_aed NUMERIC(12,2),
    CONSTRAINT uq_offer_campaign_customer UNIQUE (campaign_id, customer_id),
    -- Idempotency: a redemption key can be consumed exactly once per tenant.
    CONSTRAINT uq_offer_redemption_key UNIQUE (tenant_id, redemption_key)
);
CREATE INDEX IF NOT EXISTS idx_campaign_offers_campaign ON campaign_offers(campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaign_offers_customer ON campaign_offers(tenant_id, customer_id);

-- ---------------------------------------------------------------------------
-- 5. campaign_allocations — SOFT inventory allocation during planning. Hard
--    stock truth stays in `inventory`; redemption decrements both under lock.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS campaign_allocations (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    campaign_id INTEGER NOT NULL REFERENCES retention_campaigns(id) ON DELETE CASCADE,
    store_id INTEGER NOT NULL REFERENCES stores(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    allocated_units INTEGER NOT NULL CHECK (allocated_units >= 0),
    consumed_units INTEGER NOT NULL DEFAULT 0,
    released_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_alloc_consumed CHECK (consumed_units >= 0 AND consumed_units <= allocated_units),
    CONSTRAINT uq_alloc UNIQUE (campaign_id, store_id, item_id)
);
CREATE INDEX IF NOT EXISTS idx_campaign_allocations_tenant ON campaign_allocations(tenant_id);

-- ---------------------------------------------------------------------------
-- 6. retention_budget_ledger — append-only money trail. Every reserve /
--    release / spend writes before+after balances. NUMERIC only.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS retention_budget_ledger (
    id BIGSERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    campaign_id INTEGER NOT NULL REFERENCES retention_campaigns(id) ON DELETE CASCADE,
    entry_type VARCHAR(20) NOT NULL CHECK (entry_type IN ('reserve', 'release', 'spend')),
    amount_aed NUMERIC(14,2) NOT NULL,
    balance_before_aed NUMERIC(14,2) NOT NULL,   -- remaining (budget - spent) before
    balance_after_aed NUMERIC(14,2) NOT NULL,
    currency VARCHAR(8) NOT NULL DEFAULT 'AED',
    source_type VARCHAR(30) NOT NULL,            -- 'campaign' | 'redemption'
    source_id INTEGER,
    idempotency_key VARCHAR(80),
    actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_retention_ledger_campaign
    ON retention_budget_ledger(tenant_id, campaign_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- 7. retention_events — audit timeline, same shape as procurement_events.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS retention_events (
    id BIGSERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    entity_type VARCHAR(30) NOT NULL,
    entity_id INTEGER,
    actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    summary TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_retention_events_scan
    ON retention_events(tenant_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- 8. RLS — tenant_isolation on every new table (pattern from 010-012).
-- ---------------------------------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'customers', 'customer_purchases', 'retention_campaigns',
        'campaign_offers', 'campaign_allocations',
        'retention_budget_ledger', 'retention_events']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I '
            'USING (tenant_id = current_tenant_id()) '
            'WITH CHECK (tenant_id = current_tenant_id())', t);
    END LOOP;
END $$;

-- ---------------------------------------------------------------------------
-- 9. DETERMINISTIC synthetic seed (tenant 1). No random(): every date, item,
--    and flag is modular arithmetic over the customer/purchase ordinal, so the
--    seed is byte-identical on every run and machine.
--
--    Archetype params: (archetype, n, recency_days, interval_days, n_purchases,
--                       qty, promo_mod, return_mod, consent, contacts_used)
--    promo_mod/return_mod: 0 = never; k -> every k-th purchase.
-- ---------------------------------------------------------------------------
INSERT INTO customers (tenant_id, customer_ref, home_store_id, archetype,
                       consent_marketing, contact_cap_month, contacts_this_month)
SELECT 1,
       'CUST-' || LPAD((ROW_NUMBER() OVER (ORDER BY a.ord, gs.n))::text, 4, '0'),
       st.ids[1 + (ROW_NUMBER() OVER (ORDER BY a.ord, gs.n))::int % array_length(st.ids, 1)],
       a.archetype, a.consent, 4, a.contacts_used
FROM (VALUES
    (1,  'loyal_active',     15, 3,  7,  26, TRUE,  0),
    (2,  'declining',        15, 25, 9,  12, TRUE,  0),
    (3,  'discount_hunter',  12, 10, 12, 10, TRUE,  0),
    (4,  'promo_resistant',  12, 8,  10, 12, TRUE,  0),
    (5,  'seasonal',         10, 40, 30, 6,  TRUE,  0),
    -- lapsed customers are seeded WITHOUT marketing consent: they are the
    -- highest-churn group, so the consent guard is visibly exercised.
    (6,  'lapsed',           15, 70, 10, 8,  FALSE, 0),
    (7,  'high_value',       10, 5,  6,  30, TRUE,  0),
    (8,  'high_returns',     8,  12, 10, 10, TRUE,  0),
    (9,  'near_contact_cap', 8,  15, 12, 8,  TRUE,  3),
    (10, 'category_churn',   10, 30, 8,  10, TRUE,  0)
) AS a(ord, archetype, n, recency, interval_days, n_purch, consent, contacts_used)
CROSS JOIN LATERAL generate_series(1, a.n) AS gs(n)
CROSS JOIN (SELECT array_agg(id ORDER BY id) AS ids FROM stores WHERE tenant_id = 1) st
-- Guard added: on a FRESH deploy the migrate job runs BEFORE the app seeder, so
-- tenant 1 has no stores yet and array_agg(...) is NULL. Indexing a NULL array
-- yields NULL home_store_id and the NOT NULL constraint aborts the whole
-- migration — this file could not be applied to a clean database at all.
-- Mirrors the guard already used on the tenant-2 block below.
WHERE EXISTS (SELECT 1 FROM stores WHERE tenant_id = 1)
  AND NOT EXISTS (SELECT 1 FROM customers WHERE tenant_id = 1);

-- Purchase histories: for customer c with archetype params, purchases at
-- CURRENT_DATE - recency - k*interval for k in 0..n-1; the item cycles through
-- the tenant-1 catalog at stride 7 (co-prime with 50 items -> good spread).
INSERT INTO customer_purchases (tenant_id, customer_id, store_id, item_id,
                                purchase_date, qty, amount_aed, was_promo, is_return)
SELECT 1, c.id, c.home_store_id,
       it.ids[1 + (c.id * 7 + k.k) % array_length(it.ids, 1)],
       CURRENT_DATE - (p.recency + k.k * p.interval_days),
       CASE WHEN c.archetype = 'high_value' THEN 3 ELSE 1 END,
       ROUND((SELECT unit_price_aed FROM items
               WHERE id = it.ids[1 + (c.id * 7 + k.k) % array_length(it.ids, 1)])
             * CASE WHEN c.archetype = 'high_value' THEN 3 ELSE 1 END, 2),
       CASE WHEN p.promo_mod > 0 THEN (k.k % p.promo_mod = 0) ELSE FALSE END,
       CASE WHEN p.return_mod > 0 THEN (k.k % p.return_mod = 0) ELSE FALSE END
FROM customers c
JOIN (VALUES
    ('loyal_active',     3,  7,  26, 6, 0),
    ('declining',        25, 9,  12, 4, 0),
    ('discount_hunter',  10, 12, 10, 1, 0),
    ('promo_resistant',  8,  10, 12, 0, 0),
    ('seasonal',         40, 30, 6,  3, 0),
    ('lapsed',           70, 10, 8,  4, 0),
    ('high_value',       5,  6,  30, 8, 0),
    ('high_returns',     12, 10, 10, 4, 3),
    ('near_contact_cap', 15, 12, 8,  4, 0),
    ('category_churn',   30, 8,  10, 5, 0)
) AS p(archetype, recency, interval_days, n_purch, promo_mod, return_mod)
  ON p.archetype = c.archetype
CROSS JOIN LATERAL generate_series(0, p.n_purch - 1) AS k(k)
CROSS JOIN (SELECT array_agg(id ORDER BY id) AS ids FROM items WHERE tenant_id = 1) it
WHERE c.tenant_id = 1
  -- Same fresh-deploy guard: no tenant-1 items yet means no catalogue to
  -- cycle through, and the array index would be NULL.
  AND EXISTS (SELECT 1 FROM items WHERE tenant_id = 1)
  AND NOT EXISTS (SELECT 1 FROM customer_purchases WHERE tenant_id = 1);

-- Small tenant-2 cohort so tenant-isolation is demonstrable (guarded: only if
-- migration 013 seeded tenant-2 stores/items).
INSERT INTO customers (tenant_id, customer_ref, home_store_id, archetype)
SELECT 2, 'CUST-T2-' || LPAD(gs.n::text, 3, '0'),
       (SELECT MIN(id) FROM stores WHERE tenant_id = 2),
       'loyal_active'
FROM generate_series(1, 5) AS gs(n)
WHERE EXISTS (SELECT 1 FROM stores WHERE tenant_id = 2)
  AND NOT EXISTS (SELECT 1 FROM customers WHERE tenant_id = 2);

DO $$
DECLARE n1 INTEGER; n2 INTEGER;
BEGIN
    SELECT COUNT(*) INTO n1 FROM customers;
    SELECT COUNT(*) INTO n2 FROM customer_purchases;
    RAISE NOTICE 'Retention orchestration ready: % customers, % purchases (synthetic, deterministic)', n1, n2;
END $$;
