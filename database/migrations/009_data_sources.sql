-- =============================================================================
-- Migration 009: data source registry (pluggable "connect your database")
-- =============================================================================
-- Lets a super-admin register external databases (Postgres now, Mongo later) and
-- point the dashboard at them. One row is the built-in synthetic demo. The
-- connection string is stored Fernet-encrypted (services/data_sources.py); the
-- `mapping` JSONB maps the source's columns to the dashboard's canonical fields
-- (date, store, item, category, quantity, price).

CREATE TABLE IF NOT EXISTS data_sources (
    id SERIAL PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    type VARCHAR(20) NOT NULL DEFAULT 'postgres',   -- builtin | postgres | mongo
    connection_enc TEXT,                            -- Fernet-encrypted DSN (null for builtin)
    mapping JSONB NOT NULL DEFAULT '{}'::jsonb,     -- canonical field -> source column
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(20) NOT NULL DEFAULT 'untested', -- untested | ok | error
    last_tested_at TIMESTAMP WITH TIME ZONE,
    last_error TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- At most one active source at a time.
CREATE UNIQUE INDEX IF NOT EXISTS uq_data_sources_one_active
    ON data_sources (is_active) WHERE is_active;

-- Seed the built-in demo source (active by default) once.
INSERT INTO data_sources (name, type, is_active, status, mapping)
SELECT 'Built-in demo (Lulu synthetic)', 'builtin', TRUE, 'ok', '{}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM data_sources WHERE type = 'builtin');
