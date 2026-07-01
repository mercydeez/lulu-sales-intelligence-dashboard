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

## Track 2 — Accuracy & security hardening ("tighten the screws") ✅ done
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
- ✅ **README/doc honesty pass** done: corrected the service count (5, + optional ollama), test
  count (200+), added the RLS-by-default + Sage + Insights/measure-loop descriptions, and refreshed
  the roadmap. (The "Lulu store-name straggler" suspected earlier was a **stale volume**, not code —
  the seed in `init.sql` is already "Meridian".)

**Track 2 is complete.** Remaining tracks: 3 (activate the local LLM), 5 (SaaS near-term).

## Track 3 — Activate Sage's local LLM (no paid API) ✅ done (verified live)
Config + verification, not new code (the provider chain already picks it up). **One-command
activation** (verified 2026-06-29):
```bash
docker compose --profile ai up -d ollama          # start the local LLM service
docker exec sales_ollama ollama pull llama3.2     # ~2 GB, one time
echo 'OLLAMA_URL=http://ollama:11434' >> .env      # provider chain needs URL + enable_local_ai (default true)
docker compose up -d backend                       # recreate so the env is picked up
```
- ✅ **Provider chain active**: `get_provider_chain()` → `['ollama']` once `OLLAMA_URL` is set.
- ✅ **NL→SQL grounds for real**: "top 3 stores by units sold" → `nl2sql ok=True, 3 rows`,
  `grounded: True`, `confidence 1.0`, critic pass, SQL attached as evidence — correct store-scoped
  answer (was the rule-based fallback before).
- ✅ **Guard holds with the LLM live** (`services/nl2sql/guard.py`, tested directly): rejects DDL
  (`DROP`), DML (`DELETE/UPDATE/INSERT`), stacked-statement injection, non-allow-listed relations
  (even `users`/`sales_fact_view` — only the `sage_*` semantic views are queryable), and `pg_`
  catalog access.
- ✅ **Defense in depth**: `sage_ro` is provably read-only (a `DELETE` as `sage_ro` → *permission
  denied*); data intact after adversarial prompts; **RBAC store scope holds** — a store_manager
  (Al Barsha only) asking for "every store, all locations" got back only Al Barsha.
- ⚠️ **Known limitation (honest):** `llama3.2:3b` produces valid text-to-SQL **inconsistently** —
  schema-heavy queries can emit an invalid column/join and fall back. The deterministic responder
  (now revenue-accurate, Phase 1) is the safety net and is always correctly tenant/store-scoped. A
  larger local model (or the optional external provider) improves the grounded-hit rate; the floor
  is safe either way.

## Track 4 — Cleanup (real items only) ✅ done
- ✅ The 3 dead exports were already removed from `frontend/src/components/inventory/mockData.ts`;
  the file now exports only `generateAlerts` + `generateProcurementList` (both still imported by
  `inventory/page.tsx`). Verified: no `generateMock*` references remain anywhere in `frontend/src`.
- The consolidation into this single file (retiring `docs/IMPLEMENTATION_PLAN.md`) is the
  doc-duplication cleanup.
- **Not debt — leave as-is:** `lib/api.ts` (typed facade) vs `lib/apiClient.ts` (low-level) is correct
  layering; `predictor.py` (operational) vs `forecasting/engine.py` (Lab/eval) serve different
  purposes; SSE consumption is already centralized in `hooks/useEventStream.ts`. Don't re-flag these.

## Track 6 — UI overhaul: immersive, dynamic, color-coded 🟡 (foundation + key screens)
Decision: polish **in-place** (no shadcn migration) + add **framer-motion**; **dark mode removed**;
"rich but tasteful" motion; foundation-first then key screens.
- ✅ **Foundation** — removed dark mode (ThemeContext/toggle/script/`html.dark`); immersive tinted-mesh
  canvas + dimensional surfaces + `hero-mesh`/accent gradients + `--series-*` palette (globals.css);
  Tailwind `series` scale + card/elevated/glow shadows + gradient images; framer-motion + shared
  motion primitives (`components/ui/motion.tsx`: Reveal/Stagger/RevealItem/MotionCard) under
  `MotionConfig reducedMotion="user"`; `lib/chart.ts` (Recharts theming: CHART_SERIES, axis/grid/
  tooltip, `seriesColor()`); rebuilt `ChartFrame` (accent rule + motion).
- ✅ **Login** — immersive `hero-mesh` panel with animated orbs + staggered reveal; brand-consistent
  teal accents; animated demo tiles + CTA. All auth logic intact.
- ✅ **App shell** — animated sliding active-nav indicator (shared `layoutId`) + accent bar.
- ✅ **StatCard / KPIs** — motion hover-lift + entrance, tinted icon chips, and the gradient variant
  now **tone-colored** (was always teal); KPI grids stagger in.
- 🟡 **Remaining screens** — Analytics, Insights, Inventory next (apply `lib/chart.ts` theming to the
  Recharts charts for full color-coding + motion), then the other ~18 routes. The shared primitives
  already lift every screen that uses `StatCard`/`ChartFrame`/`Card`.
- **Verify**: `npm run dev` in `frontend/` (compose serves a prebuilt bundle, so dev server shows
  changes). `tsc --noEmit` + `next build` clean (26/26 pages).

## Track 5 — SaaS / commercial roadmap (near-term, free-tier first) ✅ done
Buildable now with **no** external service; billing stays gated to go-to-market.
- ✅ **Tenant data export + delete-on-request** — GDPR-style, pure Postgres/app work on the existing
  tenant scoping + RLS (shipped as Phase 12: `/api/data-rights/*`, migration 039 `data_requests`).
- ✅ **Plan / metering scaffolding** — `services/plan_limits.py` defines per-plan quotas (free/starter/
  growth/enterprise; `None` = unlimited) and `usage_for_tenant()` meters API requests / active keys /
  users against them. `GET /api/tenants/usage` (admin, tenant-scoped, read-only, advisory `over_quota`
  — meter now, charge later) surfaces it; the **Developer Portal → Overview** renders a "Plan & usage"
  card. Verified live (tenant 1 = enterprise/unlimited, users=3) + `tests/test_plan_limits.py` (7).
  Honest limitation: the request meter is a **lifetime** total; rolling-month windowing (a usage-events
  table) is the later enhancement, called out in the response (`window: "lifetime"`).
- ✅ **Trust docs** — ToS / Privacy / DPA drafts live in `docs/legal/` (marked "draft — legal review
  required"); legal sign-off is a `MANUAL_CHECKS_REQUIRED.md` blocker, not an engineering gap.

---

## Track 7 — UAE commercial control plane (in progress)
Taking Retail IQ from "deployment-ready MVP + SaaS scaffolding" to a UAE/GCC-ready
commercial SaaS. Phases are additive and tenant-scoped; VAT/TRN/legal content is data
modelling only and stays marked **"Draft — requires review by a qualified UAE legal/tax
professional before production/customer use."**
- ✅ **Phase 1 — UAE tenant legal/billing profile.** `tenant_billing_profile` (migration
  `041`, one row per tenant, RLS + `current_tenant_id()` like the rest of the schema):
  legal name (EN/AR), trading name, **TRN**, trade licence, **emirate** (7-emirate enum),
  **mainland/free-zone**, VAT-registered, registered/billing address, **AED + Asia/Dubai +
  language** defaults, industry/store/SKU/procurement-type, billing & finance contacts.
  Server-side validation in `services/uae_profile.py` (TRN=15 digits, emirate/jurisdiction/
  currency/email enums) shared by the API and tests. API: `GET`/`PUT /api/tenants/billing-profile`
  (admin-scoped, tenant-bound, partial upsert). UI: `/settings/company` (admin-only, loading/
  error/permission states) + a link card on `/settings`. Demo tenant 1 seeded with a UAE profile.
  **Tests:** `tests/test_tenant_profile.py` — 11 pure-validation tests pass locally; 2
  route-registration/auth tests need the container deps (`sse_starlette`) per the known local
  env-drift trap. `py_compile` clean.
- ✅ **Phase 2 — tenant lifecycle + platform-admin ops.** Migration `042`: `tenants.status`
  constrained to 9 lifecycle states (trial→…→deleted) + `status_reason/changed_at/changed_by`;
  `tenant_status_events` (append-only transition audit) and `tenant_admin_notes` (operator
  support notes). These are operator tables — cross-tenant, super-admin-gated, intentionally NOT
  under tenant RLS (consistent with `tenants` itself). State machine + access-gating in
  `services/tenant_lifecycle.py` (allowed-transition graph; `BLOCKED_STATES` = suspended/cancelled/
  deleted). **Enforcement:** `get_current_user` blocks blocked-status tenants (403); super-admins
  bypass; **fails open** on lookup error so a DB hiccup never locks everyone out. API (super-admin):
  `PATCH /api/tenants/{id}/status`, `GET .../status-events`, `GET`/`POST .../notes`. UI:
  `/admin/tenants` operator console (status transitions + reason, history, notes) linked from
  `/admin`. **Tests:** `tests/test_tenant_lifecycle.py` 10/10 pass; `py_compile` clean.
- ✅ **Phase 3 — billing-period usage metering + soft quotas.** Migration `043`: append-only
  `usage_events` (tenant-scoped + RLS). `services/usage_metering.py`: billing period = **calendar
  month in Asia/Dubai** (`current_period`, pure), `record_usage` (best-effort, never raises —
  metering can't break a request), `usage_summary` (per-dimension meters), `check_quota` (soft).
  Metered dims: sage_messages / forecast_jobs / exports / imports / api_requests, with separate
  `USAGE_LIMITS` per plan (enterprise = unlimited). **Enforcement is OFF by default**
  (`ENFORCE_USAGE_QUOTAS=false`) so the demo/MVP/tests are unaffected — flip it on to return 429
  over-limit. Wired (best-effort): Sage `/chat` + `/chat/stream` (`sage_message`), data export
  (`export`). API: `GET /api/tenants/usage/period` (kept the old lifetime `/usage` endpoint intact
  to avoid regressing the dev portal + `test_plan_limits`). UI: "This billing period" card on the
  Developer Portal overview. **Tests:** `tests/test_usage_metering.py` 8/8 pass (period math incl.
  Dec→Jan rollover, plan table, enforcement flag); `py_compile` clean.
- ✅ **Phase 4 — manual UAE billing + VAT invoices.** Migration `044`: `subscriptions`, `invoices`
  (VAT-aware: supplier/customer TRN snapshot, `subtotal_aed`/`vat_rate`/`vat_amount_aed`/`total_aed`,
  PO number, payment terms/instructions, **e-invoicing readiness fields**), `invoice_lines` — all
  RLS-scoped (lines via parent). `services/billing.py`: provider abstraction (manual / bank_transfer
  / purchase_order usable now; stripe/telr/paytabs/network/checkout **gated until configured**),
  pure VAT math (line VAT-exclusive @ 5%, totals reconcile line-by-line, fils rounding), invoice
  numbering, plan prices (AED; enterprise = custom). API `/api/billing`: `GET providers`,
  `GET subscription`, `GET/POST invoices`, `GET invoices/{id}`, `POST .../issue`, `POST .../mark-paid`
  (tenant-admin reads own; super-admin issues + records manual/bank-transfer payment). UI:
  `/settings/billing` (subscription + invoices + VAT breakdown modal) linked from `/settings`. All
  VAT/invoice surfaces carry the **legal-draft** note. **Tests:** `tests/test_billing.py` 10/10.
  Deferred to P1: invoice PDF, real gateway/e-invoicing integration, operator issue-invoice UI form.

### Partial items completed to final (P1)
- ✅ **Phase 5 — E-invoicing submission lifecycle.** Built on 044's e_invoice_* fields:
  `services/einvoicing.py` (provider-abstracted; built-in 'mock' clearing house auto-accepts a
  well-formed issued invoice; ZATCA/UAE-FTA gateways gated until configured). `POST /api/billing/
  invoices/{id}/einvoice/submit` (super-admin) + e-invoice status badge & submit button in the
  billing invoice modal. Audited (`invoice_einvoiced`). Tests `test_einvoicing.py` 8/8. Draft —
  UAE e-invoicing accreditation required.
- ✅ **Phase 6 — Unified audit log.** `security_events` (category='audit') is the canonical log;
  wired new audit events (`tenant_status_changed`, `billing_profile_updated`, `invoice_created/
  issued/paid/einvoiced`, field names only — never values). New `GET /api/security/events/export`
  (CSV/JSON, RLS-scoped, PDPL evidence). New `/audit` admin UI (filters + export) + nav entry.
- ✅ **Phase 7 — In-app notifications + preferences.** Migration `045`: `notifications` (user_id
  NULL = tenant-wide) + `notification_preferences`, RLS; worker_rw grant so the BullMQ worker
  posts finding notifications (`worker/src/notify.js`). `services/notifications.py` (best-effort,
  never breaks an action; email is a logged stub). `/api/notifications` (list/unread-count/read/
  read-all/preferences). Wired emits: invoice issued + lifecycle change → tenant admins; critical
  findings → tenant-wide. The Topbar bell now merges these with operational alerts; preferences
  card on `/settings`. Tests `test_notifications.py`.
- ✅ **Phase 8 — Arabic/i18n/RTL for the new surfaces.** New nav/title keys (EN+AR) for company/
  billing/audit/tenant-console/notifications; `t()` wired into the new page titles. Audited the new
  screens — all RTL-safe (logical `text-start`/`ms-auto`/`start-0`; no hard left/right/pl/pr/ml/mr).
  Full per-string Arabic translation of every screen remains the app-wide ongoing effort (the repo's
  i18n was always an EN/AR + RTL shell, not full i18n).

### Agentic increment — autonomy level 1 (shipped)
- ✅ **Action drafting.** Extends the loop: detect → … → accept → **draft (system)** → **approve
  (human)** → execute (human). Migration `046` `action_drafts` (RLS). Deterministic mapper
  `services/action_drafting.py` (`build_draft`, **no LLM** — every word derivable): `review_supplier`
  → supplier email, `review_pricing` → markdown proposal, `promote` → promotion proposal,
  `investigate` → review task. API `/api/action-drafts` (`POST /from-finding/{id}`, list, get,
  `approve`, `reject`). **Approval records a human decision and NEVER sends/executes anything** —
  execution stays manual (autonomy L1, not L2). Audited (`action_drafted`/`action_draft_approved`/
  `_rejected`) + notifies. UI: `/action-drafts` review page (artifact + approve/reject) + nav entry +
  "Draft action" button on Insights findings. Tests `test_action_drafting.py` 8/8. (PO replenishment
  drafting already exists separately in procurement via `approval_rules`.)

### Demo → pilot unlock (the real-data path)
- ✅ **CSV import wizard (#1).** Migration `047` `import_jobs` (RLS, import history). Pure
  parse/map/validate core `services/csv_import.py` (no I/O — unit-tested): types `stores`, `items`,
  `sales`, `inventory`; per-field validators **enforce units-vs-AED** (a unit count can't validate as
  money; AED rejects junk/negatives; dates normalise to ISO). API `/api/imports` (`types`, `analyze`,
  `validate`, `commit`, history) — operator-gated, tenant-scoped, commit in one transaction, **audited
  (`data_imported`) + metered (`import` usage) + notifies**; sales/inventory resolve store/item by name
  (unresolved rows skipped + reported). UI: `/imports` wizard (upload → auto-map columns → validate
  preview → commit) + nav. Tests `test_csv_import.py` 11/11.
- ✅ **ROI / AED calculator (#2).** `services/roi.py` — **only honest, derivable numbers** from real
  inventory + sales: inventory value at retail, dead-stock AED (+count, no sale in 60d), estimated
  stockout opportunity-loss AED (projected, flagged estimate), days-of-supply; cost-dependent metrics
  (cash-at-cost, GMROI) are **null with a `needs: cost` flag when no cost data — never fabricated**.
  Pure `build_summary` unit-tested. API `GET /api/roi/summary`. UI: `/value` screen (headline AED =
  dead-stock + projected stockout loss; metric grid; empty-state → import) + nav. Tests `test_roi.py` 7/7.
  This is the pair that converts the stack from demo to pilot-ready: a retailer imports their data and
  sees their own AED number.
- ✅ **Pilot-in-a-box (#3).** A self-contained pilot sales can run without engineering. (a) Migration
  `048` enriches the **demo tenant** inventory (unit cost → cash-at-cost + GMROI, realistic last-sale
  dates, deterministic stockouts + dead-stock tail) so `/value` shows a complete AED story out of the
  box — clearly **demo** data, not a real-customer claim. (b) Downloadable **UAE sample CSVs**
  (`GET /api/imports/sample/{type}` + "Download sample" in the wizard) so a prospect can try the full
  import flow before their own data. (c) An honest **security/PDPL one-pager** (`docs/product/
  SECURITY_ONE_PAGER.md`) + in-app **`/trust`** page (tenant isolation, RBAC, audit+export, data
  rights, what-we-never-do) linking to the live Audit + data-rights features — for a buyer's security
  review. All legal wording draft-marked. Tests extended (`test_csv_import.py` samples parse).
- ✅ **Shareable CFO ROI artifact.** `GET /api/roi/report?fmt=html|csv` — a finance-team-ready
  inventory-value report. Pure builders `build_report_html` / `build_report_csv` in `services/roi.py`:
  branded, self-contained, **browser-printable HTML** (→ PDF, no PDF dependency) + CSV, carrying the
  company legal name, the headline AED, and a **methodology column** (every number's derivation) so a
  CFO can reconstruct it; cost-dependent metrics print "needs cost data", never fabricated; draft
  disclaimer. "Report"/"CSV" download buttons on `/value`. Tests `test_roi.py` 10/10.
- ✅ **Outcome-based pricing (measure-loop capstone).** Fee = base + a share of **operator-confirmed**
  realised value, with a savings guarantee that **waives the variable portion** if savings < N× base —
  "you only pay on savings we both agree happened." Migration `049` `outcome_pricing_plans` +
  `value_realizations` (RLS). `services/outcome_pricing.py`: pure `build_statement` (non-circular
  fee/guarantee math, unit-tested); lazy realization creation from `findings.outcome_status='improved'`
  (no fabricated values — operator confirms each AED amount); period statement. API
  `/api/outcome-pricing` (plan get/put, realizations list/confirm/dismiss, statement, **generate draft
  VAT invoice** via the Phase-4 billing layer). UI `/outcome-pricing` (statement, plan config, confirm
  realised value, value-to-fee ratio) + settings link. Audited. Tests `test_outcome_pricing.py` 7/7.
  This is the pricing wedge the measure loop uniquely enables — no competitor captures "did it work?"
  per recommendation, so none can credibly price on proven outcomes.
  - ✅ **Per-finding value suggestion (honest).** `valuation_context` grounds each pending realization
    with the entity's **real** 30-day / daily revenue and a **conservative suggested figure**
    (entity daily revenue × a 3-day recovery window, method shown). The platform never fabricates an
    attribution — the suggestion pre-fills the input as a starting estimate the operator confirms or
    edits (system proposes, human disposes). Pure `suggest_from_daily` tested.

### Activation, team, UAE intelligence & GTM (autonomous round 2)
- ✅ **Guided onboarding / activation.** `/api/auth/onboarding` extended to 5 steps with deep-link
  hrefs (company profile → import → see value → invite team); existing dashboard `OnboardingChecklist`
  now shows a CTA per step + links to a new full-screen `/welcome` page. Drives time-to-first-value.
- ✅ **Team management.** `routes/team.py` (`GET /api/team`, `/seats`, `PATCH {id}/role`, `{id}/status`)
  — tenant-scoped, can't change/disable self, roles stay within the `user_role` enum. UI `/settings/team`
  (invite via existing `/api/auth/invite`, role dropdown, enable/disable, seat usage vs plan). Audited.
- ✅ **VAT invoice print/PDF.** `build_invoice_html` (pure) + `GET /api/billing/invoices/{id}/print` —
  browser-printable UAE Tax Invoice (both TRNs, VAT breakdown, payment instructions); "Print / PDF" in
  the billing modal. `test_billing.py` 11/11.
- ✅ **UAE retail intelligence.** `services/uae_intelligence.py`: real UAE retail **calendar** (Ramadan/
  Eid/DSF/back-to-school/National Day — lunar dates flagged approximate), **emirate performance**,
  **branch-transfer suggestions** (overstock→stockout, human-approved), **dead-stock by emirate** — all
  from real data. API `/api/uae-intelligence/*`, UI `/uae-insights` + nav. `test_uae_intelligence.py` 6/6.
  Verified live: emirate revenue split + 15 transfer suggestions.
- ✅ **CSV import: suppliers type** added (defer PO import + row-tagged rollback — they need a schema
  change on every target table). `test_csv_import.py` 12/12.
- ✅ **Commercial pricing + operator metrics + GTM doc.** `plans_catalog` + `GET /api/billing/plans`,
  `/pricing` page (AED plans, outcome-pricing CTA). `GET /api/tenants/metrics` (super-admin: tenants by
  status/plan, users, **estimated MRR**) surfaced on `/admin/tenants`. `docs/product/GTM_30_60_90.md`.
- **Verified:** frontend `next build` clean (40/40 pages); all new endpoints 200 live.

### Developer platform maturity (autonomous round 3)
- ✅ **Webhook event catalog + real emits.** Published `EVENT_CATALOG` (15 events) in
  `webhook_service.py` + `GET /api/webhooks/events`, surfaced in the Developer Portal → Webhooks
  ("Available events", with the HMAC-signature note). Wired real signed emits via the existing
  `dispatch_event_background`: `billing.invoice.created` (invoice issued), `import.completed` (CSV
  commit), `action.drafted` (action draft created) — alongside the existing procurement emits.
  Idempotency keys intentionally deferred: the public API has no critical state-changing writes (only
  the Sage query), so there's nothing to make idempotent yet. `next build` clean (40/40).

---

## Deferred (needs a decision or an external service)
- **Billing** — Stripe/Telr subscriptions + metering (maps onto `tenants.plan` + API-key metering).
- **Notifications** — WhatsApp/email/Slack (Twilio/Resend/Slack); the worker's webhook dispatcher
  (`worker/src/notify.js`) is the drop-in point.
- **E-signature** — DocuSign / Dropbox Sign.
- **Enterprise infra** — Temporal/Camunda, WorkOS SSO/SAML/SCIM, PostHog+Sentry, Typesense/Meili,
  DuckDB/ClickHouse+dbt, Mapbox, embedded payments.
- **Agentic autonomy.** Level 1 (system **drafts**, human approves) shipped — see "Action drafting"
  above. Level 2 (system **executes** an approved low-risk action, e.g. auto-send an approved
  supplier email or auto-place a PO under the `approval_rules` threshold) remains deferred — it needs
  an execution adapter + a tighter outcome-measurement guardrail before autonomy is raised.
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
