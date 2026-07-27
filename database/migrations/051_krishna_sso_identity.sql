-- 051_krishna_sso_identity.sql
-- E5-1a SSO/OIDC foundation (Krishna). Additive, idempotent.
--
-- Adds the backend tables for OIDC-first enterprise SSO: per-tenant provider
-- config, linked external identities, and single-use auth-flow state. NO demo
-- providers, NO secrets — client secrets live ONLY in environment variables
-- referenced by `client_secret_env` (never stored here).
--
-- Tenant safety: these tables are read on the PRE-authentication login path
-- (before any RLS/tenant GUC is set), so they intentionally do NOT use RLS —
-- the SSO service scopes every query with an explicit `tenant_id` filter (the
-- same trust model as the users/login lookup). See docs/security/SSO.md.

-- ---------------------------------------------------------------------------
-- Per-tenant SSO provider configuration.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenant_sso_providers (
    id                       SERIAL PRIMARY KEY,
    tenant_id                INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    provider_type            TEXT NOT NULL CHECK (provider_type IN ('oidc', 'saml', 'workos_saml')),
    name                     TEXT NOT NULL,
    enabled                  BOOLEAN NOT NULL DEFAULT false,
    issuer                   TEXT,
    authorization_endpoint   TEXT,
    token_endpoint           TEXT,
    jwks_uri                 TEXT,
    client_id                TEXT,
    -- NAME of the env var holding the client secret (never the secret itself).
    client_secret_env        TEXT,
    scopes                   TEXT NOT NULL DEFAULT 'openid email profile',
    allowed_domains          JSONB NOT NULL DEFAULT '[]'::jsonb,
    jit_provisioning_enabled BOOLEAN NOT NULL DEFAULT false,
    default_role             user_role NOT NULL DEFAULT 'analyst',
    -- fail-closed: only satisfy admin MFA from the IdP when explicitly trusted.
    trust_idp_mfa            BOOLEAN NOT NULL DEFAULT false,
    metadata                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_tenant_sso_providers_tenant_name UNIQUE (tenant_id, name)
);

CREATE INDEX IF NOT EXISTS idx_tenant_sso_providers_tenant   ON tenant_sso_providers(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_sso_providers_enabled  ON tenant_sso_providers(tenant_id, enabled);

-- ---------------------------------------------------------------------------
-- External identities linked to local users (one row per IdP subject).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS external_identities (
    id             SERIAL PRIMARY KEY,
    tenant_id      INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider_id    INTEGER NOT NULL REFERENCES tenant_sso_providers(id) ON DELETE CASCADE,
    issuer         TEXT NOT NULL,
    subject        TEXT NOT NULL,
    email          TEXT NOT NULL,
    email_verified BOOLEAN NOT NULL DEFAULT false,
    last_login_at  TIMESTAMPTZ,
    claims         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- one identity per (provider, subject); one identity per (provider, email).
    CONSTRAINT uq_external_identities_provider_subject UNIQUE (provider_id, subject),
    CONSTRAINT uq_external_identities_provider_email   UNIQUE (provider_id, email)
);

CREATE INDEX IF NOT EXISTS idx_external_identities_user     ON external_identities(user_id);
CREATE INDEX IF NOT EXISTS idx_external_identities_tenant   ON external_identities(tenant_id);
CREATE INDEX IF NOT EXISTS idx_external_identities_provider ON external_identities(provider_id);

-- ---------------------------------------------------------------------------
-- Single-use OIDC auth-flow state (CSRF + replay protection). Only HASHES of
-- state/nonce/code_verifier are stored — never the raw values.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sso_auth_states (
    state_hash         TEXT PRIMARY KEY,
    nonce_hash         TEXT NOT NULL,
    tenant_id          INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    provider_id        INTEGER NOT NULL REFERENCES tenant_sso_providers(id) ON DELETE CASCADE,
    redirect_uri       TEXT,
    return_to          TEXT,
    code_verifier_hash TEXT,
    expires_at         TIMESTAMPTZ NOT NULL,
    consumed_at        TIMESTAMPTZ,
    ip_address         TEXT,
    user_agent         TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sso_auth_states_expires  ON sso_auth_states(expires_at);
CREATE INDEX IF NOT EXISTS idx_sso_auth_states_provider ON sso_auth_states(provider_id);

DO $$ BEGIN
    RAISE NOTICE 'SSO identity schema ready (tenant_sso_providers, external_identities, sso_auth_states) — no providers/secrets seeded';
END $$;
