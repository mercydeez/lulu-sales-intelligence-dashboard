-- 028_sage_domains.sql
-- Sage v2 in-depth semantic layer: the domains a multi-part business question
-- spans beyond sales — distributors+zones, CRM pipeline, online pricing, company
-- targets, and a documents store (for RAG). Each table is tenant-stamped + RLS'd,
-- and exposed as a curated, tenant-filtered sage_* view (definer + current_tenant_id()
-- filter, same safe pattern as migration 023) that the least-privilege sage_ro role
-- and the NL->SQL guard read. Seeded with realistic data so it's demonstrable.

-- ---------------------------------------------------------------------------
-- Zones (a store/distributor dimension). Add to stores + assign.
-- ---------------------------------------------------------------------------
ALTER TABLE stores ADD COLUMN IF NOT EXISTS zone TEXT;
UPDATE stores SET zone = CASE
    WHEN name ILIKE '%Sharjah%' OR name ILIKE '%Ajman%' OR name ILIKE '%Nahda%'
         OR name ILIKE '%Ras Al Khaimah%'                 THEN 'North'
    WHEN name ILIKE '%Abu Dhabi%' OR name ILIKE '%Mushrif%' OR name ILIKE '%Wahda%'
         OR name ILIKE '%Khalidiyah%'                      THEN 'West'
    WHEN name ILIKE '%Barsha%' OR name ILIKE '%Deira%' OR name ILIKE '%Karama%'
         OR name ILIKE '%Marina%' OR name ILIKE '%Central%' THEN 'Central'
    ELSE COALESCE(zone, 'Central')
END
WHERE zone IS NULL OR zone = '';

-- ---------------------------------------------------------------------------
-- Distributors (channel partners), zone-scoped.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS distributors (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   INTEGER NOT NULL DEFAULT 1,
    name        TEXT NOT NULL,
    zone        TEXT NOT NULL,
    contact     TEXT,
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- CRM pipeline opportunities, zone + stage + expected revenue.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm_opportunities (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        INTEGER NOT NULL DEFAULT 1,
    name             TEXT NOT NULL,
    zone             TEXT NOT NULL,
    stage            TEXT NOT NULL,           -- Lead|Qualified|Proposal|Won|Lost
    expected_revenue NUMERIC NOT NULL DEFAULT 0,
    distributor_id   BIGINT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Online (e-commerce) selling prices per item + channel.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS online_prices (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   INTEGER NOT NULL DEFAULT 1,
    item_id     INTEGER NOT NULL,
    channel     TEXT NOT NULL DEFAULT 'online',
    price_aed   NUMERIC NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Company targets (the structured side of the strategy document).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS company_targets (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   INTEGER NOT NULL DEFAULT 1,
    metric      TEXT NOT NULL,               -- e.g. 'revenue_target'
    label       TEXT NOT NULL,               -- e.g. '2030 revenue target'
    year        INTEGER NOT NULL,
    value       NUMERIC NOT NULL,
    unit        TEXT NOT NULL DEFAULT 'AED',
    source_doc  TEXT
);

-- ---------------------------------------------------------------------------
-- Documents store (for RAG). Postgres full-text now; pgvector column added later.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   INTEGER NOT NULL DEFAULT 1,
    title       TEXT NOT NULL,
    chunk_no    INTEGER NOT NULL DEFAULT 0,
    content     TEXT NOT NULL,
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_documents_tsv ON documents USING GIN (tsv);
CREATE INDEX IF NOT EXISTS idx_documents_tenant ON documents (tenant_id);

-- ---------------------------------------------------------------------------
-- RLS on every new tenant table (keyed off the app.tenant_id GUC, migration 012).
-- ---------------------------------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['distributors','crm_opportunities','online_prices','company_targets','documents']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_tenant_id()) '
            'WITH CHECK (tenant_id = current_tenant_id())', t);
    END LOOP;
END $$;

-- ---------------------------------------------------------------------------
-- Seed (tenant 1 = Meridian). Idempotent-ish: only seed when empty.
-- ---------------------------------------------------------------------------
INSERT INTO distributors (tenant_id, name, zone)
SELECT 1, name, zone FROM (VALUES
    ('Aravalli Traders','North'), ('Himalaya Mercantile','North'),
    ('Kapoor Trade House','North'), ('Northline Agencies','North'),
    ('Punjab Provision Hub','North'), ('Rohtak Supply Syndicate','North'),
    ('Sharma Distribution Co','North'), ('Yamuna Sales Corp','North'),
    ('Gulf Coast Distributors','West'), ('Marina Wholesale','West'),
    ('Desert Star Trading','Central'), ('Creek Supply Co','Central'),
    ('Southern Cross Traders','South'), ('Eastgate Mercantile','East')
) AS d(name, zone)
WHERE NOT EXISTS (SELECT 1 FROM distributors WHERE tenant_id = 1);

INSERT INTO crm_opportunities (tenant_id, name, zone, stage, expected_revenue)
SELECT 1, name, zone, stage, rev FROM (VALUES
    ('Bulk grocery contract - Sharjah','North','Proposal', 845000),
    ('New hypermarket supply - Ajman','North','Qualified', 612000),
    ('Ramadan promo pipeline - North','North','Lead', 430000),
    ('Distributor onboarding - RAK','North','Won', 1560836),
    ('Catering chain - North','North','Proposal', 0),
    ('Office pantry deal - Dubai','Central','Qualified', 980000),
    ('Mall kiosk rollout - Central','Central','Proposal', 1240000),
    ('Hotel supply - Abu Dhabi','West','Won', 2100000),
    ('Airport retail - West','West','Lead', 760000),
    ('School supply - South','South','Qualified', 320000)
) AS o(name, zone, stage, rev)
WHERE NOT EXISTS (SELECT 1 FROM crm_opportunities WHERE tenant_id = 1);

-- Online prices: every tenant-1 item, ~8% online premium over the shelf price.
INSERT INTO online_prices (tenant_id, item_id, channel, price_aed)
SELECT 1, i.id, 'online', ROUND(i.unit_price_aed * 1.08, 2)
FROM items i
WHERE i.tenant_id = 1
  AND NOT EXISTS (SELECT 1 FROM online_prices WHERE tenant_id = 1);

INSERT INTO company_targets (tenant_id, metric, label, year, value, unit, source_doc)
SELECT 1, 'revenue_target', '2030 revenue target', 2030, 8000000000, 'AED', 'Strategy 2025-2030'
WHERE NOT EXISTS (SELECT 1 FROM company_targets WHERE tenant_id = 1 AND metric = 'revenue_target' AND year = 2030);

INSERT INTO documents (tenant_id, title, chunk_no, content)
SELECT 1, 'Strategy 2025-2030', n, c FROM (VALUES
    (0, 'Meridian Strategy 2025-2030. Our north-star ambition: by 2030 the company targets total revenue of AED 8 billion (AED 8,000,000,000), roughly tripling from the 2025 base.'),
    (1, 'Growth pillars: deepen the North zone distributor network, expand e-commerce (online) share to 25% of revenue, and grow private-label categories.'),
    (2, 'The CRM pipeline is the leading indicator for the 2030 target; expected revenue across active opportunities is reviewed monthly by zone.')
) AS d(n, c)
WHERE NOT EXISTS (SELECT 1 FROM documents WHERE tenant_id = 1 AND title = 'Strategy 2025-2030');

-- ---------------------------------------------------------------------------
-- Curated, tenant-filtered sage_* views (definer; current_tenant_id() filter).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW sage_distributors AS
SELECT id AS distributor_id, name AS distributor_name, zone, active
FROM distributors WHERE tenant_id = current_tenant_id();

CREATE OR REPLACE VIEW sage_crm_pipeline AS
SELECT id AS opportunity_id, name AS opportunity_name, zone, stage,
       expected_revenue, distributor_id
FROM crm_opportunities WHERE tenant_id = current_tenant_id();

CREATE OR REPLACE VIEW sage_online_prices AS
SELECT o.item_id, i.name AS item_name, i.category, o.channel, o.price_aed
FROM online_prices o
JOIN items i ON i.id = o.item_id AND i.tenant_id = o.tenant_id
WHERE o.tenant_id = current_tenant_id();

CREATE OR REPLACE VIEW sage_targets AS
SELECT metric, label, year, value, unit, source_doc
FROM company_targets WHERE tenant_id = current_tenant_id();

CREATE OR REPLACE VIEW sage_zones AS
SELECT DISTINCT zone FROM stores WHERE tenant_id = current_tenant_id() AND zone IS NOT NULL;

-- Also expose the zone on the stores semantic view (recreate sage_stores w/ zone).
CREATE OR REPLACE VIEW sage_stores AS
SELECT id AS store_id, name AS store_name, location, zone
FROM stores WHERE tenant_id = current_tenant_id();

-- Grant the least-privilege Sage role read on the new views.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sage_ro') THEN
        GRANT SELECT ON sage_distributors, sage_crm_pipeline, sage_online_prices,
                        sage_targets, sage_zones, sage_stores TO sage_ro;
    END IF;
END $$;

DO $$ BEGIN RAISE NOTICE 'Sage v2 domains ready (distributors, crm, online prices, targets, documents)'; END $$;
