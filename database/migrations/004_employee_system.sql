-- =============================================================================
-- LULU HYPERMARKET UAE - EMPLOYEE MANAGEMENT SYSTEM
-- Migration 004: Employee Biodata, Performance Tracking, Transaction Attribution
-- =============================================================================

-- =============================================================================
-- ENUM TYPES
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE employee_status AS ENUM ('active', 'inactive', 'terminated', 'on_leave');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE employee_department AS ENUM (
        'management', 'sales', 'inventory', 'customer_service', 
        'finance', 'hr', 'it', 'logistics', 'marketing'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE transaction_type AS ENUM ('sale', 'return', 'void', 'exchange', 'refund');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE performance_period AS ENUM ('daily', 'weekly', 'monthly', 'quarterly', 'yearly');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- =============================================================================
-- EMPLOYEES TABLE - Complete Biodata
-- =============================================================================

CREATE TABLE IF NOT EXISTS employees (
    id SERIAL PRIMARY KEY,
    employee_code VARCHAR(20) UNIQUE NOT NULL,  -- e.g., LLU-DXB-001
    
    -- Personal Information
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone VARCHAR(20),
    date_of_birth DATE,
    gender VARCHAR(10),
    nationality VARCHAR(50),
    
    -- Employment Details
    date_of_joining DATE NOT NULL,
    date_of_resignation DATE,  -- NULL if still employed
    date_of_termination DATE,  -- NULL if not terminated
    
    -- Role & Assignment
    role VARCHAR(50) NOT NULL DEFAULT 'sales_executive',
    department employee_department NOT NULL DEFAULT 'sales',
    designation VARCHAR(100),
    store_id INTEGER REFERENCES stores(id),
    region_id INTEGER REFERENCES regions(id),
    reports_to INTEGER REFERENCES employees(id),  -- Manager
    
    -- Status
    status employee_status NOT NULL DEFAULT 'active',
    
    -- Additional Info
    photo_url VARCHAR(500),
    emergency_contact_name VARCHAR(100),
    emergency_contact_phone VARCHAR(20),
    address TEXT,
    
    -- Salary & Benefits (encrypted in production)
    salary_grade VARCHAR(10),
    
    -- System Fields
    user_id INTEGER REFERENCES users(id),  -- Link to auth user
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- EMPLOYEE PERFORMANCE TABLE - KPI Tracking
-- =============================================================================

CREATE TABLE IF NOT EXISTS employee_performance (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    
    -- Period
    period_type performance_period NOT NULL DEFAULT 'monthly',
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    
    -- Sales Metrics
    sales_target DECIMAL(12, 2) DEFAULT 0,
    sales_achieved DECIMAL(12, 2) DEFAULT 0,
    sales_achievement_pct DECIMAL(5, 2) GENERATED ALWAYS AS (
        CASE WHEN sales_target > 0 THEN (sales_achieved / sales_target * 100) ELSE 0 END
    ) STORED,
    
    -- Transaction Metrics
    transactions_count INTEGER DEFAULT 0,
    returns_count INTEGER DEFAULT 0,
    voids_count INTEGER DEFAULT 0,
    avg_transaction_value DECIMAL(10, 2) DEFAULT 0,
    items_sold INTEGER DEFAULT 0,
    
    -- Customer Metrics
    customers_served INTEGER DEFAULT 0,
    customer_rating DECIMAL(3, 2) DEFAULT 0,  -- 0.00 to 5.00
    complaints_received INTEGER DEFAULT 0,
    compliments_received INTEGER DEFAULT 0,
    
    -- Attendance Metrics
    days_present INTEGER DEFAULT 0,
    days_absent INTEGER DEFAULT 0,
    days_late INTEGER DEFAULT 0,
    overtime_hours DECIMAL(6, 2) DEFAULT 0,
    attendance_percentage DECIMAL(5, 2) DEFAULT 100,
    
    -- Overall Score (0-100)
    performance_score DECIMAL(5, 2) DEFAULT 0,
    performance_grade VARCHAR(2),  -- A+, A, B+, B, C, D, F
    
    -- Manager Review
    manager_comments TEXT,
    reviewed_by INTEGER REFERENCES employees(id),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    
    -- System Fields
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Ensure unique period per employee
    UNIQUE(employee_id, period_type, period_start)
);

-- =============================================================================
-- EMPLOYEE TRANSACTIONS - Transaction Attribution
-- =============================================================================

CREATE TABLE IF NOT EXISTS employee_transactions (
    id SERIAL PRIMARY KEY,
    
    -- Transaction Reference
    transaction_code VARCHAR(50) UNIQUE NOT NULL,  -- TXN-20260205-001234
    
    -- Employee Attribution
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    
    -- Transaction Details
    transaction_type transaction_type NOT NULL DEFAULT 'sale',
    transaction_date DATE NOT NULL,
    transaction_time TIME NOT NULL,
    
    -- Financial
    gross_amount DECIMAL(12, 2) NOT NULL,
    discount_amount DECIMAL(10, 2) DEFAULT 0,
    net_amount DECIMAL(12, 2) NOT NULL,
    
    -- Items
    items_count INTEGER DEFAULT 1,
    
    -- Store Context
    store_id INTEGER NOT NULL REFERENCES stores(id),
    register_id VARCHAR(20),
    
    -- Customer (optional)
    customer_id VARCHAR(50),
    payment_method VARCHAR(20),
    
    -- Status
    is_completed BOOLEAN DEFAULT TRUE,
    is_voided BOOLEAN DEFAULT FALSE,
    void_reason TEXT,
    voided_by INTEGER REFERENCES employees(id),
    
    -- System Fields
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- EMPLOYEE TRAINING & CERTIFICATIONS
-- =============================================================================

CREATE TABLE IF NOT EXISTS employee_certifications (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    
    certification_name VARCHAR(200) NOT NULL,
    issuing_authority VARCHAR(200),
    issue_date DATE NOT NULL,
    expiry_date DATE,
    certificate_url VARCHAR(500),
    status VARCHAR(20) DEFAULT 'active',  -- active, expired, revoked
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- EMPLOYEE ATTENDANCE LOG
-- =============================================================================

CREATE TABLE IF NOT EXISTS employee_attendance (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    
    attendance_date DATE NOT NULL,
    check_in_time TIMESTAMP WITH TIME ZONE,
    check_out_time TIMESTAMP WITH TIME ZONE,
    
    status VARCHAR(20) NOT NULL DEFAULT 'present',  -- present, absent, late, half_day, leave
    shift VARCHAR(20) DEFAULT 'morning',  -- morning, evening, night
    
    hours_worked DECIMAL(4, 2),
    overtime_hours DECIMAL(4, 2) DEFAULT 0,
    
    notes TEXT,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(employee_id, attendance_date)
);

-- =============================================================================
-- INDEXES FOR PERFORMANCE
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_employees_store ON employees(store_id);
CREATE INDEX IF NOT EXISTS idx_employees_role ON employees(role);
CREATE INDEX IF NOT EXISTS idx_employees_status ON employees(status);
CREATE INDEX IF NOT EXISTS idx_employees_region ON employees(region_id);
CREATE INDEX IF NOT EXISTS idx_employees_code ON employees(employee_code);

CREATE INDEX IF NOT EXISTS idx_emp_perf_employee ON employee_performance(employee_id);
CREATE INDEX IF NOT EXISTS idx_emp_perf_period ON employee_performance(period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_emp_perf_score ON employee_performance(performance_score DESC);

CREATE INDEX IF NOT EXISTS idx_emp_txn_employee ON employee_transactions(employee_id);
CREATE INDEX IF NOT EXISTS idx_emp_txn_date ON employee_transactions(transaction_date);
CREATE INDEX IF NOT EXISTS idx_emp_txn_store ON employee_transactions(store_id);
CREATE INDEX IF NOT EXISTS idx_emp_txn_type ON employee_transactions(transaction_type);

CREATE INDEX IF NOT EXISTS idx_emp_attendance_employee ON employee_attendance(employee_id);
CREATE INDEX IF NOT EXISTS idx_emp_attendance_date ON employee_attendance(attendance_date);

-- =============================================================================
-- VIEWS FOR DASHBOARD
-- =============================================================================

-- Employee Summary View
CREATE OR REPLACE VIEW employee_summary_view AS
SELECT 
    e.id,
    e.employee_code,
    e.first_name || ' ' || e.last_name AS full_name,
    e.email,
    e.role,
    e.department::TEXT,
    e.designation,
    e.status::TEXT,
    e.date_of_joining,
    e.date_of_resignation,
    s.name AS store_name,
    r.name AS region_name,
    COALESCE(
        (SELECT performance_score FROM employee_performance 
         WHERE employee_id = e.id 
         ORDER BY period_end DESC LIMIT 1), 0
    ) AS latest_performance_score,
    COALESCE(
        (SELECT performance_grade FROM employee_performance 
         WHERE employee_id = e.id 
         ORDER BY period_end DESC LIMIT 1), 'N/A'
    ) AS latest_grade,
    COALESCE(
        (SELECT SUM(net_amount) FROM employee_transactions 
         WHERE employee_id = e.id 
         AND transaction_date >= CURRENT_DATE - INTERVAL '30 days'), 0
    ) AS sales_last_30_days,
    COALESCE(
        (SELECT COUNT(*) FROM employee_transactions 
         WHERE employee_id = e.id 
         AND transaction_date >= CURRENT_DATE - INTERVAL '30 days'), 0
    ) AS transactions_last_30_days
FROM employees e
LEFT JOIN stores s ON e.store_id = s.id
LEFT JOIN regions r ON e.region_id = r.id;

-- Role Performance Summary
CREATE OR REPLACE VIEW role_performance_view AS
SELECT 
    e.role,
    COUNT(DISTINCT e.id) AS employee_count,
    ROUND(AVG(ep.performance_score), 2) AS avg_performance_score,
    ROUND(AVG(ep.sales_achieved), 2) AS avg_sales,
    ROUND(AVG(ep.customer_rating), 2) AS avg_customer_rating,
    ROUND(AVG(ep.attendance_percentage), 2) AS avg_attendance,
    SUM(ep.transactions_count) AS total_transactions,
    SUM(ep.items_sold) AS total_items_sold
FROM employees e
LEFT JOIN employee_performance ep ON e.id = ep.employee_id
WHERE e.status = 'active'
GROUP BY e.role;

-- Store Employee Performance
CREATE OR REPLACE VIEW store_employee_performance_view AS
SELECT 
    s.id AS store_id,
    s.name AS store_name,
    e.role,
    COUNT(DISTINCT e.id) AS employee_count,
    ROUND(AVG(ep.performance_score), 2) AS avg_performance,
    ROUND(SUM(ep.sales_achieved), 2) AS total_sales,
    SUM(ep.transactions_count) AS total_transactions
FROM stores s
LEFT JOIN employees e ON s.id = e.store_id AND e.status = 'active'
LEFT JOIN employee_performance ep ON e.id = ep.employee_id
    AND ep.period_end >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY s.id, s.name, e.role
ORDER BY s.id, e.role;

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
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_employees_updated_at ON employees;
CREATE TRIGGER update_employees_updated_at
    BEFORE UPDATE ON employees
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_emp_performance_updated_at ON employee_performance;
CREATE TRIGGER update_emp_performance_updated_at
    BEFORE UPDATE ON employee_performance
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- FUNCTIONS FOR PERFORMANCE CALCULATION
-- =============================================================================

CREATE OR REPLACE FUNCTION calculate_performance_grade(score DECIMAL)
RETURNS VARCHAR(2) AS $$
BEGIN
    IF score >= 95 THEN RETURN 'A+';
    ELSIF score >= 90 THEN RETURN 'A';
    ELSIF score >= 85 THEN RETURN 'B+';
    ELSIF score >= 80 THEN RETURN 'B';
    ELSIF score >= 70 THEN RETURN 'C';
    ELSIF score >= 60 THEN RETURN 'D';
    ELSE RETURN 'F';
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Function to calculate overall performance score
CREATE OR REPLACE FUNCTION calculate_performance_score(
    sales_pct DECIMAL,
    customer_rating DECIMAL,
    attendance_pct DECIMAL,
    return_rate DECIMAL
) RETURNS DECIMAL AS $$
DECLARE
    score DECIMAL;
BEGIN
    -- Weighted scoring: Sales 40%, Customer Rating 25%, Attendance 25%, Low Returns 10%
    score := (
        (LEAST(sales_pct, 150) / 150 * 40) +  -- Cap at 150% for max score
        (customer_rating / 5 * 25) +
        (attendance_pct / 100 * 25) +
        ((100 - LEAST(return_rate, 100)) / 100 * 10)  -- Lower returns = higher score
    );
    RETURN ROUND(score, 2);
END;
$$ LANGUAGE plpgsql;

COMMIT;
