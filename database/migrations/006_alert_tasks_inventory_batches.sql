-- =============================================================================
-- LULU HYPERMARKET UAE - ALERT TASKS & INVENTORY BATCHES
-- Migration 006: Phase 2.2 (inventory batches + expiry) and 2.3 (alerts as tasks)
-- =============================================================================

-- =============================================================================
-- INVENTORY BATCHES - expiry-tracked stock lots
-- =============================================================================

CREATE TABLE IF NOT EXISTS inventory_batches (
    id SERIAL PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id),
    item_id INTEGER NOT NULL REFERENCES items(id),

    batch_number VARCHAR(50) NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity >= 0),
    initial_quantity INTEGER NOT NULL CHECK (initial_quantity >= 0),

    received_date DATE NOT NULL DEFAULT CURRENT_DATE,
    expiry_date DATE,                          -- NULL = non-perishable
    unit_cost DECIMAL(10,2) DEFAULT 0,

    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'expired', 'sold_out', 'disposed')),

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT unique_store_item_batch UNIQUE (store_id, item_id, batch_number)
);

CREATE INDEX IF NOT EXISTS idx_batches_store_item ON inventory_batches(store_id, item_id);
CREATE INDEX IF NOT EXISTS idx_batches_expiry ON inventory_batches(expiry_date)
    WHERE status = 'active' AND expiry_date IS NOT NULL;

-- =============================================================================
-- ALERTS AS TASKS - assignment workflow + persisted-alert dedup
-- =============================================================================

ALTER TABLE alerts ADD COLUMN IF NOT EXISTS assigned_to INTEGER REFERENCES users(id);
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS assigned_by INTEGER REFERENCES users(id);
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS assigned_at TIMESTAMP WITH TIME ZONE;

-- Stable identity for generated alerts so re-detection doesn't duplicate
-- open alerts; once resolved, the same condition may open a fresh alert.
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS dedupe_key VARCHAR(255);

CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_dedupe_open
    ON alerts(dedupe_key)
    WHERE status IN ('active', 'acknowledged') AND dedupe_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_alerts_assigned_to ON alerts(assigned_to)
    WHERE assigned_to IS NOT NULL;

-- New alert type for batch expiry (usable after this transaction commits)
ALTER TYPE alert_type ADD VALUE IF NOT EXISTS 'expiry_risk';

-- =============================================================================
-- SEED DEMO BATCHES from existing inventory rows (deterministic pseudo-random
-- so every fresh boot shows populated expiry screens, including some lots
-- expiring within days)
-- =============================================================================

-- Batch 1: the older lot — for perishable-ish variety, ~1 in 4 item/store
-- pairs gets a near-term expiry (0-9 days out), the rest 10-90 days.
INSERT INTO inventory_batches
    (store_id, item_id, batch_number, quantity, initial_quantity,
     received_date, expiry_date, unit_cost, status)
SELECT
    inv.store_id,
    inv.item_id,
    'B-' || inv.store_id || '-' || inv.item_id || '-001',
    GREATEST(inv.current_stock / 3, 5),
    GREATEST(inv.current_stock / 2, 10),
    CURRENT_DATE - ((inv.store_id * 7 + inv.item_id * 3) % 21 + 7),
    CASE
        WHEN (inv.store_id + inv.item_id) % 4 = 0
            THEN CURRENT_DATE + ((inv.store_id * 5 + inv.item_id) % 10)
        ELSE CURRENT_DATE + ((inv.store_id * 11 + inv.item_id * 7) % 81 + 10)
    END,
    COALESCE(NULLIF(inv.unit_cost, 0), 20.0),
    'active'
FROM inventory inv
ON CONFLICT (store_id, item_id, batch_number) DO NOTHING;

-- Batch 2: the fresher lot — received recently, longer-dated.
INSERT INTO inventory_batches
    (store_id, item_id, batch_number, quantity, initial_quantity,
     received_date, expiry_date, unit_cost, status)
SELECT
    inv.store_id,
    inv.item_id,
    'B-' || inv.store_id || '-' || inv.item_id || '-002',
    GREATEST(inv.current_stock - inv.current_stock / 3, 10),
    GREATEST(inv.current_stock, 20),
    CURRENT_DATE - ((inv.store_id * 3 + inv.item_id) % 7),
    CURRENT_DATE + ((inv.store_id * 13 + inv.item_id * 17) % 60 + 30),
    COALESCE(NULLIF(inv.unit_cost, 0), 20.0),
    'active'
FROM inventory inv
ON CONFLICT (store_id, item_id, batch_number) DO NOTHING;
