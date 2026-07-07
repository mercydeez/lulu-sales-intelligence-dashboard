# SSO (Single Sign-On) — OIDC foundation (E5-1a)

## 1. Support status

| Capability | Status |
|---|---|
| **OIDC (authorization code)** | ✅ Implemented (backend) |
| **Azure AD / Microsoft Entra ID** | ✅ Reference provider |
| JIT provisioning into a tenant | ✅ Implemented (analyst-only) |
| Link external identity to existing user | ✅ Implemented (same tenant only) |
| Admin MFA fail-closed under SSO | ✅ Implemented |
| **SAML** | ⚠️ **Config contract only** — `provider_type` `saml`/`workos_saml` exists, but there is **no** SAML SP login path yet. Use a managed SAML→OIDC bridge (e.g. WorkOS) or a future vetted SAML SP. Do **not** assume SAML login works. |
| Frontend login UI | ❌ Not in this task (backend contract only) |
| SCIM provisioning | ❌ Deferred |
| Group→role mapping | ❌ Deferred (JIT default role only) |

The implemented login path is **OIDC**. SAML is a forward-compatible config shape,
not a working login flow — we will not hand-roll SAML XML signature validation.

## 2. Endpoints (mounted at `/api/sso`)

- `GET /api/sso/providers?tenant_slug=…` (or `email_domain=…`) — public-safe enabled
  providers (never returns `client_secret_env`).
- `POST /api/sso/oidc/start` — body `{tenant_slug|tenant_id, provider_name?, return_to?}`
  → `{authorization_url, expires_in}`. No login required.
- `GET /api/sso/oidc/callback?code=…&state=…` — IdP redirect target. On success returns
  the same JSON token shape as `/api/auth/login` and sets the httpOnly cookies.

**Frontend contract (not built here):** redirect the browser to `authorization_url`;
the IdP returns to `/api/sso/oidc/callback`, which issues local tokens. A future
frontend can call `start`, follow the redirect, and consume the callback tokens (or
we add a `return_to` redirect variant).

## 3. Azure AD / Microsoft Entra ID setup

1. Entra admin center → **App registrations → New registration**.
2. **Redirect URI** (Web): `https://api.<domain>/api/sso/oidc/callback`.
3. Note the **Application (client) ID** and the **Directory (tenant) ID**.
4. **Certificates & secrets → New client secret** — copy the value once.
5. Issuer / discovery: `https://login.microsoftonline.com/<tenant-guid>/v2.0`
   (discovery at `…/v2.0/.well-known/openid-configuration`).
6. Scopes: `openid email profile`.
7. Store the secret **only** in the env var named by the provider row's
   `client_secret_env` (e.g. `SSO_AZURE_CLIENT_SECRET`). Never commit it.

Group/role mapping is **not** implemented — JIT users get the provider `default_role`
(clamped to a safe non-admin role), regardless of IdP groups.

## 4. Tenant provider setup (SQL — no public write endpoint)

Provider config is created by an operator (admin write endpoints are intentionally
deferred). Example (fill real values; the secret stays in env):

```sql
INSERT INTO tenant_sso_providers
  (tenant_id, provider_type, name, enabled, issuer,
   authorization_endpoint, token_endpoint, jwks_uri,
   client_id, client_secret_env, scopes, allowed_domains,
   jit_provisioning_enabled, default_role, trust_idp_mfa)
VALUES
  (1, 'oidc', 'Azure AD', true,
   'https://login.microsoftonline.com/<tenant-guid>/v2.0',
   'https://login.microsoftonline.com/<tenant-guid>/oauth2/v2.0/authorize',
   'https://login.microsoftonline.com/<tenant-guid>/oauth2/v2.0/token',
   'https://login.microsoftonline.com/<tenant-guid>/discovery/v2.0/keys',
   '<client-id>', 'SSO_AZURE_CLIENT_SECRET', 'openid email profile',
   '["contoso.com"]'::jsonb, true, 'analyst', false);
```

- `allowed_domains` — JSON array; empty `[]` means no restriction (not recommended).
- `jit_provisioning_enabled` — create unknown users on first login.
- `default_role` — JIT role; clamped to `analyst` if it's an admin role.
- `trust_idp_mfa` — **keep `false`** unless you fully trust the IdP's MFA (see §5).

## 5. Security model

- **State/nonce:** cryptographically random, stored as **hashes**, single-use,
  TTL-bounded (`SSO_STATE_TTL_SECONDS`). Callback consumes state exactly once
  (replay/expiry rejected). PKCE helper exists for a future public-client flow;
  the current confidential flow relies on the client secret + state + nonce.
- **ID token validation:** signature via JWKS, issuer, audience (`client_id`),
  expiry, nonce (hash-compared), subject present, email present,
  `email_verified` when `SSO_REQUIRE_VERIFIED_EMAIL=true`.
- **Tenant boundary:** identities and users are always scoped to the provider's
  tenant. Cross-tenant linking is impossible; email-domain allow-lists are enforced.
- **JIT cannot create admins:** `default_role` is clamped — `super_admin`/`admin`/
  `owner` collapse to `analyst`. JIT users get an unusable random password hash.
- **Admin MFA cannot be bypassed:** if `REQUIRE_MFA_FOR_ADMINS=true` and the user is
  `super_admin`/`admin`/`owner` without local TOTP, SSO login is **blocked** and a
  `sso_admin_mfa_required` event is recorded — **unless** the provider explicitly
  sets `trust_idp_mfa=true` AND the ID token carries a strong `amr`/`acr` MFA signal.
  Default is fail-closed.
- **Secrets:** the client secret is read from the env var named by
  `client_secret_env`; it is never stored in the DB and never logged. Codes/tokens/
  state/nonce are never logged.

## 6. Operational runbook

- **Enable in staging:** set `SSO_ENABLED=true`, `SSO_OIDC_ENABLED=true`, add the
  provider row, set the secret env var, redeploy. Verify `GET /api/sso/providers`.
- **Test the flow:** `POST /api/sso/oidc/start` → open `authorization_url` → sign in
  at the IdP → land on the callback → receive local tokens. Unit tests
  (`backend/tests/test_sso_oidc.py`) cover the security logic with a mocked provider.
- **Disable a provider quickly:** `UPDATE tenant_sso_providers SET enabled=false WHERE id=…;`
  (or flip `SSO_ENABLED=false` to disable all SSO instantly).
- **What to check (security events):** `sso_login_started`, `sso_login_succeeded`,
  `sso_login_failed`, `sso_state_invalid`, `sso_jit_user_created`,
  `sso_identity_linked`, `sso_admin_mfa_required`.

## 7. Known limitations

- No frontend UI in this task (backend contract only).
- No real SAML login (config contract + docs only).
- No SCIM; no group→role mapping (JIT uses `default_role`).
- Actual Azure tenant credentials must be configured by an operator; nothing is seeded.
