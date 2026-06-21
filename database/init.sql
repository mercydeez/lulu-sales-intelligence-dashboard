-- =============================================================================
-- Sales Dashboard Database Schema
-- Matches README.md architecture: sales_historical, sales_stream_raw, sales_fact_view
-- =============================================================================

-- Create tables
CREATE TABLE IF NOT EXISTS stores (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    location VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS items (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(50),
    unit_price_aed DECIMAL(10, 2) DEFAULT 10.00,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- HISTORICAL DATA TABLE (Immutable - Bulk loaded from CSV)
-- =============================================================================
CREATE TABLE IF NOT EXISTS sales_historical (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    store_id INTEGER NOT NULL REFERENCES stores(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    sales INTEGER NOT NULL, -- Allows negative values for returns
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- STREAMING DATA TABLE (Append-only with UUID for deduplication)
-- =============================================================================
CREATE TABLE IF NOT EXISTS sales_stream_raw (
    id SERIAL PRIMARY KEY,
    event_id UUID NOT NULL UNIQUE,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    store_id INTEGER NOT NULL REFERENCES stores(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    sales INTEGER NOT NULL, -- Allows negative values for returns
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Note: the legacy `sales` table is retired. Live events go to
-- sales_stream_raw and all readers query sales_fact_view (see migration 007).

-- Create predictions table
CREATE TABLE IF NOT EXISTS predictions (
    id SERIAL PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id),
    item_id INTEGER NOT NULL REFERENCES items(id),
    prediction_date DATE NOT NULL,
    predicted_sales FLOAT NOT NULL,
    confidence_lower FLOAT,
    confidence_upper FLOAT,
    model_version VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(prediction_date, store_id, item_id)
);

-- =============================================================================
-- INDEXES for Performance
-- =============================================================================
CREATE INDEX IF NOT EXISTS idx_sales_historical_date ON sales_historical(date);
CREATE INDEX IF NOT EXISTS idx_sales_historical_store_item ON sales_historical(store_id, item_id);
CREATE INDEX IF NOT EXISTS idx_sales_stream_timestamp ON sales_stream_raw(timestamp);
CREATE INDEX IF NOT EXISTS idx_sales_stream_store_item ON sales_stream_raw(store_id, item_id);

-- =============================================================================
-- Insert Meridian Hypermarket UAE stores
-- =============================================================================
INSERT INTO stores (id, name, location) VALUES 
    (1, 'Meridian Hypermarket Al Barsha', 'Dubai'),
    (2, 'Meridian Hypermarket Deira City Centre', 'Dubai'),
    (3, 'Meridian Hypermarket Karama', 'Dubai'),
    (4, 'Meridian Hypermarket Mushrif Mall', 'Abu Dhabi'),
    (5, 'Meridian Hypermarket Al Wahda', 'Abu Dhabi'),
    (6, 'Meridian Hypermarket Khalidiyah', 'Abu Dhabi'),
    (7, 'Meridian Hypermarket Sharjah City Centre', 'Sharjah'),
    (8, 'Meridian Hypermarket Al Nahda', 'Sharjah'),
    (9, 'Meridian Hypermarket Ajman', 'Ajman'),
    (10, 'Meridian Hypermarket Ras Al Khaimah', 'Ras Al Khaimah')
ON CONFLICT DO NOTHING;

-- =============================================================================
-- Insert grocery items with categories
-- =============================================================================
INSERT INTO items (id, name, category) VALUES
    (1, 'Basmati Rice (5kg)', 'Rice & Grains'),
    (2, 'Arabic Bread (Pack of 6)', 'Bakery'),
    (3, 'Fresh Chicken (1kg)', 'Poultry'),
    (4, 'Almarai Full Cream Milk (1L)', 'Dairy'),
    (5, 'Al Ain Bottled Water (1.5L x 6)', 'Beverages'),
    (6, 'Nescafe Classic (200g)', 'Beverages'),
    (7, 'Lipton Yellow Label Tea (200 bags)', 'Beverages'),
    (8, 'Extra Virgin Olive Oil (1L)', 'Cooking Oils'),
    (9, 'Fresh Tomatoes (1kg)', 'Vegetables'),
    (10, 'Fresh Bananas (1kg)', 'Fruits'),
    (11, 'Lurpak Butter (500g)', 'Dairy'),
    (12, 'Philadelphia Cream Cheese (500g)', 'Dairy'),
    (13, 'Al Rawabi Fresh Juice (1L)', 'Beverages'),
    (14, 'Maggi Noodles (Pack of 10)', 'Instant Food'),
    (15, 'Heinz Tomato Ketchup (500g)', 'Condiments'),
    (16, 'Goody Mayonnaise (500g)', 'Condiments'),
    (17, 'Nutella (750g)', 'Spreads'),
    (18, 'Kelloggs Corn Flakes (500g)', 'Breakfast'),
    (19, 'Fresh Eggs (30 pack)', 'Eggs'),
    (20, 'Sadia Frozen Chicken Nuggets (500g)', 'Frozen Foods'),
    (21, 'McCain French Fries (1kg)', 'Frozen Foods'),
    (22, 'Al Kabeer Beef Burger (8 pcs)', 'Frozen Foods'),
    (23, 'Puck Cheese Slices (24 pcs)', 'Dairy'),
    (24, 'Rainbow Evaporated Milk (410g)', 'Dairy'),
    (25, 'Nido Milk Powder (2.5kg)', 'Dairy'),
    (26, 'Tide Washing Powder (6kg)', 'Household'),
    (27, 'Fairy Dish Soap (1L)', 'Household'),
    (28, 'Dettol Antiseptic (1L)', 'Personal Care'),
    (29, 'Colgate Toothpaste (150g)', 'Personal Care'),
    (30, 'Head & Shoulders Shampoo (400ml)', 'Personal Care'),
    (31, 'Pampers Diapers (64 pcs)', 'Baby Care'),
    (32, 'Huggies Baby Wipes (64 pcs)', 'Baby Care'),
    (33, 'Red Bull Energy Drink (4 pack)', 'Beverages'),
    (34, 'Pepsi (2.25L)', 'Beverages'),
    (35, 'Coca-Cola (2.25L)', 'Beverages'),
    (36, 'Fresh Lamb (1kg)', 'Meat'),
    (37, 'Fresh Salmon Fillet (500g)', 'Seafood'),
    (38, 'Fresh Shrimp (500g)', 'Seafood'),
    (39, 'Saffron (1g)', 'Spices'),
    (40, 'Cardamom (100g)', 'Spices'),
    (41, 'Fresh Dates (1kg)', 'Fruits'),
    (42, 'Arabic Coffee (250g)', 'Beverages'),
    (43, 'Hummus (400g)', 'Deli'),
    (44, 'Labneh (500g)', 'Dairy'),
    (45, 'Tahini (400g)', 'Condiments'),
    (46, 'Baklava Box (500g)', 'Sweets'),
    (47, 'Fresh Mango (1kg)', 'Fruits'),
    (48, 'Cucumber (1kg)', 'Vegetables'),
    (49, 'Onions (2kg)', 'Vegetables'),
    (50, 'Potatoes (2kg)', 'Vegetables')
ON CONFLICT DO NOTHING;

-- Update realistic prices for items
UPDATE items SET unit_price_aed = 45.00 WHERE id = 1;
UPDATE items SET unit_price_aed = 3.50 WHERE id = 2;
UPDATE items SET unit_price_aed = 18.00 WHERE id = 3;
UPDATE items SET unit_price_aed = 6.00 WHERE id = 4;
UPDATE items SET unit_price_aed = 8.50 WHERE id = 5;
UPDATE items SET unit_price_aed = 22.00 WHERE id = 6;
UPDATE items SET unit_price_aed = 16.00 WHERE id = 7;
UPDATE items SET unit_price_aed = 28.00 WHERE id = 8;
UPDATE items SET unit_price_aed = 5.00 WHERE id = 9;
UPDATE items SET unit_price_aed = 6.00 WHERE id = 10;
UPDATE items SET unit_price_aed = 18.50 WHERE id = 11;
UPDATE items SET unit_price_aed = 19.00 WHERE id = 12;
UPDATE items SET unit_price_aed = 8.00 WHERE id = 13;
UPDATE items SET unit_price_aed = 12.00 WHERE id = 14;
UPDATE items SET unit_price_aed = 9.50 WHERE id = 15;
UPDATE items SET unit_price_aed = 11.00 WHERE id = 16;
UPDATE items SET unit_price_aed = 24.00 WHERE id = 17;
UPDATE items SET unit_price_aed = 15.00 WHERE id = 18;
UPDATE items SET unit_price_aed = 14.50 WHERE id = 19;
UPDATE items SET unit_price_aed = 12.50 WHERE id = 20;
UPDATE items SET unit_price_aed = 14.00 WHERE id = 21;
UPDATE items SET unit_price_aed = 16.00 WHERE id = 22;
UPDATE items SET unit_price_aed = 14.00 WHERE id = 23;
UPDATE items SET unit_price_aed = 3.50 WHERE id = 24;
UPDATE items SET unit_price_aed = 68.00 WHERE id = 25;
UPDATE items SET unit_price_aed = 48.00 WHERE id = 26;
UPDATE items SET unit_price_aed = 11.50 WHERE id = 27;
UPDATE items SET unit_price_aed = 24.50 WHERE id = 28;
UPDATE items SET unit_price_aed = 9.00 WHERE id = 29;
UPDATE items SET unit_price_aed = 16.50 WHERE id = 30;
UPDATE items SET unit_price_aed = 55.00 WHERE id = 31;
UPDATE items SET unit_price_aed = 12.00 WHERE id = 32;
UPDATE items SET unit_price_aed = 32.00 WHERE id = 33;
UPDATE items SET unit_price_aed = 7.50 WHERE id = 34;
UPDATE items SET unit_price_aed = 7.50 WHERE id = 35;
UPDATE items SET unit_price_aed = 42.00 WHERE id = 36;
UPDATE items SET unit_price_aed = 38.00 WHERE id = 37;
UPDATE items SET unit_price_aed = 29.00 WHERE id = 38;
UPDATE items SET unit_price_aed = 35.00 WHERE id = 39;
UPDATE items SET unit_price_aed = 18.00 WHERE id = 40;
UPDATE items SET unit_price_aed = 25.00 WHERE id = 41;
UPDATE items SET unit_price_aed = 19.50 WHERE id = 42;
UPDATE items SET unit_price_aed = 6.00 WHERE id = 43;
UPDATE items SET unit_price_aed = 12.00 WHERE id = 44;
UPDATE items SET unit_price_aed = 14.00 WHERE id = 45;
UPDATE items SET unit_price_aed = 35.00 WHERE id = 46;
UPDATE items SET unit_price_aed = 15.00 WHERE id = 47;
UPDATE items SET unit_price_aed = 4.00 WHERE id = 48;
UPDATE items SET unit_price_aed = 6.00 WHERE id = 49;
UPDATE items SET unit_price_aed = 6.00 WHERE id = 50;


-- =============================================================================
-- Historical data load + date-shift are performed by the APPLICATION seeder
-- (backend/app/services/db_seeder.py), NOT here. Managed Postgres (e.g. Render)
-- cannot run this file via the docker-entrypoint, and a server-side
-- `COPY FROM '/data/train.csv'` requires the file on the DB server, which it
-- isn't. The seeder bulk-loads data/train.csv into sales_historical (asyncpg
-- COPY) and shifts the dates so the latest day is yesterday — portably, in
-- every environment. This script stays pure, idempotent schema + seed DDL.
-- =============================================================================

-- =============================================================================
-- UNIFIED VIEW: sales_fact_view (Historical UNION Streaming)
-- =============================================================================
-- Shaped as a drop-in for the retired `sales` table (same columns) so the ORM
-- Sale model and raw-SQL readers work unchanged. Streaming ids are offset by
-- 1,000,000,000 to stay unique across the union. Kept in sync with migration 007.
-- Ensure tenant_id exists on the base tables so the view can carry it. Migration
-- 010 adds the same column (+ FK) idempotently; keeping it here makes init.sql
-- self-consistent, so re-running it never tries to drop tenant_id from the view
-- ("cannot drop columns from view").
ALTER TABLE sales_historical ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1;
ALTER TABLE sales_stream_raw ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1;

-- security_invoker: the view evaluates underlying-table RLS as the CALLER, so
-- the non-owner app_rw role (Sage executor / RLS request path) is tenant-scoped
-- through the view too. Baked in here because init.sql runs on every boot and
-- would otherwise clear the setting that migration 021 applied once.
CREATE OR REPLACE VIEW sales_fact_view WITH (security_invoker = true) AS
SELECT
    id,
    date,
    store_id,
    item_id,
    sales,
    FALSE AS is_streaming,
    'historical'::text AS source,
    created_at,
    tenant_id
FROM sales_historical
UNION ALL
SELECT
    id + 1000000000 AS id,
    timestamp::date AS date,
    store_id,
    item_id,
    sales,
    TRUE AS is_streaming,
    'streaming'::text AS source,
    COALESCE(created_at, timestamp) AS created_at,
    tenant_id
FROM sales_stream_raw;

-- =============================================================================
-- Log Completion
-- =============================================================================
DO $$
DECLARE
    historical_count INTEGER;
    store_count INTEGER;
    item_count INTEGER;
    min_date DATE;
    max_date DATE;
BEGIN
    SELECT COUNT(*) INTO historical_count FROM sales_historical;
    SELECT COUNT(*) INTO store_count FROM stores;
    SELECT COUNT(*) INTO item_count FROM items;
    SELECT MIN(date), MAX(date) INTO min_date, max_date FROM sales_historical;
    
    RAISE NOTICE '✅ Successfully loaded % historical records', historical_count;
    RAISE NOTICE '📊 Data range: % to %', min_date, max_date;
    RAISE NOTICE '📊 Unique stores: %', store_count;
    RAISE NOTICE '📊 Unique items: %', item_count;
END $$;

-- =============================================================================
-- AUTHENTICATION & USER MANAGEMENT TABLES
-- =============================================================================

-- ENUM TYPES
DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('super_admin', 'regional_manager', 'store_manager', 'analyst');
EXCEPTION WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE user_status AS ENUM ('active', 'inactive', 'locked', 'pending');
EXCEPTION WHEN duplicate_object THEN null;
END $$;

-- REGIONS TABLE
CREATE TABLE IF NOT EXISTS regions (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO regions (code, name, description) VALUES 
    ('dubai', 'Dubai Region', 'All Meridian stores in Dubai emirate'),
    ('abu_dhabi', 'Abu Dhabi Region', 'All Meridian stores in Abu Dhabi emirate'),
    ('northern_emirates', 'Northern Emirates Region', 'Stores in Sharjah, Ajman, RAK')
ON CONFLICT (code) DO NOTHING;

-- Update stores with region_id
ALTER TABLE stores ADD COLUMN IF NOT EXISTS region_id INTEGER REFERENCES regions(id);

UPDATE stores SET region_id = (SELECT id FROM regions WHERE code = 'dubai') WHERE id IN (1, 2, 3);
UPDATE stores SET region_id = (SELECT id FROM regions WHERE code = 'abu_dhabi') WHERE id IN (4, 5, 6);
UPDATE stores SET region_id = (SELECT id FROM regions WHERE code = 'northern_emirates') WHERE id IN (7, 8, 9, 10);

-- USERS TABLE
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    role user_role NOT NULL DEFAULT 'analyst',
    status user_status NOT NULL DEFAULT 'active',
    phone VARCHAR(20),
    job_title VARCHAR(100),
    department VARCHAR(100),
    failed_login_attempts INTEGER DEFAULT 0,
    locked_until TIMESTAMP WITH TIME ZONE,
    password_changed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    must_change_password BOOLEAN DEFAULT FALSE,
    two_factor_enabled BOOLEAN DEFAULT FALSE,
    two_factor_secret VARCHAR(100),
    last_login_at TIMESTAMP WITH TIME ZONE,
    last_login_ip VARCHAR(45),
    last_activity_at TIMESTAMP WITH TIME ZONE,
    preferences JSONB DEFAULT '{}',
    notification_settings JSONB DEFAULT '{"email": true, "in_app": true, "sms": false}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- USER PERMISSIONS TABLE
CREATE TABLE IF NOT EXISTS user_permissions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    region_id INTEGER REFERENCES regions(id),
    store_id INTEGER REFERENCES stores(id),
    can_view BOOLEAN DEFAULT TRUE,
    can_edit BOOLEAN DEFAULT FALSE,
    can_delete BOOLEAN DEFAULT FALSE,
    can_export BOOLEAN DEFAULT FALSE,
    can_manage_users BOOLEAN DEFAULT FALSE,
    can_manage_inventory BOOLEAN DEFAULT FALSE,
    can_manage_promotions BOOLEAN DEFAULT FALSE,
    can_view_financials BOOLEAN DEFAULT FALSE,
    can_approve_transfers BOOLEAN DEFAULT FALSE,
    valid_from DATE DEFAULT CURRENT_DATE,
    valid_until DATE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- AUDIT LOG TABLE  
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    user_email VARCHAR(255),
    action VARCHAR(50) NOT NULL,
    resource_type VARCHAR(100),
    resource_id VARCHAR(100),
    description TEXT,
    old_values JSONB,
    new_values JSONB,
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- INDEXES
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_user_permissions_user ON user_permissions(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at DESC);

-- =============================================================================
-- INSERT DEFAULT USERS
-- Password: Demo@2026! (bcrypt hash)
-- =============================================================================

INSERT INTO users (email, password_hash, first_name, last_name, role, status, job_title, department) VALUES 
    ('atharva@retaildemo.app', '$2b$12$H5K0AMsU34kndvqz4reAkOOZ5QmINt67ZriaLAHJc5bCzK64SUv/i', 'Atharva', 'Soundankar', 'super_admin', 'active', 'Senior Vice President', 'Executive Leadership'),
    ('krishna@retaildemo.app', '$2b$12$H5K0AMsU34kndvqz4reAkOOZ5QmINt67ZriaLAHJc5bCzK64SUv/i', 'Krishna', 'Sharma', 'regional_manager', 'active', 'Senior Regional Manager', 'Operations'),
    ('yash@retaildemo.app', '$2b$12$H5K0AMsU34kndvqz4reAkOOZ5QmINt67ZriaLAHJc5bCzK64SUv/i', 'Yash', 'Patel', 'store_manager', 'active', 'Store Manager', 'Store Operations')
ON CONFLICT (email) DO NOTHING;

-- SET UP PERMISSIONS
-- ATHARVA (Senior VP) - Full access to all regions
INSERT INTO user_permissions (user_id, region_id, can_view, can_edit, can_delete, can_export, can_manage_users, can_manage_inventory, can_manage_promotions, can_view_financials, can_approve_transfers)
SELECT u.id, r.id, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE
FROM users u, regions r
WHERE u.email = 'atharva@retaildemo.app'
ON CONFLICT DO NOTHING;

-- KRISHNA (Senior Manager) - Dubai Region only
INSERT INTO user_permissions (user_id, region_id, can_view, can_edit, can_delete, can_export, can_manage_users, can_manage_inventory, can_manage_promotions, can_view_financials, can_approve_transfers)
SELECT u.id, r.id, TRUE, TRUE, FALSE, TRUE, FALSE, TRUE, TRUE, TRUE, TRUE
FROM users u, regions r
WHERE u.email = 'krishna@retaildemo.app' AND r.code = 'dubai'
ON CONFLICT DO NOTHING;

-- 