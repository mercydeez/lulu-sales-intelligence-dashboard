# Runbook: Suspected Data Leak / Cross-Tenant Access

**Treat as a critical security incident.** Symptoms: a tenant reports seeing another
tenant's data; `token_tenant_mismatch` events; an unexpected export download; an
auth-failure or access-pattern anomaly.

## 1. Contain (first, fast)
- Identify the affected tenant(s) and the suspected path/endpoint.
- If a specific feature is implicated, disable it via its flag
  ([../production/ENVIRONMENT.md](../production/ENVIRONMENT.md)).
- If credentials may be compromised, force session revocation: rotate
  `JWT_SECRET_KEY` (invalidates all tokens) as a break-glass; reset affected
  passwords (which revokes their sessions).

## 2. Investigate
- `security_events` (migration 030): `token_tenant_mismatch`, `role_denied`,
  `permission_denied`, `data_source_*`, export/delete events — filter by tenant +
  time window.
- Confirm the isolation layers: is `USE_RLS_ROLE` on? Did a query miss a `tenant_id`
  filter? (App-layer scoping is layer 1; RLS is the backstop — see
  [../security/TENANT_ISOLATION_PROOF.md](../security/TENANT_ISOLATION_PROOF.md).)
- Check recent deploys/migrations for a scoping regression.

## 3. Remediate
- Fix the missing scope; add a regression test (e.g. the
  `tests/test_data_source_isolation.py` pattern).
- Ensure RLS is enabled in production (`USE_RLS_ROLE=true`, not
  `ALLOW_INSECURE_NO_RLS`).

## 4. After (do not skip)
- Determine scope of exposure: which tenants/records, for how long.
- Notify affected customers per contract/policy ([../legal/DPA_DRAFT.md](../legal/DPA_DRAFT.md)).
- Write a post-incident review; add detection (alert on `token_tenant_mismatch`).
