-- 057_krishna_demo_tenant_guard.sql
-- E0-8 (P1): confine synthetic (generator-written) sales to the demo tenant, at the
-- database level, and make the demo-reset job possible.
--
-- WHY:
--   `services/data_generator.py` writes a fake sale every ~5-15s. Until now it picked
--   `store_id = random.randint(1, 10)` and never set `tenant_id` at all — the row landed
--   on tenant 1 only because `sales_stream_raw.tenant_id` carries `DEFAULT 1` (migration
--   010). Nothing *enforced* that. Any future writer that passes an explicit tenant_id,
--   or any change to that column default, silently starts writing fabricated revenue into
--   a paying tenant's numbers. The config layer already refuses to run the generator
--   outside DEMO_MODE (config.validate_security), but a process-level flag is not a
--   row-level guarantee, and the blueprint asks for both a guard and a test.
--
-- WHAT:
--   1. `sales_stream_raw.is_synthetic` — an explicit provenance flag. Real streamed sales
--      (a future POS connector, E2-1) write FALSE; the generator writes TRUE.
--   2. `demo_tenant_id()` — resolves the demo tenant by slug, falling back to 1.
--   3. A BEFORE INSERT OR UPDATE trigger that RAISES if a synthetic row targets any
--      tenant other than the demo tenant. This is the guarantee: no code path, ORM or
--      raw SQL, can fabricate sales for a real tenant.
--
-- The trigger reads only `tenants`, which carries no RLS policy (012 enables RLS on
-- users/stores/items/sales_*, not tenants), so it needs no SECURITY DEFINER and stays
-- correct whether or not the caller has bound `app.tenant_id`.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS / CREATE OR REPLACE / DROP TRIGGER IF EXISTS.
-- Additive only — `is_synthetic` defaults FALSE so existing readers are unaffected.

-- ---------------------------------------------------------------------------
-- 1. Provenance flag
-- ---------------------------------------------------------------------------
ALTER TABLE sales_stream_raw
    ADD COLUMN IF NOT EXISTS is_synthetic BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN sales_stream_raw.is_synthetic IS
    'TRUE = fabricated by services/data_generator.py (demo tenant only, enforced by '
    'trg_sales_stream_raw_confine_synthetic). FALSE = a real streamed sale.';

-- ---------------------------------------------------------------------------
-- 2. Demo tenant resolution
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION demo_tenant_id() RETURNS INTEGER AS $$
    SELECT COALESCE(
        (SELECT id FROM tenants WHERE slug = 'demo' ORDER BY id LIMIT 1),
        1
    );
$$ LANGUAGE sql STABLE;

-- ---------------------------------------------------------------------------
-- 3. Backfill: every row written before this migration came from the generator
--    (sales_stream_raw has had exactly one writer). Only claim the ones that sit
--    on the demo tenant — if a row is already on a real tenant, leave it FALSE and
--    let the operator investigate rather than silently relabelling real data.
-- ---------------------------------------------------------------------------
UPDATE sales_stream_raw
   SET is_synthetic = TRUE
 WHERE tenant_id = demo_tenant_id()
   AND is_synthetic = FALSE;

-- Reset job scans by (tenant_id, is_synthetic, timestamp); partial index keeps it cheap
-- and costs nothing once real streamed rows outnumber synthetic ones.
CREATE INDEX IF NOT EXISTS idx_sales_stream_synthetic
    ON sales_stream_raw (tenant_id, timestamp)
    WHERE is_synthetic;

-- ---------------------------------------------------------------------------
-- 4. The guard
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION sales_stream_raw_confine_synthetic()
RETURNS TRIGGER AS $$
DECLARE
    demo_id INTEGER := demo_tenant_id();
BEGIN
    IF NEW.is_synthetic AND NEW.tenant_id IS DISTINCT FROM demo_id THEN
        RAISE EXCEPTION
            'synthetic sale rejected: tenant_id % is not the demo tenant (%)',
            NEW.tenant_id, demo_id
            USING ERRCODE = 'check_violation',
                  HINT = 'Synthetic sales may only be written to the demo tenant. '
                         'See E0-8 / services/data_generator.py.';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sales_stream_raw_confine_synthetic ON sales_stream_raw;
CREATE TRIGGER trg_sales_stream_raw_confine_synthetic
    BEFORE INSERT OR UPDATE ON sales_stream_raw
    FOR EACH ROW
    EXECUTE FUNCTION sales_stream_raw_confine_synthetic();

DO $$ BEGIN
    RAISE NOTICE 'sales_stream_raw: synthetic rows confined to demo tenant %', demo_tenant_id();
END $$;
