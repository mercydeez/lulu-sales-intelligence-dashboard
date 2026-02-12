-- =============================================================================
-- LULU HYPERMARKET UAE - AUTHENTICATION & AUTHORIZATION SCHEMA
-- Migration 001: User Management, Roles, Permissions, Audit Logging
-- =============================================================================

-- =============================================================================
-- ENUM TYPES
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('super_admin', 'regional_manager', 'store_manager', 'analyst');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE user_status AS ENUM ('active', 'inactive', 'locked', 'pending');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE audit_action AS ENUM (
        'login', 'logout', 'login_failed', 
        'view_dashboard', 'view_report', 'export_data',
        'create_record', 'update_record', 'delete_record',
        'change_password', 'update_profile',
        'create_user', 'update_user', 'delete_user',
        'create_alert', 'acknowledge_alert',
        'create_promotion', 'update_promotion',
        'stock_transfer', 'inventory_adjustment'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE region_code AS ENUM ('dubai', 'abu_dhabi', 'northern_emirates', 'all');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- =============================================================================
-- REGIONS TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS regions (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Insert regions
INSERT INTO regions (code, name, description) VALUES 
    ('dubai', 'Dubai Region', 'All Lulu stores in Dubai emirate'),
    ('abu_dhabi', 'Abu Dhabi Region', 'All Lulu stores in Abu Dhabi emirate'),
    ('northern_emirates', 'Northern Emirates Region', 'Stores in Sharjah, Ajman, RAK')
ON CONFLICT (code) DO NOTHING;

-- =============================================================================
-- UPDATE STORES TABLE WITH REGION
-- =============================================================================

ALTER TABLE stores ADD COLUMN IF NOT EXISTS region_id INTEGER REFERENCES regions(id);
ALTER TABLE stores ADD COLUMN IF NOT EXISTS square_footage INTEGER DEFAULT 50000;
ALTER TABLE stores ADD COLUMN IF NOT EXISTS opening_date DATE DEFAULT '2020-01-01';

-- Update store regions
UPDATE stores SET region_id = (SELECT id FROM regions WHERE code = 'dubai') 
WHERE id IN (1, 2, 3);

UPDATE stores SET region_id = (SELECT id FROM regions WHERE code = 'abu_dhabi') 
WHERE id IN (4, 5, 6);

UPDATE stores SET region_id = (SELECT id FROM regions WHERE code = 'northern_emirates') 
WHERE id IN (7, 8, 9, 10);

-- =============================================================================
-- USERS TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    role user_role NOT NULL DEFAULT 'analyst',
    status user_status NOT NULL DEFAULT 'active',
    
    -- Profile
    phone VARCHAR(20),
    avatar_url VARCHAR(500),
    job_title VARCHAR(100),
    department VARCHAR(100),
    
    -- Security
    failed_login_attempts INTEGER DEFAULT 0,
    locked_until TIMESTAMP WITH TIME ZONE,
    password_changed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    must_change_password BOOLEAN DEFAULT FALSE,
    two_factor_enabled BOOLEAN DEFAULT FALSE,
    two_factor_secret VARCHAR(100),
    
    -- Session
    last_login_at TIMESTAMP WITH TIME ZONE,
    last_login_ip VARCHAR(45),
    last_activity_at TIMESTAMP WITH TIME ZONE,
    
    -- Preferences
    preferences JSONB DEFAULT '{}',
    notification_settings JSONB DEFAULT '{"email": true, "in_app": true, "sms": false}',
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by INTEGER REFERENCES users(id),
    
    -- Constraints
    CONSTRAINT valid_email CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
);

-- =============================================================================
-- USER PERMISSIONS TABLE (Row-Level Security)
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_permissions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Regional access (for regional managers)
    region_id INTEGER REFERENCES regions(id),
    
    -- Store-level access (for store managers)
    store_id INTEGER REFERENCES stores(id),
    
    -- Permission flags
    can_view BOOLEAN DEFAULT TRUE,
    can_edit BOOLEAN DEFAULT FALSE,
    can_delete BOOLEAN DEFAULT FALSE,
    can_export BOOLEAN DEFAULT FALSE,
    can_manage_users BOOLEAN DEFAULT FALSE,
    can_manage_inventory BOOLEAN DEFAULT FALSE,
    can_manage_promotions BOOLEAN DEFAULT FALSE,
    can_view_financials BOOLEAN DEFAULT FALSE,
    can_approve_transfers BOOLEAN DEFAULT FALSE,
    
    -- Validity
    valid_from DATE DEFAULT CURRENT_DATE,
    valid_until DATE,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT unique_user_store UNIQUE (user_id, store_id),
    CONSTRAINT unique_user_region UNIQUE (user_id, region_id)
);

-- =============================================================================
-- USER SESSIONS TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_token VARCHAR(500) UNIQUE NOT NULL,
    refresh_token VARCHAR(500) UNIQUE,
    
    -- Session info
    ip_address VARCHAR(45),
    user_agent TEXT,
    device_type VARCHAR(50),
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    last_activity_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMP WITH TIME ZONE,
    
    -- Status
    is_active BOOLEAN DEFAULT TRUE
);

-- =============================================================================
-- AUDIT LOG TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    
    -- Who
    user_id INTEGER REFERENCES users(id),
    user_email VARCHAR(255),
    user_role VARCHAR(50),
    
    -- What
    action audit_action NOT NULL,
    resource_type VARCHAR(100),
    resource_id VARCHAR(100),
    
    -- Details
    description TEXT,
    old_values JSONB,
    new_values JSONB,
    metadata JSONB DEFAULT '{}',
    
    -- Where
    ip_address VARCHAR(45),
    user_agent TEXT,
    endpoint VARCHAR(500),
    
    -- When
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Partition audit_log by month for performance
-- CREATE TABLE audit_log_2026_01 PARTITION OF audit_log
--     FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');

-- =============================================================================
-- PASSWORD RESET TOKENS
-- =============================================================================

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token VARCHAR(255) UNIQUE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    used_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- INDEXES FOR PERFORMANCE
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);
CREATE INDEX IF NOT EXISTS idx_user_permissions_user ON user_permissions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_permissions_store ON user_permissions(store_id);
CREATE INDEX IF NOT EXISTS idx_user_permissions_region ON user_permissions(region_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_token ON user_sessions(session_token);
CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_resource ON audit_log(resource_type, resource_id);

-- =============================================================================
-- INSERT DEFAULT USERS
-- =============================================================================

-- Password for all users: Lulu@2026! (bcrypt hashed)
-- Hash generated with: passlib.hash.bcrypt.hash("Lulu@2026!")

INSERT INTO users (email, password_hash, first_name, last_name, role, status, job_title, department) VALUES 
    -- Senior VP - ATHARVA (Super Admin - sees everything)
    ('atharva@lulu.ae', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.G.D.wLjwhWvEKi', 'Atharva', 'Soundankar', 'super_admin', 'active', 'Senior Vice President', 'Executive Leadership'),
    
    -- Senior Manager - KRISHNA (Regional Manager - Dubai Region)
    ('krishna@lulu.ae', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.G.D.wLjwhWvEKi', 'Krishna', 'Sharma', 'regional_manager', 'active', 'Senior Regional Manager', 'Operations'),
    
    -- Store Manager - YASH (Store Manager - Al Barsha only)
    ('yash@lulu.ae', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.G.D.wLjwhWvEKi', 'Yash', 'Patel', 'store_manager', 'active', 'Store Manager', 'Store Operations')
ON CONFLICT (email) DO NOTHING;

-- =============================================================================
-- SET UP PERMISSIONS FOR DEFAULT USERS
-- =============================================================================

-- ATHARVA (Senior VP) - Full access to all regions and stores
INSERT INTO user_permissions (user_id, region_id, can_view, can_edit, can_delete, can_export, can_manage_users, can_manage_inventory, can_manage_promotions, can_view_financials, can_approve_transfers)
SELECT u.id, r.id, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE
FROM users u, regions r
WHERE u.email = 'atharva@lulu.ae'
ON CONFLICT DO NOTHING;

-- KRISHNA (Senior Manager) - Dubai Region only
INSERT INTO user_permissions (user_id, region_id, can_view, can_edit, can_delete, can_export, can_manage_users, can_manage_inventory, can_manage_promotions, can_view_financials, can_approve_transfers)
SELECT u.id, r.id, TRUE, TRUE, FALSE, TRUE, FALSE, TRUE, TRUE, TRUE, TRUE
FROM users u, regions r
WHERE u.email = 'krishna@lulu.ae' AND r.code = 'dubai'
ON CONFLICT DO NOTHING;

-- YASH (Store Manager) - Al Barsha store only
INSERT INTO user_permissions (user_id, store_id, can_view, can_edit, can_delete, can_export, can_manage_users, can_manage_inventory, can_manage_promotions, can_view_financials, can_approve_transfers)
SELECT u.id, s.id, TRUE, TRUE, FALSE, TRUE, FALSE, TRUE, FALSE, FALSE, FALSE
FROM users u, stores s
WHERE u.email = 'yash@lulu.ae' AND s.id = 1
ON CONFLICT DO NOTHING;

-- =============================================================================
-- ROW LEVEL SECURITY POLICIES
-- =============================================================================

-- Enable RLS on sales table
ALTER TABLE sales ENABLE ROW LEVEL SECURITY;

-- Policy: Super admins see all
CREATE POLICY IF NOT EXISTS sales_super_admin ON sales
    FOR ALL
    TO PUBLIC
    USING (
        EXISTS (
            SELECT 1 FROM users 
            WHERE users.role = 'super_admin' 
            AND users.id = current_setting('app.current_user_id', true)::integer
        )
    );

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to check if user can access a store
CREATE OR REPLACE FUNCTION user_can_access_store(p_user_id INTEGER, p_store_id INTEGER)
RETURNS BOOLEAN AS $$
DECLARE
    v_role user_role;
    v_has_permission BOOLEAN;
BEGIN
    -- Get user role
    SELECT role INTO v_role FROM users WHERE id = p_user_id;
    
    -- Super admin can access everything
    IF v_role = 'super_admin' THEN
        RETURN TRUE;
    END IF;
    
    -- Check direct store permission
    SELECT EXISTS (
        SELECT 1 FROM user_permissions 
        WHERE user_id = p_user_id 
        AND store_id = p_store_id
        AND can_view = TRUE
        AND (valid_until IS NULL OR valid_until >= CURRENT_DATE)
    ) INTO v_has_permission;
    
    IF v_has_permission THEN
        RETURN TRUE;
    END IF;
    
    -- Check regional permission
    SELECT EXISTS (
        SELECT 1 FROM user_permissions up
        JOIN stores s ON s.region_id = up.region_id
        WHERE up.user_id = p_user_id 
        AND s.id = p_store_id
        AND up.can_view = TRUE
        AND (up.valid_until IS NULL OR up.valid_until >= CURRENT_DATE)
    ) INTO v_has_permission;
    
    RETURN v_has_permission;
END;
$$ LANGUAGE plpgsql;

-- Function to get accessible store IDs for a user
CREATE OR REPLACE FUNCTION get_user_accessible_stores(p_user_id INTEGER)
RETURNS TABLE(store_id INTEGER) AS $$
DECLARE
    v_role user_role;
BEGIN
    SELECT role INTO v_role FROM users WHERE id = p_user_id;
    
    -- Super admin gets all stores
    IF v_role = 'super_admin' THEN
        RETURN QUERY SELECT s.id FROM stores s;
        RETURN;
    END IF;
    
    -- Get stores from direct permissions and regional permissions
    RETURN QUERY
    SELECT DISTINCT s.id
    FROM stores s
    LEFT JOIN user_permissions up_store ON up_store.store_id = s.id AND up_store.user_id = p_user_id
    LEFT JOIN user_permissions up_region ON up_region.region_id = s.region_id AND up_region.user_id = p_user_id
    WHERE (up_store.id IS NOT NULL OR up_region.id IS NOT NULL)
    AND (up_store.can_view = TRUE OR up_region.can_view = TRUE);
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- TRIGGERS
-- =============================================================================

-- Update timestamp trigger
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_permissions_updated_at
    BEFORE UPDATE ON user_permissions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

COMMIT;
