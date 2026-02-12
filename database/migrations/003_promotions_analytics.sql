-- =============================================================================
-- LULU HYPERMARKET UAE - PROMOTIONS & ADVANCED ANALYTICS SCHEMA
-- Migration 003: Promotions, Pricing, Reports, Scheduled Jobs
-- =============================================================================

-- =============================================================================
-- PROMOTIONS TABLE
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE promotion_type AS ENUM (
        'percentage_discount', 'fixed_discount', 'buy_one_get_one',
        'buy_x_get_y', 'bundle_deal', 'clearance', 'loyalty_exclusive'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE promotion_status AS ENUM ('draft', 'scheduled', 'active', 'paused', 'ended', 'cancelled');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS promotions (
    id SERIAL PRIMARY KEY,
    
    -- Basic info
    name VARCHAR(255) NOT NULL,
    description TEXT,
    promotion_code VARCHAR(50) UNIQUE,
    
    -- Type and discount
    promotion_type promotion_type NOT NULL,
    discount_value DECIMAL(10,2) NOT NULL,  -- Percentage or fixed amount
    discount_cap DECIMAL(10,2),  -- Maximum discount amount
    
    -- Scope
    applies_to_all_stores BOOLEAN DEFAULT TRUE,
    applies_to_all_items BOOLEAN DEFAULT FALSE,
    
    -- Conditions
    minimum_purchase DECIMAL(10,2),
    minimum_quantity INTEGER,
    max_uses_total INTEGER,
    max_uses_per_customer INTEGER,
    current_uses INTEGER DEFAULT 0,
    
    -- Schedule
    start_date TIMESTAMP WITH TIME ZONE NOT NULL,
    end_date TIMESTAMP WITH TIME ZONE NOT NULL,
    status promotion_status DEFAULT 'draft',
    
    -- Performance tracking
    total_revenue DECIMAL(14,2) DEFAULT 0,
    total_discount_given DECIMAL(12,2) DEFAULT 0,
    total_transactions INTEGER DEFAULT 0,
    
    -- Audit
    created_by INTEGER REFERENCES users(id),
    approved_by INTEGER REFERENCES users(id),
    approved_at TIMESTAMP WITH TIME ZONE,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- PROMOTION ITEMS - Items included in promotion
-- =============================================================================

CREATE TABLE IF NOT EXISTS promotion_items (
    id SERIAL PRIMARY KEY,
    promotion_id INTEGER NOT NULL REFERENCES promotions(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id),
    
    -- Item-specific discount (overrides promotion default)
    custom_discount_value DECIMAL(10,2),
    
    -- For bundle deals
    required_quantity INTEGER DEFAULT 1,
    free_quantity INTEGER DEFAULT 0,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT unique_promotion_item UNIQUE (promotion_id, item_id)
);

-- =============================================================================
-- PROMOTION STORES - Stores where promotion is valid
-- =============================================================================

CREATE TABLE IF NOT EXISTS promotion_stores (
    id SERIAL PRIMARY KEY,
    promotion_id INTEGER NOT NULL REFERENCES promotions(id) ON DELETE CASCADE,
    store_id INTEGER NOT NULL REFERENCES stores(id),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT unique_promotion_store UNIQUE (promotion_id, store_id)
);

-- =============================================================================
-- COMPETITOR PRICES - Price monitoring
-- =============================================================================

CREATE TABLE IF NOT EXISTS competitor_prices (
    id SERIAL PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items(id),
    
    competitor_name VARCHAR(100) NOT NULL,
    competitor_price DECIMAL(10,2) NOT NULL,
    our_price DECIMAL(10,2),
    price_difference DECIMAL(10,2),
    
    -- Location context
    location VARCHAR(100),
    store_id INTEGER REFERENCES stores(id),
    
    -- Validity
    observed_date DATE NOT NULL DEFAULT CURRENT_DATE,
    valid_until DATE,
    
    -- Source
    source VARCHAR(50),  -- 'manual', 'web_scrape', 'api'
    recorded_by INTEGER REFERENCES users(id),
    
    notes TEXT,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- BASKET ANALYSIS - Frequently bought together
-- =============================================================================

CREATE TABLE IF NOT EXISTS basket_associations (
    id SERIAL PRIMARY KEY,
    item_a_id INTEGER NOT NULL REFERENCES items(id),
    item_b_id INTEGER NOT NULL REFERENCES items(id),
    
    -- Association metrics
    support DECIMAL(8,6) NOT NULL,  -- Frequency of both items together
    confidence DECIMAL(8,6) NOT NULL,  -- P(B|A) - probability of B given A
    lift DECIMAL(8,4) NOT NULL,  -- How much more likely together than random
    
    -- Counts
    transactions_both INTEGER NOT NULL,
    transactions_a INTEGER NOT NULL,
    transactions_b INTEGER NOT NULL,
    total_transactions INTEGER NOT NULL,
    
    -- Time period
    analysis_start_date DATE NOT NULL,
    analysis_end_date DATE NOT NULL,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT unique_item_pair UNIQUE (item_a_id, item_b_id),
    CONSTRAINT different_items CHECK (item_a_id < item_b_id)  -- Ensure no duplicates
);

-- =============================================================================
-- SCHEDULED REPORTS
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE report_frequency AS ENUM ('once', 'daily', 'weekly', 'monthly', 'quarterly');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE report_format AS ENUM ('pdf', 'excel', 'csv', 'json');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS scheduled_reports (
    id SERIAL PRIMARY KEY,
    
    -- Report definition
    name VARCHAR(255) NOT NULL,
    description TEXT,
    report_type VARCHAR(100) NOT NULL,  -- 'sales_summary', 'inventory_status', 'promotion_performance'
    
    -- Parameters
    parameters JSONB DEFAULT '{}',  -- Store IDs, date ranges, filters
    
    -- Schedule
    frequency report_frequency NOT NULL,
    day_of_week INTEGER,  -- 0-6 for weekly
    day_of_month INTEGER,  -- 1-31 for monthly
    time_of_day TIME DEFAULT '08:00:00',
    timezone VARCHAR(50) DEFAULT 'Asia/Dubai',
    
    -- Output
    format report_format DEFAULT 'pdf',
    
    -- Distribution
    recipient_emails TEXT[],
    recipient_users INTEGER[],
    
    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    last_run_at TIMESTAMP WITH TIME ZONE,
    next_run_at TIMESTAMP WITH TIME ZONE,
    
    -- Audit
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- REPORT HISTORY - Generated reports
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE report_status AS ENUM ('pending', 'generating', 'completed', 'failed');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS report_history (
    id SERIAL PRIMARY KEY,
    scheduled_report_id INTEGER REFERENCES scheduled_reports(id),
    
    -- Report info
    report_type VARCHAR(100) NOT NULL,
    report_name VARCHAR(255) NOT NULL,
    parameters JSONB,
    
    -- Status
    status report_status DEFAULT 'pending',
    
    -- Output
    format report_format,
    file_path VARCHAR(500),
    file_size_bytes BIGINT,
    
    -- Timing
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    duration_seconds INTEGER,
    
    -- Error handling
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    
    -- Access
    generated_by INTEGER REFERENCES users(id),
    download_count INTEGER DEFAULT 0,
    last_downloaded_at TIMESTAMP WITH TIME ZONE,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- SALES ANALYTICS MATERIALIZED VIEWS
-- =============================================================================

-- Daily sales summary by store
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_daily_sales_by_store AS
SELECT 
    date,
    store_id,
    COUNT(*) as transaction_count,
    SUM(CASE WHEN sales > 0 THEN sales ELSE 0 END) as total_sales,
    SUM(CASE WHEN sales < 0 THEN ABS(sales) ELSE 0 END) as total_returns,
    SUM(sales) as net_sales,
    AVG(sales) as avg_sale,
    COUNT(DISTINCT item_id) as unique_items
FROM sales
GROUP BY date, store_id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_daily_store ON mv_daily_sales_by_store(date, store_id);

-- Weekly sales by category
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_weekly_sales_by_category AS
SELECT 
    DATE_TRUNC('week', s.date) as week_start,
    i.category,
    SUM(s.sales) as total_sales,
    COUNT(*) as transaction_count,
    COUNT(DISTINCT s.store_id) as stores_count
FROM sales s
JOIN items i ON s.item_id = i.id
GROUP BY DATE_TRUNC('week', s.date), i.category;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_weekly_category ON mv_weekly_sales_by_category(week_start, category);

-- Hourly sales pattern (for heatmap)
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_hourly_sales_pattern AS
SELECT 
    EXTRACT(DOW FROM created_at) as day_of_week,
    EXTRACT(HOUR FROM created_at) as hour_of_day,
    store_id,
    COUNT(*) as transaction_count,
    SUM(sales) as total_sales,
    AVG(sales) as avg_sales
FROM sales
WHERE created_at >= CURRENT_DATE - INTERVAL '90 days'
GROUP BY EXTRACT(DOW FROM created_at), EXTRACT(HOUR FROM created_at), store_id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_hourly_pattern ON mv_hourly_sales_pattern(day_of_week, hour_of_day, store_id);

-- =============================================================================
-- INDEXES
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_promotions_status ON promotions(status);
CREATE INDEX IF NOT EXISTS idx_promotions_dates ON promotions(start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_promotions_active ON promotions(status) WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_promotion_items_promotion ON promotion_items(promotion_id);
CREATE INDEX IF NOT EXISTS idx_promotion_items_item ON promotion_items(item_id);

CREATE INDEX IF NOT EXISTS idx_competitor_prices_item ON competitor_prices(item_id);
CREATE INDEX IF NOT EXISTS idx_competitor_prices_date ON competitor_prices(observed_date DESC);

CREATE INDEX IF NOT EXISTS idx_basket_lift ON basket_associations(lift DESC);
CREATE INDEX IF NOT EXISTS idx_basket_items ON basket_associations(item_a_id, item_b_id);

CREATE INDEX IF NOT EXISTS idx_scheduled_reports_active ON scheduled_reports(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_scheduled_reports_next_run ON scheduled_reports(next_run_at);

CREATE INDEX IF NOT EXISTS idx_report_history_scheduled ON report_history(scheduled_report_id);
CREATE INDEX IF NOT EXISTS idx_report_history_status ON report_history(status);
CREATE INDEX IF NOT EXISTS idx_report_history_date ON report_history(created_at DESC);

-- =============================================================================
-- REFRESH MATERIALIZED VIEWS FUNCTION
-- =============================================================================

CREATE OR REPLACE FUNCTION refresh_analytics_views()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_sales_by_store;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_weekly_sales_by_category;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_hourly_sales_pattern;
END;
$$ LANGUAGE plpgsql;

COMMIT;
