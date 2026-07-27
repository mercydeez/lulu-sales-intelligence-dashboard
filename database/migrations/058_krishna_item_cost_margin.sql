-- 058_krishna_item_cost_margin.sql
-- E2-3 (P0): effective-dated cost price + margin.
--
-- WHY:
--   Cost lived only on `inventory.unit_cost` — one mutable number per store-item,
--   with no history. `roi.py` therefore computed 90-day COGS as
--   `AVG(NULLIF(unit_cost,0))` blended across every store and applied that ONE
--   present-day number to ninety days of past sales. If a supplier raised prices
--   last month, historical margin was silently wrong, and there was no way to say
--   what an item actually cost on the day it sold.
--
--   Cost is a time series, not a scalar. This makes it one.
--
-- WHAT:
--   1. `item_costs` — the effective-dated source of truth: one row per cost period
--      per (tenant, item), with a GiST exclusion constraint that makes overlapping
--      periods impossible (you cannot have two costs in effect on the same day).
--   2. `items.unit_cost_aed` — the CURRENT cost, denormalised from item_costs by a
--      trigger. This is the column the blueprint names; it keeps the "inventory at
--      cost" style joins cheap. NULL = cost unknown.
--   3. `item_cost_at(tenant, item, date)` — the point-in-time resolver.
--   4. `metric_margin_fact` — the E6-1-style view that joins each sale to the cost
--      that was in effect ON ITS OWN DATE, yielding honest COGS and gross margin.
--      Margin is NULL (never 0, never fabricated) where no cost covers that day.
--
-- HONESTY:
--   The backfill seeds item_costs from the existing blended inventory cost and
--   labels it `source='backfill_inventory'` — so a reader can always tell a real
--   dated cost from a derived one. Rows with no cost stay NULL and every reader
--   must keep returning the `needs: cost` state rather than inventing a margin.
--
-- Idempotent: IF NOT EXISTS / CREATE OR REPLACE / guarded constraint + backfill.
-- Additive only — no existing column or view changes shape.

-- btree_gist lets the exclusion constraint mix `=` on ints with `&&` on a range.
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- ---------------------------------------------------------------------------
-- 1. The effective-dated cost table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS item_costs (
    id            SERIAL PRIMARY KEY,
    tenant_id     INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id),
    item_id       INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    unit_cost_aed NUMERIC(12, 4) NOT NULL CHECK (unit_cost_aed >= 0),
    valid_from    DATE NOT NULL,
    valid_until   DATE,                       -- NULL = still in effect
    source        VARCHAR(40) NOT NULL DEFAULT 'import',
    created_at    TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT item_costs_range_ordered
        CHECK (valid_until IS NULL OR valid_until > valid_from)
);

COMMENT ON TABLE item_costs IS
    'Effective-dated unit cost per (tenant, item). Source of truth for COGS/margin; '
    'items.unit_cost_aed is a trigger-maintained denormalisation of the open period.';
COMMENT ON COLUMN item_costs.source IS
    'Provenance: ''import'' (tenant-supplied), ''backfill_inventory'' (derived from the '
    'blended inventory.unit_cost at migration time), ''pos'' (connector). Never guess.';

-- Two costs may not be in effect on the same day for the same item.
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'item_costs_no_overlap'
    ) THEN
        ALTER TABLE item_costs ADD CONSTRAINT item_costs_no_overlap
            EXCLUDE USING gist (
                tenant_id WITH =,
                item_id   WITH =,
                daterange(valid_from, valid_until, '[)') WITH &&
            );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_item_costs_tenant ON item_costs(tenant_id);
-- The point-in-time lookup: (tenant, item) then range-scan valid_from.
CREATE INDEX IF NOT EXISTS idx_item_costs_lookup
    ON item_costs(tenant_id, item_id, valid_from DESC);

-- RLS, matching migrations 010-012 for every tenant-scoped table.
ALTER TABLE item_costs ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'item_costs' AND policyname = 'tenant_isolation'
    ) THEN
        CREATE POLICY tenant_isolation ON item_costs
            USING (tenant_id = current_tenant_id())
            WITH CHECK (tenant_id = current_tenant_id());
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 2. items.unit_cost_aed — the current cost (the column the blueprint names)
-- ---------------------------------------------------------------------------
ALTER TABLE items ADD COLUMN IF NOT EXISTS unit_cost_aed NUMERIC(12, 4);

COMMENT ON COLUMN items.unit_cost_aed IS
    'CURRENT unit cost in AED, denormalised from item_costs by trg_item_costs_sync_current. '
    'NULL = cost unknown: readers must return the `needs: cost` state, never a fabricated '
    'margin. For point-in-time cost use item_cost_at() / metric_margin_fact.';

-- ---------------------------------------------------------------------------
-- 3. Point-in-time resolver
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION item_cost_at(p_tenant_id INTEGER, p_item_id INTEGER, p_date DATE)
RETURNS NUMERIC AS $$
    SELECT c.unit_cost_aed
      FROM item_costs c
     WHERE c.tenant_id = p_tenant_id
       AND c.item_id   = p_item_id
       AND p_date     >= c.valid_from
       AND (c.valid_until IS NULL OR p_date < c.valid_until)
     LIMIT 1;
$$ LANGUAGE sql STABLE;

COMMENT ON FUNCTION item_cost_at(INTEGER, INTEGER, DATE) IS
    'The unit cost in effect for this item on this date, or NULL when none covers it. '
    'The exclusion constraint guarantees at most one match.';

-- ---------------------------------------------------------------------------
-- 3b. set_item_cost() — the ONLY sane way to record a new cost.
--
--     The exclusion constraint makes overlapping periods impossible, and the
--     current period is open-ended (valid_until NULL), so a naive INSERT of a new
--     cost ALWAYS conflicts. Recording a price change means closing the period
--     that was in force and opening a new one — classic slowly-changing-dimension
--     behaviour. Callers (CSV import, POS connector) must go through this instead
--     of hand-rolling the close/insert and getting the boundaries wrong.
--
--     Semantics: "this item costs X from p_from onward", superseding anything
--     that was in effect from p_from. Boundaries are half-open [from, until).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_item_cost(
    p_tenant_id INTEGER,
    p_item_id   INTEGER,
    p_cost      NUMERIC,
    p_from      DATE DEFAULT CURRENT_DATE,
    p_source    VARCHAR DEFAULT 'import'
) RETURNS VOID AS $$
BEGIN
    -- Any period already starting at/after p_from is superseded outright.
    DELETE FROM item_costs
     WHERE tenant_id = p_tenant_id AND item_id = p_item_id
       AND valid_from >= p_from;

    -- Close the period straddling p_from so the new one can start there.
    UPDATE item_costs
       SET valid_until = p_from
     WHERE tenant_id = p_tenant_id AND item_id = p_item_id
       AND valid_from < p_from
       AND (valid_until IS NULL OR valid_until > p_from);

    INSERT INTO item_costs (tenant_id, item_id, unit_cost_aed, valid_from, valid_until, source)
    VALUES (p_tenant_id, p_item_id, p_cost, p_from, NULL, p_source);
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION set_item_cost(INTEGER, INTEGER, NUMERIC, DATE, VARCHAR) IS
    'Record a cost effective from p_from onward: closes the straddling period and '
    'supersedes any later ones. The only supported way to write item_costs.';

-- ---------------------------------------------------------------------------
-- 4. Keep items.unit_cost_aed in step with the open cost period
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION item_costs_sync_current() RETURNS TRIGGER AS $$
DECLARE
    target_tenant INTEGER := COALESCE(NEW.tenant_id, OLD.tenant_id);
    target_item   INTEGER := COALESCE(NEW.item_id,   OLD.item_id);
BEGIN
    UPDATE items
       SET unit_cost_aed = item_cost_at(target_tenant, target_item, CURRENT_DATE)
     WHERE id = target_item
       AND tenant_id = target_tenant;
    RETURN NULL;  -- AFTER trigger
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_item_costs_sync_current ON item_costs;
CREATE TRIGGER trg_item_costs_sync_current
    AFTER INSERT OR UPDATE OR DELETE ON item_costs
    FOR EACH ROW EXECUTE FUNCTION item_costs_sync_current();

-- ---------------------------------------------------------------------------
-- 5. Backfill from the blended inventory cost so existing tenants keep working.
--    valid_from reaches back past the earliest sale so historical COGS resolves;
--    the row is labelled so nobody mistakes it for a real dated cost.
-- ---------------------------------------------------------------------------
INSERT INTO item_costs (tenant_id, item_id, unit_cost_aed, valid_from, source)
SELECT it.tenant_id,
       it.id,
       ROUND(AVG(NULLIF(inv.unit_cost, 0))::numeric, 4),
       COALESCE((SELECT MIN(date) FROM sales_historical), CURRENT_DATE) - INTERVAL '1 day',
       'backfill_inventory'
  FROM items it
  JOIN inventory inv ON inv.item_id = it.id
 WHERE NOT EXISTS (SELECT 1 FROM item_costs c WHERE c.item_id = it.id AND c.tenant_id = it.tenant_id)
 GROUP BY it.tenant_id, it.id
HAVING AVG(NULLIF(inv.unit_cost, 0)) > 0;

-- ---------------------------------------------------------------------------
-- 6. metric_margin_fact — each sale joined to the cost in effect ON ITS OWN DATE.
--    Mirrors the E6-1 metric_* convention: tenant_id is a COLUMN (callers scope
--    with WHERE), security_invoker so RLS follows the caller.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW metric_margin_fact AS
SELECT
    s.tenant_id,
    s.date,
    s.store_id,
    s.item_id,
    i.category,
    s.sales                                    AS units,
    i.unit_price_aed,
    s.sales::numeric * i.unit_price_aed        AS revenue_aed,
    c.unit_cost_aed,
    c.source                                   AS cost_source,
    -- NULL, never 0, when no cost covers this sale's date.
    s.sales::numeric * c.unit_cost_aed         AS cogs_aed,
    s.sales::numeric * (i.unit_price_aed - c.unit_cost_aed) AS gross_margin_aed
FROM sales_fact_view s
JOIN items i
  ON i.id = s.item_id AND i.tenant_id = s.tenant_id
LEFT JOIN item_costs c
  ON c.tenant_id = s.tenant_id
 AND c.item_id   = s.item_id
 AND s.date     >= c.valid_from
 AND (c.valid_until IS NULL OR s.date < c.valid_until);

ALTER VIEW metric_margin_fact SET (security_invoker = true);

COMMENT ON VIEW metric_margin_fact IS
    'E2-3: point-in-time COGS + gross margin. cogs_aed/gross_margin_aed are NULL where '
    'no cost period covers the sale date — readers must surface `needs: cost`, not zero.';

DO $$
DECLARE n INTEGER;
BEGIN
    SELECT COUNT(*) INTO n FROM item_costs;
    RAISE NOTICE 'item_costs seeded with % cost periods; metric_margin_fact ready', n;
END $$;
