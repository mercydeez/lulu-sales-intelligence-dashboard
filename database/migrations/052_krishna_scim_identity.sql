-- 052_krishna_scim_identity.sql
-- E5-1c SCIM enterprise provisioning (Krishna). Additive, idempotent.
--
-- Adds the backend tables for SCIM 2.0 user/group lifecycle provisioning:
--   * tenant_scim_tokens   — per-tenant bearer tokens, HASHED at rest (never raw)
--   * scim_external_users  — links an IdP-provisioned identity to a local user
--   * scim_groups / scim_group_memberships / scim_group_role_mappings — minimal
--     group support (role mapping is OFF by default and can never grant admin).
--
-- Schema uses INTEGER/SERIAL keys to match this repo (users.id, tenants.id are
-- SERIAL — NOT UUID). No secrets, no demo data. Read on the SCIM protocol path,
-- which is tenant-scoped by an explicit tenant_id filter (no RLS on this
-- pre-app boundary, same model as tenant_sso_providers). See docs/security/SCIM.md.

-- ---------------------------------------------------------------------------
-- Per-tenant SCIM bearer tokens (hash + prefix only; raw shown once at creation).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenant_scim_tokens (
    id                    SERIAL PRIMARY KEY,
    tenant_id             INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name                  TEXT NOT NULL,
    token_hash            TEXT NOT NULL,
    token_prefix          TEXT,
    scopes                TEXT NOT NULL DEFAULT 'scim:read scim:write',
    created_by_user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    rotated_from_token_id INTEGER REFERENCES tenant_scim_tokens(id) ON DELETE SET NULL,
    last_used_at          TIMESTAMPTZ,
    expires_at            TIMESTAMPTZ,
    revoked_at            TIMESTAMPTZ,
    revoked_by_user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tenant_scim_tokens_tenant  ON tenant_scim_tokens(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_scim_tokens_hash    ON tenant_scim_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_tenant_scim_tokens_active  ON tenant_scim_tokens(tenant_id, revoked_at);

-- ---------------------------------------------------------------------------
-- SCIM external users (IdP resource <-> local user). userName is tenant-scoped.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scim_external_users (
    id             SERIAL PRIMARY KEY,
    tenant_id      INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id        INTEGER REFERENCES users(id) ON DELETE CASCADE,
    external_id    TEXT,
    scim_user_name TEXT NOT NULL,
    raw_profile    JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_synced_at TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_scim_external_users_tenant_username UNIQUE (tenant_id, scim_user_name)
);

-- external_id unique per tenant only when present (partial unique index).
CREATE UNIQUE INDEX IF NOT EXISTS uq_scim_external_users_tenant_extid
    ON scim_external_users(tenant_id, external_id) WHERE external_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_scim_external_users_user ON scim_external_users(user_id);

-- ---------------------------------------------------------------------------
-- Minimal SCIM group support (role mapping OFF by default; never grants admin).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scim_groups (
    id           SERIAL PRIMARY KEY,
    tenant_id    INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    external_id  TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_scim_groups_tenant_name UNIQUE (tenant_id, display_name)
);
CREATE INDEX IF NOT EXISTS idx_scim_groups_tenant ON scim_groups(tenant_id);

CREATE TABLE IF NOT EXISTS scim_group_memberships (
    id         SERIAL PRIMARY KEY,
    tenant_id  INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    group_id   INTEGER NOT NULL REFERENCES scim_groups(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_scim_group_membership UNIQUE (group_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_scim_group_memberships_group ON scim_group_memberships(group_id);

CREATE TABLE IF NOT EXISTS scim_group_role_mappings (
    id         SERIAL PRIMARY KEY,
    tenant_id  INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    group_id   INTEGER NOT NULL REFERENCES scim_groups(id) ON DELETE CASCADE,
    role       user_role NOT NULL DEFAULT 'analyst',
    enabled    BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_scim_group_role_mapping UNIQUE (group_id)
);

DO $$ BEGIN
    RAISE NOTICE 'SCIM identity schema ready (tokens hashed; users/groups; no admin mapping by default)';
END $$;
