# Authentication

## Primitives

- **Passwords:** bcrypt-hashed; strength policy enforced (`auth_service.validate_password_strength`).
- **JWT access/refresh:** short-lived access (carries `iat`, `jti`, `type=access`),
  longer refresh (`type=refresh`, single-use — rotated + blacklisted on use).
- **Token blacklist:** Redis, per-token-hash, checked by `SessionInvalidationMiddleware`.
  Fails **closed** by default when Redis is down (`AUTH_FAIL_OPEN_ON_REDIS_DOWN=false`).
- **2FA:** TOTP with hashed backup codes (migrations 032). A correct password for a
  2FA account returns a short-lived `mfa_challenge`, exchanged at `/2fa/verify`.

## Single-use lifecycle tokens (migration 036, `auth_tokens`)

Reset, email-verification, and invite tokens are recorded in `auth_tokens` as a
**SHA-256 hash** (never the raw value) with an expiry. Consumption is atomic:

```sql
UPDATE auth_tokens SET used_at = now()
 WHERE token_hash = :h AND token_type = :t AND used_at IS NULL AND expires_at > now()
 RETURNING ...
```

A replay matches no row → rejected. Service: `app/services/token_store.py`
(`issue_token` / `consume_token`).

| Flow | Type | TTL | On consume |
|------|------|-----|------------|
| Password reset | `pwd_reset` | 30 min | set password, **revoke all sessions** |
| Email verify | `email_verify` | 3 days | mark `email_verified` |
| Invite | `invite` | 7 days | set password, activate, mark verified |

The JWT signature/expiry is still validated **and** the single-use record consumed —
both must pass.

## Session revocation (epoch)

Auth is stateless (no session table is populated). To revoke **all** of a user's
access tokens at once (after a password reset), `revoke_user_sessions(user_id)`
writes a Redis cutoff timestamp; `get_current_user` rejects any access token whose
`iat` predates it (`tokens_revoked_before`). This is best-effort (Redis-dependent)
and complements the per-token blacklist used at logout/refresh.

## No account enumeration

`/forgot-password` always returns the same message whether or not the email exists.

## Admin MFA enforcement

When `REQUIRE_MFA_FOR_ADMINS=true`, an admin/owner/super_admin **without** 2FA is
blocked at login (403) and a `mfa_required_admin` security event is recorded.
**Enable this only after admins have enrolled** — see
[`../product/ACCOUNT_LIFECYCLE.md`](../product/ACCOUNT_LIFECYCLE.md). Toggling the
flag off is the break-glass for initial enrollment.

**SSO does not bypass this.** The OIDC login path (E5-1a) applies the same admin
MFA gate: an admin without local TOTP is blocked (`sso_admin_mfa_required`) unless
the provider explicitly opts into trusting the IdP's MFA. See
[`SSO.md`](SSO.md).

## Enterprise identity: SSO + SCIM (E5-1a / E5-1c)
Enterprise OIDC login (Azure AD / Entra reference) is available at `/api/sso/*`,
OFF by default. JIT provisioning is analyst-only and cannot create admins; identity
linking is same-tenant only. Full setup, security model, and limitations (incl.
SAML being config-contract-only) are in [`SSO.md`](SSO.md).

**SCIM provisioning** (`/api/scim/*`, E5-1c) is the identity-lifecycle companion:
IdP-driven create/update/deactivate via hashed, tenant-scoped bearer tokens.
SCIM-provisioned users default to analyst and can never be admin, deactivation
never hard-deletes, and SCIM does not bypass admin MFA. See [`SCIM.md`](SCIM.md).

## Audited events
`password_reset_requested`, `password_changed`, `user_invited`, `invite_accepted`,
`mfa_required_admin`, the SSO events (`sso_login_started/succeeded/failed`,
`sso_state_invalid`, `sso_jit_user_created`, `sso_identity_linked`,
`sso_admin_mfa_required`), plus the existing login/role/permission/token events
(`security_events`, migration 030).
