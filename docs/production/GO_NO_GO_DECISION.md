# Retail IQ — GO / NO-GO Decision (Phase 14)

> Date: 2026-06-28 · Branch: `prod-hardening` · Input: `FINAL_RELEASE_REPORT.md`,
> `READINESS_CHECKLIST.md`, `KNOWN_LIMITATIONS.md`, `MANUAL_CHECKS_REQUIRED.md`.

## Decision: **CONDITIONAL GO**

- ✅ **GO** for a **demo / sample-data pilot** *now*. The stack boots healthy, all
  hardening phases (1–6, 9–13) are complete and tested, AI is read-only and
  privacy-preserving by default, tenants are isolated, and there is a backup/
  restore/rollback story.
- ⚠️ **CONDITIONAL** for a **real customer-data pilot**: gated on the
  `MANUAL_CHECKS_REQUIRED.md` items (fresh secrets, tested restore, legal review of
  the `docs/legal/` drafts, staging RLS cross-tenant probe) and acceptance that
  data import is operator-assisted.
- ⛔ **NO-GO** for any use as a **system of record / POS / financial source of
  truth**, or any **regulatory-compliance** claim — explicitly out of scope.

## Why GO is justified

1. **Fail-closed in prod** (Phase 1): default secrets, wildcard CORS, demo users,
   docs exposure, and startup migrate/seed/generator are all rejected.
2. **Safe topology** (Phase 2): API serves API only; migrate/seed/generator/worker
   are dedicated processes; Redis requires a password in prod compose.
3. **Operable** (Phases 3, 4, 9): liveness/readiness/deep probes; backup/restore/
   verify scripts; metrics + request-scoped logging; a runbook per failure mode.
4. **Isolated** (Phase 6, RLS default on): cross-tenant read/list/test/activate is
   blocked at app layer with RLS backstop; verified by tests.
5. **AI-safe** (Phase 11): external AI off by default, no raw SQL on the public
   surface, evidence + demo-data disclosure on every answer, read-only by design.
6. **Trustworthy** (Phase 12): tenant-scoped export, human-approved deletion with
   audit, honest legal drafts that disclaim compliance/POS/SLA.
7. **Verified** (Phases 10, 13, 14): green FE typecheck/tests/build, 289 backend
   tests passing in-container (3 env-path artifacts pass on host/CI), six-job CI
   gate matrix, live health probes green, migrations current.

## Blockers carried (must clear before *real-data* pilot)

| # | Blocker | Owner | Reference |
|---|---------|-------|-----------|
| 1 | Provision fresh prod secrets; confirm `validate_security()` boots clean | Ops | `MANUAL_CHECKS_REQUIRED.md` |
| 2 | Take baseline backup + execute a test restore | Ops | `RESTORE_FROM_BACKUP.md` |
| 3 | Legal review of `PRIVACY.md` / `TERMS.md` | Legal | `docs/legal/` |
| 4 | Staging cross-tenant RLS probe with `USE_RLS_ROLE` | Security | `TENANT_ISOLATION_PROOF.md` |
| 5 | `/security-review` on the release diff, triage findings | Security | — |

## Accepted (not blockers — documented & bounded)

- Phases **7 (import)** and **8 (ingestion)** deferred; pilot uses demo/sample data
  + operator-assisted load.
- Single-node pilot topology; RPO/RTO are planning targets, not an SLA.

## Sign-off

Engineering gate: **CONDITIONAL GO** as above. Final business/legal sign-off
pending the blocker table.
