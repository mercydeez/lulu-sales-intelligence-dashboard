# SCIM provisioning — enterprise identity lifecycle (E5-1c)

SCIM 2.0-compatible provisioning that pairs with SSO ([`SSO.md`](SSO.md)): the IdP
creates/updates/deactivates users in Retail IQ automatically.

## 1. Support status

| Capability | Status |
|---|---|
| SCIM 2.0 User provisioning (create/read/list/update/patch/deactivate) | ✅ Implemented |
| Group provisioning (create/list/get/patch members/delete) | ✅ Minimal (metadata + membership) |
| Group→role mapping | ⚠️ **Off by default**; never grants admin (see §6) |
| Azure AD / Okta / WorkOS core flows | ✅ Compatible |
| Bearer-token auth (hashed, tenant-scoped) | ✅ Implemented |
| Frontend admin UI | ❌ Not in this task (API only) |
| SCIM password sync | ❌ Not supported (SSO/local only) |
| `filter` beyond `userName eq` | ❌ Not supported (clear SCIM error) |

## 2. Setup

1. Set `SCIM_ENABLED=true` and redeploy.
2. As a tenant admin, create a token:
   `POST /api/scim/admin/tokens  {"name":"Okta","expires_days":365}` → returns the
   **raw token once**. Copy it now — it is never shown again.
3. In the IdP, configure SCIM provisioning:
   - **Base URL:** `https://api.<domain>/api/scim/v2/{tenant_slug}`
   - **Authorization:** `Bearer <the token>`
4. Attribute mappings:
   - `userName` → email (identifier)
   - `active` → active
   - `name.givenName` / `name.familyName` / `displayName`
   - `externalId` → external id
   - **No role/group mapping to privileges** (see §6).

## 3. Azure AD / Microsoft Entra
Enterprise app → **Provisioning** → Automatic. Tenant URL = the Base URL above;
Secret Token = the bearer token. **Test Connection** validates auth (calls
`/ServiceProviderConfig` + `/Users`). Provision on demand from a user's
Provisioning tab. Deprovisioning sends `active:false` (PATCH) → the user is
**deactivated** (status=inactive), sessions revoked.

## 4. Okta
Okta app → **Provisioning** → Configure API Integration. Base URL = the Base URL
above; API Token = the bearer token. Supported: Create/Update/Deactivate Users,
Import (via `GET /Users`). Deactivate → `active:false` → user deactivated (not
deleted).

## 5. WorkOS / managed bridge
If WorkOS (or another bridge) fronts the IdP's SCIM, point WorkOS's Directory Sync
at the Base URL with the bearer token. Retail IQ stores **only the token hash** —
manage the raw token in WorkOS's vault/admin flow.

## 6. Security model

- **Hashed tokens, one-time reveal:** tokens are stored as sha256 hashes + a display
  prefix; the raw value is returned only at create/rotate and never logged.
- **Constant-time, tenant-scoped auth:** verification uses `hmac.compare_digest`
  against the tenant's active tokens only; an invalid token returns 401 without
  revealing whether the tenant exists; a token cannot be used cross-tenant.
- **No privileged provisioning:** SCIM-created users default to `analyst`
  (`SCIM_DEFAULT_ROLE`); a `role` in the SCIM body is **ignored**. SCIM can never
  create `super_admin`/`admin`/`owner`.
- **Group→role mapping is off by default** (`SCIM_GROUP_MAPPING_ENABLED=false`) and
  a privileged mapping is refused unless `SCIM_ALLOW_ADMIN_ROLE_MAPPING=true`
  (records `scim_group_role_mapping_skipped`).
- **Deactivate, never delete:** `active:false` and `DELETE /Users/{id}` set
  status=inactive and (with `SCIM_DEACTIVATE_REVOKES_TOKENS=true`) revoke sessions.
  The **last active super_admin cannot be deactivated**.
- **Tenant isolation:** every query filters `tenant_id`; userName uniqueness is
  per-tenant; group members outside the tenant are ignored
  (`scim_cross_tenant_access_blocked`).
- **No SSO admin-MFA bypass:** SCIM provisions *analyst* users; it does not grant
  admin and does not touch the SSO admin-MFA gate. Admin login still requires MFA.
- **Audit:** `scim_token_created/rotated/revoked/auth_failed`, `scim_user_created/
  updated/deactivated/reactivated`, `scim_group_created/updated/deleted`,
  `scim_group_role_mapping_skipped`, `scim_cross_tenant_access_blocked`,
  `scim_provisioning_failed` (no tokens/hashes/passwords in payloads).

## 7. Acceptance checklist
- [ ] SCIM token created (raw shown once).
- [ ] IdP test connection succeeds.
- [ ] User provisioned (`POST /Users` → analyst).
- [ ] User updated (`PUT`/`PATCH`).
- [ ] User deactivated (`active:false` / `DELETE` → status inactive).
- [ ] Token rotated (new token issued once, old revoked).
- [ ] Revoked token rejected (401).
- [ ] No secrets in logs (grep for `scim_` token values — none).
- [ ] Security events captured for the above.
- [ ] Combined SSO + SCIM pilot evidence captured (see
      [`../runbooks/ENTERPRISE_IDENTITY.md`](../runbooks/ENTERPRISE_IDENTITY.md)).

## 8. Disable / rollback
1. Revoke the SCIM token(s): `POST /api/scim/admin/tokens/{id}/revoke`.
2. Set `SCIM_ENABLED=false` and redeploy (all SCIM endpoints 401 immediately).
3. Disable the SSO provider if needed (see `SSO.md`).
4. Redeploy the previous tag if required (see `../runbooks/DEPLOY_PIPELINE.md`).
5. Verify `/health/ready` returns 200.
