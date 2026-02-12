-- =============================================================================
-- LULU HYPERMARKET UAE - INVENTORY MANAGEMENT SCHEMA
-- Migration 002: Inventory, Stock Levels, Transfers, Alerts
-- =============================================================================

-- =============================================================================
-- INVENTORY TABLE - Current Stock Levels
-- =============================================================================

CREATE TABLE IF NOT EXISTS inventory (
    id SERIAL PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    
    -- Stock levels
    current_stock INTEGER NOT NULL DEFAULT 0,
    reserved_stock INTEGER DEFAULT 0,  -- For pending orders
    available_stock INTEGER GENERATED ALWAYS AS (current_stock - COALESCE(reserved_stock, 0)) STORED,
    
    -- Reorder management
    reorder_point INTEGER DEFAULT 50,
    reorder_quantity INTEGER DEFAULT 100,
    max_stock_level INTEGER DEFAULT 500,
    
    -- ABC Classification
    abc_class CHAR(1) DEFAULT 'C' CHECK (abc_class IN ('A', 'B', 'C')),
    
    -- Cost tracking
    unit_cost DECIMAL(10,2) DEFAULT 0,
    total_value DECIMAL(12,2) GENERATED ALWAYS AS (current_stock * unit_cost) STORED,
    
    -- Analytics
    average_daily_sales DECIMAL(10,2) DEFAULT 0,
    days_of_supply DECIMAL(10,2) GENERATED ALWAYS AS (
        CASE WHEN average_daily_sales > 0 
        THEN current_stock / average_daily_sales 
        ELSE 999 END
    ) STORED,
    last_sale_date DATE,
    last_restock_date DATE,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT unique_store_item UNIQUE (store_id, item_id)
);

-- =============================================================================
-- INVENTORY TRANSACTIONS - Stock Movements
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE inventory_transaction_type AS ENUM (
        'sale', 'return', 'restock', 'transfer_in', 'transfer_out',
        'adjustment_positive', 'adjustment_negative', 'shrinkage', 'damage', 'expired'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS inventory_transactions (
    id BIGSERIAL PRIMARY KEY,
    inventory_id INTEGER NOT NULL REFERENCES inventory(id),
    store_id INTEGER NOT NULL REFERENCES stores(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    
    -- Transaction details
    transaction_type inventory_transaction_type NOT NULL,
    quantity INTEGER NOT NULL,  -- Positive for in, negative for out
    
    -- Stock levels at time of transaction
    stock_before INTEGER NOT NULL,
    stock_after INTEGER NOT NULL,
    
    -- Reference
    reference_type VARCHAR(50),  -- 'sale', 'transfer', 'po'
    reference_id VARCHAR(100),
    
    -- Cost tracking
    unit_cost DECIMAL(10,2),
    total_cost DECIMAL(12,2),
    
    -- Audit
    notes TEXT,
    performed_by INTEGER REFERENCES users(id),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- STOCK TRANSFERS - Between Stores
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE transfer_status AS ENUM ('pending', 'approved', 'in_transit', 'completed', 'cancelled');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS stock_transfers (
    id SERIAL PRIMARY KEY,
    transfer_number VARCHAR(50) UNIQUE NOT NULL,
    
    -- Source and destination
    from_store_id INTEGER NOT NULL REFERENCES stores(id),
    to_store_id INTEGER NOT NULL REFERENCES stores(id),
    
    -- Status
    status transfer_status DEFAULT 'pending',
    
    -- Approval workflow
    requested_by INTEGER NOT NULL REFERENCES users(id),
    requested_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    approved_by INTEGER REFERENCES users(id),
    approved_at TIMESTAMP WITH TIME ZONE,
    completed_by INTEGER REFERENCES users(id),
    completed_at TIMESTAMP WITH TIME ZONE,
    
    -- Notes
    reason TEXT,
    notes TEXT,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT different_stores CHECK (from_store_id != to_store_id)
);

CREATE TABLE IF NOT EXISTS stock_transfer_items (
    id SERIAL PRIMARY KEY,
    transfer_id INTEGER NOT NULL REFERENCES stock_transfers(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id),
    
    quantity_requested INTEGER NOT NULL,
    quantity_sent INTEGER,
    quantity_received INTEGER,
    
    unit_cost DECIMAL(10,2),
    
    notes TEXT,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- SHRINKAGE TRACKING
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE shrinkage_reason AS ENUM (
        'theft', 'damage', 'expired', 'administrative_error', 'vendor_fraud', 'unknown'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS shrinkage_records (
    id SERIAL PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    
    quantity INTEGER NOT NULL,
    unit_cost DECIMAL(10,2),
    total_loss DECIMAL(12,2),
    
    reason shrinkage_reason NOT NULL,
    description TEXT,
    
    -- Investigation
    investigated BOOLEAN DEFAULT FALSE,
    investigation_notes TEXT,
    investigated_by INTEGER REFERENCES users(id),
    
    -- Audit
    reported_by INTEGER NOT NULL REFERENCES users(id),
    reported_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- ALERTS TABLE
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE alert_type AS ENUM (
        'low_stock', 'stockout', 'overstock', 
        'sales_anomaly', 'returns_anomaly',
        'shrinkage_threshold', 'dead_stock',
        'forecast_deviation', 'system_health'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE alert_severity AS ENUM ('info', 'warning', 'critical');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE alert_status AS ENUM ('active', 'acknowledged', 'resolved', 'snoozed', 'expired');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS alerts (
    id SERIAL PRIMARY KEY,
    
    -- Alert classification
    alert_type alert_type NOT NULL,
    severity alert_severity NOT NULL DEFAULT 'warning',
    status alert_status NOT NULL DEFAULT 'active',
    
    -- Context
    store_id INTEGER REFERENCES stores(id),
    item_id INTEGER REFERENCES items(id),
    region_id INTEGER REFERENCES regions(id),
    
    -- Content
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    details JSONB DEFAULT '{}',
    
    -- Thresholds
    threshold_value DECIMAL(12,2),
    actual_value DECIMAL(12,2),
    
    -- Actions
    acknowledged_by INTEGER REFERENCES users(id),
    acknowledged_at TIMESTAMP WITH TIME ZONE,
    resolved_by INTEGER REFERENCES users(id),
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolution_notes TEXT,
    
    -- Snooze
    snoozed_until TIMESTAMP WITH TIME ZONE,
    snooze_count INTEGER DEFAULT 0,
    
    -- Escalation
    escalated BOOLEAN DEFAULT FALSE,
    escalated_to INTEGER REFERENCES users(id),
    escalated_at TIMESTAMP WITH TIME ZONE,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- ALERT NOTIFICATIONS - Sent notifications
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE notification_channel AS ENUM ('in_app', 'email', 'sms', 'slack', 'teams');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS alert_notifications (
    id SERIAL PRIMARY KEY,
    alert_id INTEGER NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    
    channel notification_channel NOT NULL,
    
    -- Delivery status
    sent_at TIMESTAMP WITH TIME ZONE,
    delivered_at TIMESTAMP WITH TIME ZONE,
    read_at TIMESTAMP WITH TIME ZONE,
    failed_at TIMESTAMP WITH TIME ZONE,
    failure_reason TEXT,
    
    -- Retry
    retry_count INTEGER DEFAULT 0,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- ALERT RULES - Configurable thresholds
-- =============================================================================

CREATE TABLE IF NOT EXISTS alert_rules (
    id SERIAL PRIMARY KEY,
    
    -- Rule definition
    name VARCHAR(255) NOT NULL,
    description TEXT,
    alert_type alert_type NOT NULL,
    severity alert_severity NOT NULL DEFAULT 'warning',
    
    -- Scope
    store_id INTEGER REFERENCES stores(id),  -- NULL = all stores
    item_id INTEGER REFERENCES items(id),    -- NULL = all items
    category VARCHAR(50),                     -- NULL = all categories
    
    -- Threshold
    condition VARCHAR(50) NOT NULL,  -- 'less_than', 'greater_than', 'equals', 'percentage_change'
    threshold_value DECIMAL(12,2) NOT NULL,
    comparison_period VARCHAR(50),  -- 'previous_day', 'previous_week', 'previous_month'
    
    -- Notification settings
    notify_roles TEXT[],  -- Roles to notify
    notify_users INTEGER[],  -- Specific users to notify
    channels notification_channel[] DEFAULT ARRAY['in_app']::notification_channel[],
    
    -- Schedule
    check_frequency_minutes INTEGER DEFAULT 60,
    last_checked_at TIMESTAMP WITH TIME ZONE,
    
    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- INDEXES
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_inventory_store ON inventory(store_id);
CREATE INDEX IF NOT EXISTS idx_inventory_item ON inventory(item_id);
CREATE INDEX IF NOT EXISTS idx_inventory_low_stock ON inventory(current_stock) WHERE current_stock <= reorder_point;
CREATE INDEX IF NOT EXISTS idx_inventory_abc ON inventory(abc_class);

CREATE INDEX IF NOT EXISTS idx_inv_trans_inventory ON inventory_transactions(inventory_id);
CREATE INDEX IF NOT EXISTS idx_inv_trans_store ON inventory_transactions(store_id);
CREATE INDEX IF NOT EXISTS idx_inv_trans_date ON inventory_transactions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_inv_trans_type ON inventory_transactions(transaction_type);

CREATE INDEX IF NOT EXISTS idx_transfers_status ON stock_transfers(status);
CREATE INDEX IF NOT EXISTS idx_transfers_from ON stock_transfers(from_store_id);
CREATE INDEX IF NOT EXISTS idx_transfers_to ON stock_transfers(to_store_id);

CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
CREATE INDEX IF NOT EXISTS idx_alerts_type ON alerts(alert_type);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
CREATE INDEX IF NOT EXISTS idx_alerts_store ON alerts(store_id);
CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_alert_notifications_user ON alert_notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_alert_notifications_unread ON alert_notifications(user_id) WHERE read_at IS NULL;

-- =============================================================================
-- INITIALIZE INVENTORY FROM SALES DATA
-- =============================================================================

INSERT INTO inventory (store_id, item_id, current_stock, reorder_point, reorder_quantity, average_daily_sales)
SELECT 
    s.store_id,
    s.item_id,
    COALESCE(SUM(s.sales), 0) * 2 AS current_stock,  -- Initialize with 2x recent sales
    GREATEST(COALESCE(AVG(s.sales), 10) * 7, 50) AS reorder_point,  -- 1 week supply minimum
    GREATEST(COALESCE(AVG(s.sales), 10) * 14, 100) AS reorder_quantity,  -- 2 week supply
    COALESCE(AVG(s.sales), 0) AS average_daily_sales
FROM sales s
WHERE s.date >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY s.store_id, s.item_id
ON CONFLICT (store_id, item_id) DO UPDATE SET
    average_daily_sales = EXCLUDED.average_daily_sales,
    updated_at = CURRENT_TIMESTAMP;

-- =============================================================================
-- DEFAULT ALERT RULES
-- =============================================================================

INSERT INTO alert_rules (name, description, alert_type, severity, condition, threshold_value, notify_roles, channels) VALUES
    ('Low Stock Alert', 'Triggered when stock falls below reorder point', 'low_stock', 'warning', 'less_than', 0, ARRAY['store_manager', 'regional_manager'], ARRAY['in_app', 'email']::notification_channel[]),
    ('Stockout Alert', 'Triggered when item is out of stock', 'stockout', 'critical', 'equals', 0, ARRAY['store_manager', 'regional_manager', 'super_admin'], ARRAY['in_app', 'email', 'sms']::notification_channel[]),
    ('Sales Drop Alert', 'Triggered when daily sales drop >20% vs forecast', 'sales_anomaly', 'warning', 'percentage_change', -20, ARRAY['regional_manager', 'super_admin'], ARRAY['in_app', 'email']::notification_channel[]),
    ('High Returns Alert', 'Triggered when returns exceed 10% of sales', 'returns_anomaly', 'warning', 'greater_than', 10, ARRAY['store_manager', 'regional_manager'], ARRAY['in_app']::notification_channel[])
ON CONFLICT DO NOTHING;

COMMIT;
