# Runbook — Enterprise Identity (SSO + SCIM)

One combined pilot checklist for enterprise identity: OIDC SSO login (E5-1a) plus
SCIM provisioning (E5-1c). Details: [`../security/SSO.md`](../security/SSO.md),
[`../security/SCIM.md`](../security/SCIM.md).

> Honest scope: OIDC login + SCIM provisioning are implemented. **Native SAML is
> not** — use a managed OIDC/SCIM bridge (e.g. WorkOS). No frontend admin UI; no
> SCIM password sync; group→role mapping is off by default and never grants admin.

## Pilot checklist

**SSO**
- [ ] Provider configured — `POST /api/sso/admin/providers` (admin) or SQL (SSO.md §4/§10); set the client-secret env var.
- [ ] Provider validated — `POST /api/sso/admin/providers/{id}/validate` → `ok:true` (diagnostics carry no secrets).
- [ ] Provider enabled — `POST /api/sso/admin/providers/{id}/enable` (only a valid provider enables).
- [ ] (Enterprise SAML) managed bridge — create a `workos_saml` provider, `SSO_MANAGED_SAML_BRIDGE_ENABLED=true`, validate + enable. Native `saml` is rejected.
- [ ] SSO login smoke — `POST /api/sso/oidc/start` → sign in at the IdP/bridge → callback issues tokens.
- [ ] **Admin MFA block** — an admin without local TOTP is blocked at SSO login (`sso_admin_mfa_required`, 403).
- [ ] Provider disable — `POST /api/sso/admin/providers/{id}/disable` → `POST /oidc/start` now fails.

**SCIM**
- [ ] `SCIM_ENABLED=true`; create a token — `POST /api/scim/admin/tokens` (admin only) → copy the raw token once.
- [ ] IdP test connection succeeds against `/api/scim/v2/{tenant_slug}` with the bearer token.
- [ ] Provision — `POST /Users` creates an **analyst** user (never admin).
- [ ] Update — `PUT`/`PATCH /Users/{id}` updates name/active.
- [ ] Deactivate — `active:false` / `DELETE /Users/{id}` sets status inactive (not deleted), sessions revoked.
- [ ] Rotate — `POST /api/scim/admin/tokens/{id}/rotate` issues a new token once, revokes the old.
- [ ] Revoke — the revoked token now returns 401.

**Evidence to capture** (no secrets/screenshots of tokens)
- [ ] SSO login success + admin-MFA-block security events.
- [ ] SCIM token create/rotate/revoke events; user create/update/deactivate events.
- [ ] Log grep shows **no raw `scim_…` token or client secret** in logs.
- [ ] `/health/ready` = 200 throughout.

## Rollback / disable
1. Revoke SCIM token(s): `POST /api/scim/admin/tokens/{id}/revoke`.
2. `SCIM_ENABLED=false` (SCIM endpoints 401 immediately).
3. Disable the SSO provider: `UPDATE tenant_sso_providers SET enabled=false …` or `SSO_ENABLED=false`.
4. If needed, redeploy the previous tag (see [`DEPLOY_PIPELINE.md`](DEPLOY_PIPELINE.md)).
5. Verify `/health/ready` = 200 and local login still works.
