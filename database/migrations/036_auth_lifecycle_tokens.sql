-- =============================================================================
-- 036_auth_lifecycle_tokens.sql
-- Single-use, expiring auth tokens for password reset, email verification, and
-- invites. Additive: a new table; does not touch existing auth tables.
--
-- Tokens are stored as a SHA-256 hash of the raw token (never the raw value).
-- Single-use is enforced atomically at consume time:
--   UPDATE ... SET used_at = now() WHERE token_hash = :h AND used_at IS NULL
--                 AND expires_at > now() RETURNING ...
-- A second attempt matches no row, so replay is impossible.
--
-- Accessed only by the owner connection on pre-auth flows (not the tenant-scoped
-- request path), consistent with password_reset_tokens / user_sessions, so no RLS
-- policy is attached. invite rows carry tenant_id/role for the accept flow.
-- =============================================================================

CREATE TABLE IF NOT EXISTS auth_tokens (
    id           BIGSERIAL PRIMARY KEY,
    token_hash   VARCHAR(64) UNIQUE NOT NULL,            -- sha256 hex of the raw token
    token_type   VARCHAR(32) NOT NULL,                  -- 'pwd_reset' | 'email_verify' | 'invite'
    user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,   -- null for invites (no user yet)
    tenant_id    INTEGER,                               -- invites
    email        VARCHAR(255),                          -- invites
    role         VARCHAR(50),                           -- invites
    invited_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    expires_at   TIMESTAMP WITH TIME ZONE NOT NULL,
    used_at      TIMESTAMP WITH TIME ZONE,
    created_at   TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_auth_tokens_type_hash ON auth_tokens(token_type, token_hash);
CREATE INDEX IF NOT EXISTS idx_auth_tokens_user ON auth_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_tokens_expires ON auth_tokens(expires_at);
