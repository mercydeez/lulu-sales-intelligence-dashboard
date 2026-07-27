-- 072 — Platform Console foundation: a REAL platform-operator boundary.
--
-- WHY. Today `super_admin` doubles as both "owner of one tenant" (every self-signup
-- owner is created super_admin by tenant_provisioning.create_tenant_with_owner) AND
-- "operator of the whole platform" — the cross-tenant routes (/api/tenants list,
-- metrics, provisioning) gate only on role == 'super_admin', so any self-signup
-- owner satisfies the same check as the platform team. The Platform Console
-- (per-tenant customization, bespoke-request ledger, ops actions) needs a boundary
-- that tenant admins can NEVER cross.
--
-- WHAT. A per-user flag, not a new role: the user_role enum stays untouched (SSO/
-- SCIM JIT clamping, permission aggregation and the role experience all key off the
-- existing enum; adding an enum value would ripple through all of them). The flag is
-- additive — a platform developer keeps their normal role for everything else.
--
-- WHO. Seeded for the three platform developers (the demo-workspace accounts the
-- team actually uses). Production additionally AND-gates on the
-- PLATFORM_DEVELOPER_EMAILS env allowlist (services/platform_access.py), so a
-- compromised DB row alone cannot mint a platform developer where the allowlist is
-- set. Fail-closed: no flag -> no access, regardless of role.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS / UPDATE by email is naturally re-runnable.

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_platform_developer BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN users.is_platform_developer IS
    'Platform-operator boundary (Platform Console). TRUE only for the vendor''s own '
    'developers — never for tenant admins. Checked by services/platform_access.py, '
    'which may additionally require membership in the PLATFORM_DEVELOPER_EMAILS '
    'allowlist. A tenant super_admin does NOT imply this.';

-- The three platform developers (Atharva / Krishna / Yash).
UPDATE users SET is_platform_developer = TRUE
 WHERE email IN ('atharva@retaildemo.app', 'krishna@retaildemo.app', 'yash@retaildemo.app');

DO $$ BEGIN
    RAISE NOTICE 'users.is_platform_developer ready; platform-operator boundary is now a per-user flag, fail-closed';
END $$;
