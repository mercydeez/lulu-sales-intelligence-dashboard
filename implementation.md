# Implementation Plan — Retail IQ

The **single, forward** roadmap: what's verified-done and what's left to build. Completed work
lives in git history and is not re-tracked here. Strategic/product rationale lives in `docs/`
(`PRODUCT_STRATEGY`, `SAAS_PATH`, `architecture/ADR`).

> **Where we are.** The product is a working **system of intelligence**: JWT/RBAC auth,
> multi-tenancy + Postgres RLS, a live Redis→SSE sales pipeline, forecasting + Forecast Lab, a
> procure-to-pay system of record, a per-tenant public API/PaaS layer, and **Sage** — a grounded,
> RBAC-safe NL→SQL assistant (decompose-route-recompose + federation + document RAG, all wired and
> tested). A **Node BullMQ diagnostics worker** runs the loop **detect → diagnose → recommend →
> (human) accept**. The next milestone **tightens the screws**: close the one missing loop stage
> (**measure**), harden accuracy/security, activate the local LLM, and scope the near-term SaaS path
> — keeping it tenant-generic so it serves either **B2B** retail or **B2G** oversight.

## Prototype constraints
- **No paid services.** Local **Ollama** for the LLM, **BullMQ on the existing Redis** for jobs,
  deterministic rules for diagnostics. Paid tiers (Stripe/Telr, hosted LLMs, Temporal, WorkOS) stay
  deferred until go-to-market.
- **Accuracy is the product.** Every number Sage or a panel shows must be derivable and correct.
  Convention: VOLUME metrics in **units**, VALUE metrics in **AED**, never mixed on one axis
  (reference: `backend/app/routes/kpis.py`).

## Status legend
✅ done · 🟡 in progress · ❌ not started · ⏭️ deferred

---

## Verified state (what's shipped)
The post-recovery remediation is complete; these are proven against the running stack and tests.

| Capability | State | Notes |
|---|---|---|
| Live sales pipeline (generator → Redis pub/sub → SSE) | ✅ | `/stream/*`, ticket-authenticated; consumers centralized in `hooks/useEventStream.ts` |
| Units vs AED accuracy | ✅ | Derived revenue (`unit_price_aed`), guarded by `tests/test_accuracy_guards.py` + `test_golden_numbers.py` |
| RBAC + tenant scoping | ✅ | region→store expansion, server-side; tenant scoping + RLS (FORCE-RLS opt-in) |
| Sage AI safety | ✅ | store-scoped chat, server-side AI gate, user-bound sessions, grounded refusing guardrails, `tests/test_ai_rbac.py` (10) |
| httpOnly cookie auth | ✅ | Bearer **or** cookie; logout clears + blacklists; `test_tokens.py::TestCookieAuth` |
| Sage engine | ✅ | `nl2sql` (guard + `sage_ro`), `sage2` (multi-part), `federation` (multi-source), `rag` (FTS) — all wired; deterministic fallback works with **zero LLM** |
| Diagnostics loop: detect→diagnose→recommend→accept | ✅ | worker `scan` job, 5 rules, `findings` + `recommended_action`/`action_type`, human-gated `accept-action` |
| Forecasting + Forecast Lab | ✅ | classical/LightGBM + optional deep tier; MAPE/WAPE backtest vs seasonal-naive |

**Loop status:** `measure` — the previously-missing stage — is **done and verified live** (Track 1):
the worker re-evaluates accepted findings and auto-resolves when the metric recovers.

---

## Track 1 — Close the loop: Measure / Outcome ✅ done (verified live)
Goal: after a recommendation is accepted, **prove whether it worked** and auto-resolve when it does.
- ✅ **Schema** (`database/migrations/034_finding_outcomes.sql`): `outcome_status`
  (`pending|improved|unchanged|worsened`), `metric_before`, `metric_after`, `measured_at` on
  `findings`, + a partial index on the accepted-and-open access path. Covered by `worker_rw`'s
  existing UPDATE grant (029).
- ✅ **Worker** — second BullMQ job **`measure`** (`worker/src/measure.js`, wired in `index.js`,
  hourly via `MEASURE_INTERVAL_MS`). For each accepted, not-yet-resolved finding it re-runs the
  rules over the current window and compares by `(rule, entity)` (week-stamp-independent): rule no
  longer fires → `improved` → **auto-resolve** (`resolved_by='system:measure'`); still firing →
  `worsened`/`unchanged` from the rule's own current metric. Pure decision logic isolated in
  `outcome.js` (no new metric math — reuses the rule outputs).
- ✅ **API** (`backend/app/routes/findings.py`): list exposes `outcome_status` + `metric_before/after`
  + `measured_at`, with `outcome=` and `measured=` filters; summary adds `by_outcome`.
- ✅ **UI** (`frontend/src/app/insights/page.tsx`): an **Outcomes** filter + a per-finding outcome
  block ("Resolved — metric recovered (X → Y)" / worsened / not-yet-recovered).
- ✅ **Tests**: `worker/src/measure.test.js` (6, zero-dep `node --test`) covers the classification
  matrix; `measure:once` added to CI smoke + worker unit tests to the build job.
- ✅ **Verified live (2026-06-27):** migration 034 auto-applied on boot; a still-firing accepted
  finding measured `unchanged` (stayed acknowledged, before=after), while a recovered (non-firing)
  one measured `improved` and **auto-resolved** (`resolved_by='system:measure'`, after=null). The
  API `measured=true` filter + `by_outcome` summary returned both correctly.

## Track 2 — Accuracy & security hardening ("tighten the screws") 🟡 (mostly done)
- ✅ **`USE_RLS_ROLE` flipped ON by default & verified.** Both prerequisite follow-ups turned out to
  be already implemented in `services/database.py`: `resolve_request_tenant` binds the tenant GUC
  **before** the session opens (GUC-after-auth ordering) and looks up API keys on the **owner**
  session (cross-tenant key→tenant lookup not RLS-filtered). The dev compose default is now
  `USE_RLS_ROLE=${...:-true}`. **Verified live:** two-tenant isolation (tenant 1 = 913k/10/50 vs
  tenant 2 = 1920/2/8), reads (analytics/findings/inventory/promotions) 200, a write (acknowledge)
  200, SSE stream-ticket 200, and `test_golden_numbers` 5/5 — all through the non-owner `app_rw`
  path. Set `USE_RLS_ROLE=false` to fall back to the owner connection.
- ✅ **`worker_rw` stale-volume auth bug fixed.** 029's `ELSE` branch now always asserts the login
  password; migration `035_worker_role_password.sql` repairs already-migrated volumes (029 won't
  re-run). Verified 035 applied and the worker still authenticates.
- ✅ **`test_golden_numbers` stabilized under load.** Per-request timeout is now generous + overridable
  (`GOLDEN_REQUEST_TIMEOUT`, default 30s) with a small backoff retry; health-probe timeout 3s→10s.
- ✅ **Accuracy guards extended** — guard 6 in `tests/test_accuracy_guards.py` asserts the finding
  `metric_value/metric_before/metric_after` ratios are never currency/units-formatted.
- 🟡 **README/doc honesty pass** (the remediation's last tail): reconcile every claim with code —
  synthetic data, units vs AED, what Sage can/can't do, what forecasting predicts, what's not built.
  (Note: the "Lulu store-name straggler" suspected earlier was a **stale volume**, not code — the
  seed in `init.sql` is already "Meridian".)

## Track 3 — Activate Sage's local LLM (no paid API) ⏳
Config + verification, not new code (the provider chain already picks it up):
- Bring up the `ollama` service (compose profile `ai`), set `OLLAMA_URL`, pull a small model
  (e.g. `llama3.2`).
- Verify free-form questions now route through NL→SQL (not the rule-based fallback), the allow-list
  guard (`services/nl2sql/guard.py`) still rejects injection/DDL/cross-tenant, tenant isolation holds
  (`sage_ro` + `app.tenant_id`), and narration stays grounded in the returned rows.
- Document the one-command activation here so it's reproducible.

## Track 4 — Cleanup (real items only) ❌
- Remove the 3 dead exports from `frontend/src/components/inventory/mockData.ts`
  (`generateMockInventory`, `generateMockSummary`, `generateMockCategories`); keep `generateAlerts` +
  `generateProcurementList` (still imported by `inventory/page.tsx`).
- The consolidation into this single file (retiring `docs/IMPLEMENTATION_PLAN.md`) is the
  doc-duplication cleanup.
- **Not debt — leave as-is:** `lib/api.ts` (typed facade) vs `lib/apiClient.ts` (low-level) is correct
  layering; `predictor.py` (operational) vs `forecasting/engine.py` (Lab/eval) serve different
  purposes; SSE consumption is already centralized in `hooks/useEventStream.ts`. Don't re-flag these.

## Track 5 — SaaS / commercial roadmap (near-term, free-tier first) 🟡
Buildable now with **no** external service; billing stays gated to go-to-market.
- **Tenant data export + delete-on-request** — GDPR-style, pure Postgres/app work on the existing
  tenant scoping + RLS.
- **Plan / metering scaffolding** — meter on `tenants.plan` + per-API-key usage (key infra exists);
  meter now, charge later.
- **Trust docs** — ToS / Privacy / DPA one-pagers next to the existing `SECURITY.md`.

---

## Deferred (needs a decision or an external service)
- **Billing** — Stripe/Telr subscriptions + metering (maps onto `tenants.plan` + API-key metering).
- **Notifications** — WhatsApp/email/Slack (Twilio/Resend/Slack); the worker's webhook dispatcher
  (`worker/src/notify.js`) is the drop-in point.
- **E-signature** — DocuSign / Dropbox Sign.
- **Enterprise infra** — Temporal/Camunda, WorkOS SSO/SAML/SCIM, PostHog+Sentry, Typesense/Meili,
  DuckDB/ClickHouse+dbt, Mapbox, embedded payments.
- **Next agentic increment (deliberately slow).** Today is autonomy level 0 — the system never acts
  on its own. The next step maps `action_type` → a *drafted* PO/alert via the existing procure-to-pay
  + `approval_rules` layer (still human-approved). Gated behind Track 1 (you can't safely raise
  autonomy until you can measure outcomes).
- **Other federation engines** — MySQL/BigQuery/Snowflake/Mongo/REST adapters register but error
  until their driver/service is wired (`services/federation/adapters/others.py`).

## Run / deploy notes
- Dev: `docker compose up -d` (postgres :5432, redis :6379, backend :8000, frontend :3000, worker).
- **Rebuild after dependency or backend changes**: `docker compose up -d --build backend` (and
  `frontend` to serve new routes).
- Migrations auto-apply on boot (numbered SQL in `database/migrations/`, tracked in
  `schema_migrations`). Re-trigger `init.sql` with `docker compose down -v && up`.
- Activate the LLM: `docker compose --profile ai up -d ollama`, set `OLLAMA_URL`, pull a model.
- Demo logins (password `Demo@2026!`): `atharva@retaildemo.app` (super_admin),
  `krishna@retaildemo.app` (regional_manager), `yash@retaildemo.app` (store_manager).
