# Feature Audit Status

**Date:** 2026-07-11 · **Branch:** `prototype-evolution-accuracy-bullmq` · **Auditor:** repo-verified (Ponytail classification treated as hypothesis only)

> **Note on "Current Classification":** the Ponytail audit text was never delivered to this
> session (the paste was interrupted), so the hypothesis column is `—`. Every classification
> below was derived and verified directly from the repository: router registry
> (`backend/app/routes/registry.py`), frontend API consumers (grep of `frontend/src` for
> `/api/*` and `/stream/*`), nav config (`frontend/src/config/nav.tsx`), config flags
> (`backend/app/config.py`), import graphs (backend + frontend orphan scans), lifespan/
> singleton wiring (`main.py`, `app/commands/singletons.py`), and the test suite (114 files).

## Method

1. Enumerated every mounted router (46), backend service (~75), frontend page (48), and test file (114).
2. Measured runtime consumption: which API prefixes the frontend actually calls, which background loops each process actually starts, which flags gate what.
3. Ran orphan scans both directions (backend: modules never imported; frontend: modules never imported, with manual verification of `next/dynamic` barrel files, which produced 14 false positives).
4. Only artifacts with **zero** operational references after manual verification were classified DEAD.

## Verdict in one line

The codebase is unusually clean: every router has a live consumer or a documented flag gate; the "experimental" tier is already implemented as config flags (off by default) with full test suites — no archiving move is needed. Genuine dead weight: **3 files (~90 lines) + 3 stale-brand SVGs + 2 stale doc claims**.

---

## CORE — verified in use; keep

| Feature | Audit | Verified | Evidence (consumers / wiring) | Key files | Tests | Risk | Status |
|---|---|---|---|---|---|---|---|
| Auth & RBAC (JWT, 2FA, invites, onboarding, key rotation) | — | CORE | `AuthContext.tsx`, login/signup/reset/verify/accept-invite pages; every data router depends on it | `routes/auth.py`, `services/auth_service.py`, `jwt_keys.py`, `totp.py` | test_security, test_auth_lifecycle, test_tokens, test_jwt_keys | n/a | keep |
| Live sales pipeline (generator → Redis → SSE) | — | CORE | `hooks/useEventStream.ts`, LiveStreamChart, LiveTable, Topbar; singletons container runs generator | `routes/stream.py`, `services/data_generator.py`, `commands/singletons.py` | test_partitioned_stream, test_demo_tenant_guard, test_multiworker_safety | n/a | keep |
| Sales / KPIs / Analytics APIs | — | CORE | `lib/api.ts` facade; dashboard, analytics, role-workbench, today pages | `routes/{sales,kpis,analytics}.py` | test_golden_numbers, test_accuracy_guards, test_metric_views_parity | n/a | keep |
| History API | — | CORE (API surface) | No frontend consumer, but documented REST resource (README), auth+tenant-scoped, trivial size | `routes/history.py` | covered via test_api | n/a | keep |
| Diagnostics loop (findings + BullMQ worker + insights/decisions) | — | CORE | `lib/api.ts` findings endpoints; insights & decisions pages; worker/ heartbeat in /health | `routes/findings.py`, `services/root_cause.py`, `worker/src/*` | test_root_cause, worker/src/*.test.js | n/a | keep — prototype centerpiece |
| Forecasting (classical + LightGBM + LSTM tiers, Forecast Lab, public methodology) | — | CORE | forecast-lab page, /methodology (public trust page, in `openPaths`), sales predictions | `services/{predictor,forecast_service,forecast_trainer}.py`, `services/forecasting/` | test_forecasting_engine, test_forecasting_v2, test_predictor, test_forecast_methodology_public | n/a | keep |
| Inventory | — | CORE | nav + page + ActionCenter + nav badges | `routes/inventory.py` | test_safety_stock, test_api | n/a | keep |
| Promotions (+ uplift honesty) | — | CORE | nav + page + queries/promotions.ts | `routes/promotions.py`, `services/promotion_uplift.py` | test_promotion_uplift, test_promotion_honesty | n/a | keep |
| Procurement (P2P, POs, approvals) | — | CORE | nav + pages + ActionCenter + AuditTimeline | `routes/procurement.py`, `services/procurement_service.py` | test_procurement | n/a | keep |
| Alerts & notifications | — | CORE | alerts page, Topbar bell, /stream/alerts | `routes/{alerts,notifications}.py` | test_alert_service, test_notifications | n/a | keep |
| Employees | — | CORE | nav + page + dynamic chart components | `routes/employees.py`, `services/employee_*.py` | (seeder covered in test_api) | n/a | keep |
| Reports & print export | — | CORE | reports page; `lib/printExport.ts` (dynamic import — orphan-scan false positive) | `routes/reports.py` | test_api | n/a | keep |
| Admin console + tenants | — | CORE | admin, admin/tenants pages | `routes/{admin,tenants}.py` | test_tenant_lifecycle, test_tenant_profile | n/a | keep |
| Team & seats | — | CORE | settings/team page | `routes/team.py` | test_onboarding | n/a | keep |
| Billing + usage metering + plan limits | — | CORE | settings/billing, UsageMeters, pricing page | `routes/billing.py`, `services/{billing,usage_metering,plan_limits}.py` | test_billing, test_usage_metering, test_plan_limits | n/a | keep |
| Outcome pricing | — | CORE | /outcome-pricing page (linked from settings + pricing) | `routes/outcome_pricing.py` | test_outcome_pricing | n/a | keep |
| Imports (interactive, Excel, quality, scheduler, rollback) | — | CORE | imports page; scheduler loop is the one API-process background task | `routes/imports.py`, `services/{csv_import,import_scheduler,import_rollback}.py` | test_csv_import, test_excel_import, test_import_* | n/a | keep |
| Bulk import API (SCALE-2) | — | CORE (API-only by design) | No frontend by spec (`docs/product/specs/EXTERNAL_DATA_AT_SCALE.md`) | `routes/bulk_import.py` | test_bulk_ingest | n/a | keep |
| Data sources & connectors | — | CORE (flag) | data-sources page; `enable_data_source_connectors` (off in prod by default) | `routes/data_sources.py`, `services/source_adapters.py` | test_data_source_isolation | n/a | keep |
| Public API + keys + webhooks + versioning | — | CORE | developers page (playground, keys, webhooks) | `routes/{public_api,api_keys,webhooks}.py`, `services/api_versioning.py` | test_api_keys, test_webhooks, test_api_versioning | n/a | keep |
| Security ops (SOC panel, audit export, events) | — | CORE | security + audit pages, /stream/security, nav badges | `routes/security.py`, `services/security_events.py` | test_security_hardening | n/a | keep |
| Monitoring / status / trust | — | CORE | monitoring, /status, /trust pages (public trust surfaces in `openPaths`) | `routes/monitoring.py`, `services/health_checks.py` | test_health, test_health_checks, test_observability | n/a | keep |
| UAE intelligence | — | CORE | nav + uae-insights page + calendar hook | `routes/uae_intelligence.py` | test_uae_intelligence | n/a | keep |
| Sage assistant (NL→SQL v2, RAG, guardrails, federation, voice) | — | CORE | ChatBot.tsx; sage2 is also a dependency of sage3 | `routes/ai.py`, `services/{sage2,nl2sql,rag,guardrails,federation,llm}/`, `voice_service.py` | test_sage2, test_nl2sql_*, test_rag_* (11 files), test_guardrails, test_federation | n/a | keep |
| Sage Copilot feed | — | CORE | nav (super_admin), copilot page, feed widgets (side-effect import) | `routes/copilot.py`, `services/sage_copilot.py` | test_sage_copilot | n/a | keep |
| Role experience (briefing, decisions, experience nav manifest, role-workbench, /today) | — | CORE | nav + pages + DomainRail + ExperienceContext | `routes/{briefing,decisions,experience}.py`, `services/role_experience.py` | test_briefing, test_decision_center, test_role_experience | n/a | keep |
| Action drafts + ROI/value | — | CORE | action-drafts + value pages, insights integration | `routes/{action_drafts,roi}.py` | test_action_drafting, test_roi | n/a | keep |
| Search / command palette | — | CORE | CommandPalette.tsx | `routes/search.py` | (covered in test_api) | n/a | keep |
| Feedback / NPS | — | CORE | FeedbackDialog, NpsPulse | `routes/feedback.py` | (covered in test_api) | n/a | keep |
| Platform console (customizations, ops, bespoke, Atelier AI) | — | CORE (internal tooling) | platform-console pages + AtelierChat; gated on `is_platform_developer` | `routes/{customizations,platform_ops,bespoke,atelier_ai}.py` | test_customizations, test_bespoke, test_atelier_advisor, test_platform_access | n/a | keep |
| Frontend telemetry (PostHog, opt-in) | — | CORE (inert by default) | No-op without `NEXT_PUBLIC_POSTHOG_KEY`; `/api/telemetry/events` in the file is a comment about planned K1 ingest, not a call | `lib/telemetry.ts` | — | n/a | keep |

## EXPERIMENTAL — valuable, already flag-gated (the audit's "move behind feature flags" action is ALREADY DONE); keep

| Feature | Audit | Verified | Evidence | Flag (default) | Tests | Status |
|---|---|---|---|---|---|---|
| SSO (OIDC + managed-SAML bridge) | — | EXPERIMENTAL | No frontend consumer; enterprise-identity showcase per `docs/runbooks/ENTERPRISE_IDENTITY.md` | `sso_enabled` (off), `sso_native_saml_enabled` (off, not impl.) | test_sso_oidc, test_sso_admin, test_sso_managed_saml | keep as-is |
| SCIM provisioning | — | EXPERIMENTAL | IdP-driven by design (no frontend expected) | `scim_enabled` (off) | test_scim, test_scim_admin | keep as-is |
| POS connectors | — | EXPERIMENTAL | Sync loop in singletons container; platform-ops surface | `pos_sync_enabled` | test_platform_hardening | keep as-is |
| Payments provider | — | EXPERIMENTAL | Mock provider; disabled in production (commit 7ffdf5a) | prod-guarded | test_deploy_config | keep as-is |
| E-invoicing + clearance (UAE) | — | EXPERIMENTAL | Billing sub-feature; accreditation doc | billing-gated | test_einvoicing, test_einvoice_clearance | keep as-is |
| Data rights (export/delete, PDPL) | — | EXPERIMENTAL | API-only compliance surface; runbook DATA_DELETION.md | — | test_data_rights | keep as-is |
| Provisioning / isolation tiers / residency | — | EXPERIMENTAL | Admin API; `docs/product/ISOLATION_TIERS.md` | `enable_dedicated_schema_routing` (off) | test_provisioning, test_isolation_and_replica, test_data_residency | keep as-is |
| Sage v3 multi-agent graph (langgraph) | — | EXPERIMENTAL | Builds ON sage2 (not a superseded generation — v2 is a v3 dependency) | `use_sage_v3` (off) | test_sage3, test_sage3_rbac | keep as-is |
| Ops alerting (webhook pager) | — | EXPERIMENTAL | Wired into /health/ready | `alert_enabled` (off) | test_alerting | keep as-is |
| Embedding backfill (semantic layer Stage 1) | — | EXPERIMENTAL (unwired) | Zero importers — module self-documents "intended callers … to wire" per `docs/product/specs/STAGE1_SEMANTIC_LAYER.md`; its dep `embeddings.py` is live in RAG | — (awaiting wiring) | none yet | keep; wire or delete at Stage 1 |
| Dev component gallery (`/dev/components`) | — | EXPERIMENTAL (dev tool) | Not in nav; design-system showcase | — | — | keep |

## DEAD — verified zero references; deleted

| Feature | Audit | Verified | Evidence | Decision | Reason | Files | Tests | Risk | Status |
|---|---|---|---|---|---|---|---|---|---|
| Nav `domains.ts` compat shim | — | DEAD | Zero importers; its own docstring: "will be removed once no imports reference it" | DELETE | Migration it served is complete | `frontend/src/lib/nav/domains.ts` (11 lines) | none (re-export only) | none — tsc proves it | **deleted** |
| "RetailIQ" wordmark lockup (component + SVGs) | — | DEAD (brand decision) | Zero importers of `Logo`; wordmark hardcodes "RetailIQ" but the owner-confirmed name is "Retail Intelligence" — the reconciliation the branding README was waiting on already happened, and it went the other way. A drop-in component rendering the wrong product name violates the "never hardcode the name" rule and is a shipping hazard, not staged value. The mark itself (`BrandIcon`, favicon, icon SVG) is live and kept. | DELETE | Artwork for a rejected name; landmine risk > reuse value; recoverable from git | `frontend/src/components/branding/Logo.tsx` (59 lines), `frontend/public/branding/retailiq-logo{,-dark,-mono}.svg`, README section | none | low — no importers; tsc + vitest verify | **deleted** |
| `database/seed_data.sql` placeholder | — | DEAD | Nothing mounts it (E0-4 removed the prod mount; dev compose uses db_seeder, no entrypoint SQL); `test_deploy_config.py` *forbids* re-mounting it | DELETE | Self-described placeholder whose delivery mechanism was removed | `database/seed_data.sql` (12 lines) | test_deploy_config (guard stays green) | none | **deleted** |
| Empty nested `lulu-sales-intelligence-dashboard-main/` dir | — | DEAD (local disk only) | Empty, untracked, not ignored — zip-extraction leftover | REMOVE (no commit — never in git) | Filesystem noise | — | — | none | **removed** |

## Stale documentation corrected (Phase 1)

| Claim | Where | Reality | Fix |
|---|---|---|---|
| "`seed_data.sql` is empty (0 bytes) yet mounted by production compose; prod compose mounts train.csv at a wrong path" | CLAUDE.md + AGENTS.md "Known traps" | E0-4 closed this: neither compose mounts either file; a guard test enforces it | Trap entry replaced with the resolved state |
| "`backend/alembic/` is empty/unused" / "No alembic despite the alembic/ dir" | CLAUDE.md + AGENTS.md | E6-2 added a baseline squash (`alembic/versions/0001_baseline_squash.py`) validated by `test_alembic_baseline.py` and the CI migrations job; runtime migrations remain plain SQL | Claims updated |

## Not dead — audit-style false positives worth recording

- 14 frontend components flagged "unused" by import-scan are loaded via `next/dynamic` barrel files (`components/{analytics,charts,admin,employees,reports}/index.ts`) — **all live**.
- `copilot/feedWidgets.tsx` is a side-effect import (`import '@/components/copilot/feedWidgets'`) — live.
- `lib/printExport.ts` is dynamically imported by analytics + reports pages — live.
- `global.d.ts` is ambient — needs no importer.
- `/methodology`, `/status`, `/trust` have no nav entry **by design** — they're public trust pages (`ClientLayout.openPaths`).
- Backend `voice_service`, `predictor`, `promotion_uplift`, `einvoicing`, `data_residency`, `import_rollback`, `root_cause`, `isolation`, `api_versioning` — all traced to live importers (lazy/function-scope imports defeat naive grep).
- `worker/` (Node BullMQ) is not an orphan sub-project — it's the diagnostics engine feeding `/api/findings`, heartbeat-checked by `/health`.
- Both backup docs kept: `docs/production/BACKUP_RESTORE.md` (policy/tooling) vs `docs/runbooks/BACKUP_AND_RESTORE.md` (E0-1 runbook) — complementary, not duplicates.
- All 8 frontend runtime dependencies and every annotated backend requirement verified in use. **Zero dependencies removed because zero were unused.**

---

## Phase reports

### Phase 1 — low-risk cleanup (implemented)
- **Removed files:** `frontend/src/lib/nav/domains.ts`, `frontend/src/components/branding/Logo.tsx`, `frontend/public/branding/retailiq-logo.svg`, `retailiq-logo-dark.svg`, `retailiq-logo-mono.svg`, `database/seed_data.sql`; plus the empty untracked nested dir (local only).
- **Edited:** `frontend/public/branding/README.md` (wordmark section removed), `frontend/src/components/branding/BrandIcon.tsx` (default a11y title now sourced from `lib/brand.ts` instead of hardcoded "RetailIQ"), CLAUDE.md + AGENTS.md (stale claims), this file.
- **Lines removed:** ~200 (code + SVG markup) net of doc edits.
- **Dependencies removed:** 0 (none unused).
- **Tests updated:** 0 required — no test referenced any deleted artifact. Verification: `tsc --noEmit` + vitest (frontend), deploy-config guard suite (backend).
- **Bundle impact:** negligible (dead modules were already tree-shaken; SVGs were unreferenced static assets).
- **Maintenance impact:** removes a wrong-brand landmine and a shim inviting deprecated imports; docs now match reality (the real win — two "known traps" were already fixed but still documented as live).

### Phase 2 — archive (verified: nothing to do)
Every archive-tier candidate (SSO, SCIM, POS, payments, e-invoicing, Sage v3, provisioning tiers) is **already** behind an off-by-default flag with a full test suite — which is this audit's prescribed end-state for EXPERIMENTAL/ARCHIVE. Moving them to an `archive/` directory would *break* their tests and CI for zero maintenance gain. Decision: no moves.

### Phase 3 — delete dead systems (verified: none)
No dead *systems* exist. The only deletions were the Phase 1 files above. Notably, nothing was deleted for merely "having no frontend consumer" (SCIM, bulk import, data rights are API-only **by design**).

---

## Final inventory

**Core (31 features):** auth/RBAC, live pipeline, sales/KPIs/analytics, history API, diagnostics loop (findings + worker), forecasting, inventory, promotions, procurement, alerts, notifications, employees, reports/export, admin, tenants, team, billing/metering, outcome pricing, imports (+bulk), data sources, public API/keys/webhooks, security ops, monitoring/status/trust, UAE intelligence, Sage v2 (+RAG/guardrails/voice), Sage Copilot, role experience (briefing/decisions/workbench/today), action drafts/ROI, search, feedback/NPS, platform console (+Atelier).

**Experimental (11, all flag-gated or spec-staged):** SSO, SCIM, POS connectors, payments, e-invoicing, data rights, provisioning/isolation/residency, Sage v3, ops alerting, embedding backfill, dev component gallery.

**Archived:** none (flag-gating already serves this role).

**Deleted:** nav domains shim, RetailIQ wordmark lockup (component + 3 SVGs), seed_data.sql placeholder, empty stray directory.

## Architecture (post-audit — unchanged shape, less noise)

```
                       ┌────────────────────────────────────────────┐
                       │ Next.js 14 (App Router, 48 pages)          │
                       │ lib/api.ts → apiClient (scoped TTL cache)  │
                       │ useEventStream (SSE, ref-counted)          │
                       └───────────────┬────────────────────────────┘
                                       │ httpOnly-cookie auth + CSRF
                       ┌───────────────▼────────────────────────────┐
                       │ FastAPI — 46 routers via routes/registry   │
                       │ middleware: SecHdrs→CSRF→BodyLimit→Session │
                       │            →RateLimit→ReqID→CORS           │
                       └──┬──────────┬──────────┬───────────────────┘
        singletons (1x)   │          │          │        Node BullMQ worker
   generator·demo-reset·  │   Postgres 15 (RLS, │     detect→diagnose→recommend
   cache-warm·trainer·    │   sales_fact_view)  │          → findings API
   partition·pos-sync     │          │          │
                          └── Redis 7 (pub/sub sales|alerts|inventory·streams·
                              rate-limit·blacklist·BullMQ queues) ──────────┘
   Flag-gated enterprise ring (off by default): SSO · SCIM · payments ·
   e-invoicing · isolation tiers · Sage v3 (langgraph, composes on Sage v2)
```

## Technical-debt reduction & production-readiness delta

- Debt removed: 1 deprecated shim, 1 wrong-brand component + 3 assets, 1 orphan SQL placeholder, 2 stale "known trap" doc claims that would have misdirected future work.
- Debt explicitly tracked (not hidden): `embedding_backfill.py` awaits its Stage-1 wiring; `sso_native_saml_enabled` is a declared not-implemented flag.
- Production-readiness: **unchanged by this audit** (nothing load-bearing was touched). The readiness posture continues to be governed by `docs/production/READINESS_CHECKLIST.md`; the deploy-config guard suite still passes, and the corrected CLAUDE/AGENTS traps remove two false alarms from every future review.
