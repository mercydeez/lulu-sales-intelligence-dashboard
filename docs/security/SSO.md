# SSO (Single Sign-On) — OIDC + provider operations (E5-1a / E5-1b)

## 1. Enterprise SSO support matrix

| Capability | Status |
|---|---|
| **OIDC (authorization code)** | ✅ Implemented (backend) |
| **Azure AD / Microsoft Entra ID (OIDC)** | ✅ Reference provider |
| **Managed SAML bridge via OIDC** (`provider_type='workos_saml'`) | ✅ **Implemented (E5-1b)** — reuses the OIDC flow when `SSO_MANAGED_SAML_BRIDGE_ENABLED=true` |
| **Native SAML SP** (`provider_type='saml'`) | ❌ **Not implemented — fail-closed.** Login is rejected with a clear error and a `sso_native_saml_rejected` event. We do **not** hand-roll SAML XML/signature parsing. |
| Tenant-admin provider management (`/api/sso/admin/providers`) | ✅ **Implemented (E5-1b)** |
| Provider validation / diagnostics | ✅ **Implemented (E5-1b)** |
| JIT provisioning into a tenant | ✅ Implemented (analyst-only) |
| Link external identity to existing user | ✅ Same-tenant only |
| Admin MFA fail-closed under SSO | ✅ Implemented (incl. managed bridge) |
| SCIM provisioning | ✅ Implemented (E5-1c — see [`SCIM.md`](SCIM.md)) |
| Frontend login/admin UI | ❌ Not in these tasks (backend contract only) |
| Group→role mapping | ❌ Deferred (JIT/SCIM default role only) |

The implemented login paths are **OIDC** and the **managed SAML→OIDC bridge**.
**Native SAML is not a working login flow** and is never offered or claimed.

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

## 4. Tenant provider setup (SQL or admin API)

Providers can be created via the **admin API** (§10, recommended) or directly in
SQL by an operator. SQL example (fill real values; the secret stays in env):

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

- No frontend UI in these tasks (backend contract only).
- **No native SAML SP login** — enterprise SAML is supported only via the managed
  OIDC bridge (§9); native `saml` providers are fail-closed.
- Actual IdP/bridge credentials must be configured by an operator; nothing is seeded.

## 8. SCIM provisioning (lifecycle companion)

SSO authenticates users; **SCIM** (E5-1c) provisions their lifecycle automatically
from the IdP (create/update/deactivate). SCIM is a separate, tenant-scoped
bearer-token API at `/api/scim/v2/{tenant_slug}`, OFF by default, and — like JIT —
can never create admins. See **[`SCIM.md`](SCIM.md)** and the combined pilot
runbook **[`../runbooks/ENTERPRISE_IDENTITY.md`](../runbooks/ENTERPRISE_IDENTITY.md)**.
SCIM does not bypass the SSO admin-MFA gate.

## 9. Managed SAML bridge (E5-1b)

Enterprise IdPs that speak **SAML** are supported through a **managed bridge** (e.g.
WorkOS): the IdP speaks SAML to the bridge, and the bridge speaks **OIDC** to
Retail IQ. We therefore reuse the entire OIDC security path — no SAML XML or
signature parsing is done here.

- Create a provider with `provider_type='workos_saml'` and the bridge's
  issuer/authorization/token/JWKS endpoints + `client_id` + `client_secret_env`.
- Set `SSO_MANAGED_SAML_BRIDGE_ENABLED=true` to allow bridge logins.
- Redirect URI: `https://api.<domain>/api/sso/oidc/callback` (same as OIDC).
- The secret is stored only in the env var named by `client_secret_env`.
- Allowed domains, JIT, and MFA behave exactly as for OIDC.
- A bridge login records `sso_managed_saml_bridge_started`; public metadata labels
  it `managed_saml_bridge` (never "native SAML").
- `provider_type='saml'` (native) is **rejected** at login with a clear message and
  a `sso_native_saml_rejected` event.

## 10. Tenant-admin provider management (E5-1b)

Endpoints under `/api/sso/admin/providers` (local JWT, **super_admin/admin/owner**,
tenant-scoped). Secrets are never returned — only `client_secret_env_configured`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/sso/admin/providers` | List this tenant's providers (safe fields) |
| POST | `/api/sso/admin/providers` | Create a provider **disabled/draft** (validated) |
| PATCH | `/api/sso/admin/providers/{id}` | Update safe fields (re-sets status to draft) |
| POST | `/api/sso/admin/providers/{id}/validate` | Run diagnostics; store status |
| POST | `/api/sso/admin/providers/{id}/enable` | Enable — **only if valid** |
| POST | `/api/sso/admin/providers/{id}/disable` | Disable immediately (login blocked) |

**Lifecycle:** create → validate → enable → test login → (disable to roll back).
Validation checks required fields, `openid` scope, allowed-domain list, **safe
default role** (never admin), URL safety (HTTPS in prod), and that
`client_secret_env` is an **env var name** (a pasted secret/URL/JWT is rejected).
Optional live validation (`SSO_LIVE_PROVIDER_VALIDATION_ENABLED=true`) also checks
the secret env var exists. Diagnostics contain **no secrets**. Cross-tenant
provider IDs return 404. Disabling a provider blocks `POST /oidc/start` immediately;
existing linked identities remain.

## 11. Security model (provider ops)
- No hand-rolled SAML XML/signature parsing; native SAML is fail-closed.
- Managed bridge reuses all OIDC checks: single-use state, nonce, issuer, audience,
  expiry, email verification, tenant scoping, allowed domains, admin-MFA fail-closed.
- Provider secrets are only env-var **names** in the DB; values live in the
  environment and are never logged or returned.
- Admin endpoints are tenant-scoped and admin-gated; no cross-tenant access.

## 12. Acceptance checklist (SSO provider ops)
- [ ] OIDC provider created + validated + enabled.
- [ ] Managed bridge provider created + validated (bridge enabled).
- [ ] `GET /api/sso/providers` returns safe metadata (no secrets; honest labels).
- [ ] Non-admin SSO login succeeds (analyst).
- [ ] Admin without local MFA is blocked (`sso_admin_mfa_required`).
- [ ] Native `saml` provider login rejected (`sso_native_saml_rejected`).
- [ ] Provider disabled → `POST /oidc/start` fails.
- [ ] Security events captured; **no secrets in logs**.
- [ ] SCIM provisioning still works (see [`SCIM.md`](SCIM.md)).

## 13. Disable / rollback (SSO)
1. Disable the provider: `POST /api/sso/admin/providers/{id}/disable`.
2. Set `SSO_ENABLED=false` (and `SSO_MANAGED_SAML_BRIDGE_ENABLED=false`) to kill all SSO.
3. Local super_admin login (with MFA) always remains available.
4. If the IdP is compromised, also revoke/rotate the SCIM token (see SCIM.md).
5. Redeploy the previous tag if needed; verify `/health/ready`.
