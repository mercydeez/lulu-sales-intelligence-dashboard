# Retail IQ — Production Gap Analysis

> Companion to [`BASELINE_AUDIT.md`](BASELINE_AUDIT.md). The audit states current facts; this document states **recommendations** — the gaps between today and a safe pilot deployment, mapped to the hardening phases that close them.

Each gap lists: **Gap → Why it matters → Target state → Phase**.

## A. Runtime & configuration

| Gap | Why it matters | Target state | Phase |
|-----|----------------|--------------|:-----:|
| No production feature flags | Cannot make prod fail closed; demo behavior leaks into prod | ~24 flags (`DEMO_MODE`, `RUN_MIGRATIONS_ON_STARTUP`, `LIVE_GENERATOR_ENABLED`, `ALLOW_DEMO_USERS`, `EXPOSE_API_DOCS`, …) with prod-safe defaults | 1 |
| `validate_security()` too narrow | Unsafe configs boot in prod | Reject wildcard CORS, demo users, docs-exposed, generator-without-demo, migrate/seed-on-startup, default infra passwords | 1 |
| API runs migrate/seed/generator/warmer/trainer | Concurrent migrations + synthetic data in real tenants on multi-replica | API serves API only in prod; one-shot + background work in dedicated processes | 2 |
| No CLI command modules | Can't run migrate/seed/generator as container entrypoints | `backend/app/commands/{migrate,seed,generator,cache_warmer,forecast_trainer}.py` | 2 |
| Prod compose missing migrate/worker/generator separation; Redis unauthenticated | No safe deploy topology | `migrate` one-shot, `worker`, demo-only `generator` profile, `redis --requirepass` | 2 |

## B. Reliability & operations

| Gap | Why it matters | Target state | Phase |
|-----|----------------|--------------|:-----:|
| No liveness/readiness split | Traffic routed before deps ready; restarts on slow deps | `/health/live`, `/health/ready`, `/health/deep` | 3 |
| No backup/restore/rollback | Data loss is unrecoverable; no rollback story | `scripts/{backup,restore,verify}-postgres.sh` + DR runbooks + RPO/RTO | 4 |
| No metrics / thin observability | Incidents undiagnosable | metrics endpoint + tenant/user log context (no secrets) + runbooks | 9 |
| No CI gate matrix | Regressions ship silently | full pytest + isolation + AI-guard + FE build + compose config + migration + scans | 13 |

## C. Security & tenancy

| Gap | Why it matters | Target state | Phase |
|-----|----------------|--------------|:-----:|
| `get_active_source()`/`set_active()` global | **Cross-tenant**: one tenant flips another's active source | tenant-scoped query + per-tenant active unique index (migration 037) | 6 |
| Connector testing ungated | SSRF/egress risk in prod | `ENABLE_DATA_SOURCE_CONNECTORS` (prod default off) + audit events | 6 |
| Reset/verify tokens replayable | Token reuse within expiry window | hashed + single-use (`used_at`), reset revokes sessions, no enumeration (migration 036) | 5 |
| Invites are temp-passwords | Weaker than single-use token flow | invite-token family (expiry, used_at, tenant, role, invited_by) | 5 |
| No session list/revoke | Users can't revoke a stolen session | list + revoke one/all + reuse detection | 5 |
| Admin MFA not enforced | High-priv accounts optional 2FA | `REQUIRE_MFA_FOR_ADMINS` enforcement | 5 |
| ~~API keys never expire~~ **(done)** | Long-lived credential risk | `expires_at` (migration 038) + expiry check in `authenticate`/`tenant_for_key`; optional `expires_in_days` at mint | 8* |

## D. AI safety

| Gap | Why it matters | Target state | Phase |
|-----|----------------|--------------|:-----:|
| External AI not gated | Tenant data could leave to a 3rd-party LLM unexpectedly | `ENABLE_EXTERNAL_AI` off by default in prod; per-tenant AI mode | 11 |
| Public API may surface SQL | Schema/info disclosure | return evidence/summary, never raw SQL in prod | 11 |
| No evidence/approval flow | AI claims unverifiable; autonomous actions | evidence block (source/scope/freshness/confidence/disclosure) + human-approved drafts | 11 |

## E. Product & trust

| Gap | Why it matters | Target state | Phase |
|-----|----------------|--------------|:-----:|
| No self-serve data import | Pilot can't load own data | **Deferred** to a later cycle (documented) | 7* |
| No public ingestion API | No programmatic real-data feed | **Deferred** to a later cycle (documented) | 8* |
| Zero frontend tests | Auth/data regressions ship | Vitest+RTL+Playwright smoke; page states; a11y | 10 |
| No export/delete-on-request | Customer trust / privacy | tenant-scoped export + delete workflow + legal/support drafts | 12 |

\* **Phases 7 and 8 are deferred** by decision. The pilot will run on demo/sample data + manual load; this is stated plainly in `KNOWN_LIMITATIONS.md`. The only Phase-8 carve-out attempted is API-key `expires_at`.

## Sequencing rationale

Hardening before features: Phases **1–6, 9** make *any* deploy safe (fail-closed config, process split, health, backup, isolation, observability). Phases **10–13** raise quality and automation. Phase **14** is the honest GO/NO-GO. Import/ingestion (7/8) add real-data value but are not prerequisites for a demo/sample pilot, so they follow.
