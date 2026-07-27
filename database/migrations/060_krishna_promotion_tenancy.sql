-- 060_krishna_promotion_tenancy.sql
-- Tenant-scope the stored promotions (security fix), found while building E7-5.
--
-- WHY:
--   `promotions` (migration 003) predates multi-tenancy (010-012) and was never
--   stamped with a tenant_id. Its write endpoints check only the caller's ROLE:
--
--       if not permissions.can_manage_promotions: 403
--       UPDATE promotions SET ... WHERE id = :promo_id      -- no tenant filter
--
--   So a promotions manager in tenant A could edit, approve or cancel tenant B's
--   promotion simply by guessing its id. Role is not a boundary; tenant is.
--
--   Every other tenant-scoped table already carries tenant_id + an RLS policy
--   (010-012). This brings promotions into line, and gives E7-5's uplift
--   measurement a table it can safely scope.
--
-- WHAT:
--   1. promotions.tenant_id, backfilled to the demo tenant (the only rows that
--      could exist today), NOT NULL, FK, indexed.
--   2. RLS on promotions (by tenant_id) and on its two line tables
--      (promotion_items / promotion_stores) through the parent — the same
--      EXISTS pattern migration 020 uses for purchase_order_lines.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS / DROP POLICY IF EXISTS.
-- Additive only. The routes are tenant-filtered in the same change.

-- ---------------------------------------------------------------------------
-- 1. Stamp the tenant
-- ---------------------------------------------------------------------------
ALTER TABLE promotions
    ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);

COMMENT ON COLUMN promotions.tenant_id IS
    'Owning tenant. Added by migration 060: the write endpoints previously scoped on '
    'role alone, so any promotions manager could edit another tenant''s promotion by id.';

CREATE INDEX IF NOT EXISTS idx_promotions_tenant ON promotions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_promotions_window ON promotions(tenant_id, start_date, end_date);

-- ---------------------------------------------------------------------------
-- 2. RLS — header by tenant_id, line tables through the parent (migration 020)
-- ---------------------------------------------------------------------------
ALTER TABLE promotions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON promotions;
CREATE POLICY tenant_isolation ON promotions
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

ALTER TABLE promotion_items ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON promotion_items;
CREATE POLICY tenant_isolation ON promotion_items USING (
    EXISTS (SELECT 1 FROM promotions p
            WHERE p.id = promotion_id AND p.tenant_id = current_tenant_id()));

ALTER TABLE promotion_stores ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON promotion_stores;
CREATE POLICY tenant_isolation ON promotion_stores USING (
    EXISTS (SELECT 1 FROM promotions p
            WHERE p.id = promotion_id AND p.tenant_id = current_tenant_id()));

ALTER TABLE promotions       FORCE ROW LEVEL SECURITY;
ALTER TABLE promotion_items  FORCE ROW LEVEL SECURITY;
ALTER TABLE promotion_stores FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    RAISE NOTICE 'promotions is now tenant-scoped (RLS); the write routes filter by tenant too.';
END $$;
