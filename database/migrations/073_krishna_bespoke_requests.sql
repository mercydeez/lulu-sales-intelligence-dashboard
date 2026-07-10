-- 073 — Platform Console: the BESPOKE REQUEST LEDGER ("Rolls-Royce" service).
--
-- WHY. When a client asks for something the product does not have, that request
-- must not live in a developer's inbox or a Slack thread — it must be RECORDED,
-- tracked through an explicit delivery pipeline, and auditable end to end. This
-- table is that ledger. A platform developer (services/platform_access.py — the
-- flag + allowlist boundary from migration 072) records the ask verbatim, scopes
-- it, and walks it through: requested -> scoped -> approved -> building ->
-- delivered, with declined reachable from every non-terminal state. The state
-- machine itself is enforced in services/bespoke.py (an illegal jump such as
-- requested -> delivered is refused); the DB enforces the two PROOF invariants
-- below so not even a buggy writer can record a claim without its evidence.
--
-- HONESTY INVARIANTS (brand rule: status claims must carry proof):
--   * a row may not claim `delivered` without a delivered_at timestamp;
--   * a row may not claim `declined` without scoping_notes saying why.
--
-- TENANCY. tenant_id is NULLABLE ON DELETE SET NULL: a bespoke ask may arrive
-- before the prospect is provisioned as a tenant, and the ledger must survive a
-- tenant being deleted (the history of what was asked for is platform knowledge).
--
-- THIS IS A CROSS-TENANT CONTROL-PLANE TABLE — deliberately NO RLS policy, same
-- as tenant_provisioning (068): it describes platform-level work items spanning
-- tenants and prospects, and access is gated in the route layer by
-- require_platform_developer (fail-closed flag + allowlist). See the REVOKE
-- block below for the matching privilege boundary.

BEGIN;

CREATE TABLE IF NOT EXISTS bespoke_requests (
    id                 SERIAL PRIMARY KEY,
    -- Nullable on purpose: a request may predate the tenant it is for.
    tenant_id          INTEGER NULL REFERENCES tenants(id) ON DELETE SET NULL,
    title              TEXT NOT NULL,
    -- The client's ask, recorded verbatim — the source of truth for scoping.
    client_description TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'requested'
                         CHECK (status IN ('requested', 'scoped', 'approved',
                                           'building', 'delivered', 'declined')),
    priority           TEXT NOT NULL DEFAULT 'medium'
                         CHECK (priority IN ('low', 'medium', 'high', 'vip')),
    scoping_notes      TEXT,
    estimate           TEXT,
    -- Optional AI-drafted scoping suggestion; advisory only, never authoritative.
    ai_suggestion      JSONB,
    delivered_at       TIMESTAMPTZ,
    created_by         TEXT,
    updated_by         TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- PROOF CHECK 1: "delivered" is a claim — it must carry its timestamp.
ALTER TABLE bespoke_requests DROP CONSTRAINT IF EXISTS bespoke_delivered_has_timestamp;
ALTER TABLE bespoke_requests
    ADD CONSTRAINT bespoke_delivered_has_timestamp
    CHECK (status <> 'delivered' OR delivered_at IS NOT NULL);

-- PROOF CHECK 2: declining a client's ask without a recorded reason is not
-- actionable and not honest — scoping_notes must say why.
ALTER TABLE bespoke_requests DROP CONSTRAINT IF EXISTS bespoke_declined_has_reason;
ALTER TABLE bespoke_requests
    ADD CONSTRAINT bespoke_declined_has_reason
    CHECK (status <> 'declined' OR scoping_notes IS NOT NULL);

-- SECURITY: revoke the tenant-request role's access. Migration 020 set DEFAULT
-- PRIVILEGES in schema public granting DML on every NEW table (and USAGE/SELECT
-- on every new sequence) to app_rw — the role the tenant request path runs as.
-- This ledger is cross-tenant control-plane data with NO RLS policy, so if
-- app_rw kept those default grants, any future tenant-facing query bug could
-- read (or write) every client's bespoke asks across tenants. Revoking here
-- means even a buggy tenant-path query fails closed with a permission error.
-- The app's OWNER session (which the platform routes use) is unaffected.
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
        REVOKE ALL ON bespoke_requests FROM app_rw;
        REVOKE ALL ON SEQUENCE bespoke_requests_id_seq FROM app_rw;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_bespoke_requests_status ON bespoke_requests (status);
CREATE INDEX IF NOT EXISTS ix_bespoke_requests_tenant ON bespoke_requests (tenant_id);

COMMIT;

DO $$ BEGIN
    RAISE NOTICE 'bespoke request ledger ready: proof-carrying statuses, app_rw revoked (platform developers only)';
END $$;
