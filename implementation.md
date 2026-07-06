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

## 12-Month Blueprint execution (see `docs/EXECUTION_BLUEPRINT_12M.md`)
The audit-derived Q1→Q4 plan. Tracked here as items land.

### Engineering ownership & parallel-development workflow ✅ done (verified)
Organized the repo for three developers (Atharva/Krishna/Yash) to work in parallel with near-zero
merge conflicts. **No product features** — refactors, docs, and repo structure only.
- ✅ **Killed the two worst merge-conflict hubs (behavior-identical refactors).** Backend router
  registration moved out of `main.py` (42 imports + 35 `include_router` lines) into
  `backend/app/routes/registry.py` — adding an endpoint is now a one-line append there. Frontend
  `navItems`/`NAV_ICONS`/`NavItem` moved out of the 200-line `Sidebar.tsx` into
  `frontend/src/config/nav.tsx` (CommandPalette repointed too) — adding a page is a one-line append.
  Verified: app imports (35 routers, 244 routes), `tsc` clean, backend router-adjacent suites green.
- ✅ **Bounded-context ownership** (not by page): Atharva = AI/Sage/Decision/Briefing/Role-Experience
  vertical (spans backend + frontend + `worker/`); Krishna = all other backend + DB + auth + infra;
  Yash = all other frontend + design system. Rule: *bounded-context beats layer where they overlap*.
- ✅ **Governance docs authored from scratch:** `TEAM_OWNERSHIP.md`, `PROJECT_STRUCTURE.md`
  (subsystem map + dependency graph), `GIT_WORKFLOW.md` (trunk-based), `CONTRIBUTING.md`,
  `.github/CODEOWNERS` (real handles: Atharva=@mercydeez, Krishna=@krish2105, Yash=@Yashpetkar7),
  and a PR template. Pointers added to `CLAUDE.md`/`AGENTS.md`/`docs/README.md`.
- ➡️ **Team rollout (not executed here):** add the three owners as repo collaborators, PR
  `prototype-evolution-accuracy-bullmq → main`, enable branch protection on `main`.

### Store-manager workflow friction fixes — S1 blockers ✅ done (verified live)
From the first-time Store-Manager UX audit. Root causes were **dropped context between steps** and
**numbers that disagree or aren't scoped to me**. Fixed the roots so workflows are continuous; no new
features.
- ✅ **Reorder → the exact order, item preserved (S1-1, the #1 blocker).** Each forecast reorder
  decision now deep-links to the draft PO that already carries that item
  (`_open_po_for_items` in `decision_center.py` → `href=/procurement/po/{id}?item={name}`). The PO
  page (`procurement/po/[id]`) reads `?item=`, **highlights + scrolls to that line**, shows a
  "You're here to reorder X" banner, and — crucially — **Approve now lives on the same page** (review
  and approve no longer split across two screens; Print demoted to secondary). Home "will run out"
  cards and the Decision Center both route straight there ("Review & approve order"). Verified: home
  card → PO-01-00001 with Heinz highlighted → Approve → `POST …/status 200`.
- ✅ **"Created 0 draft POs" dead-end (S1-2).** `generate_draft_pos_from_reorder` now returns a
  plain-language reason instead of a bare 0: "All N item(s) that need reordering are already on the
  draft POs below — review and approve them" (or no-supplier / nothing-to-reorder variants).
- ✅ **Two different 7-day revenue numbers on one screen (S1-3).** The 7-day revenue is stated once —
  in the hero verdict. Dropped the duplicate `total_revenue_week` KPI tile from the store & regional
  configs (replaced with today/stock/workload KPIs), so no metric appears twice with two computations.
- ✅ **"AED 3,060,650 at stake" for a one-store manager (S1-4).** `roi_summary` now accepts `allowed`
  stores and scopes every figure; the briefing + `/api/roi` pass it. A store manager's "at stake"
  went **3,060,650 → 214,150** (their store), and is believable. Chain roles (super_admin) unchanged.
- ✅ **"Am I OK or not?" mixed signals (S1-5).** The store stock card now connects the two horizons —
  "Nothing out of stock now — but N running low… act before they run out" — instead of a flat "no
  stockouts" that contradicted the "will run out" cards. (Residual: the inventory reorder-level count
  and the forecast reorder count are different measures and can still differ — noted, not yet unified.)
- ✅ **Tests:** 66 green across decision-center/role-experience/roi/briefing/procurement; `tsc` clean.

### Role Experience Engine — Wave 1 ✅ done (verified live)
The infrastructure from `docs/product/ROLE_EXPERIENCE_BLUEPRINT.md`: every role gets a different
homepage, navigation, Sage persona, KPI set, and decision scope from **configuration**, not
duplicated pages. One engine, many experiences. Wave 1 covers the roles that exist in RBAC today
(`store_manager`, `regional_manager`) + a `_default` that preserves current behavior for everyone
else. Roles needing data we don't have (HR attendance, Loss Prevention POS grain) are intentionally
absent.
- ✅ **Config-as-data** `services/role_experience.py`: one `_CONFIGS` record per role (persona pack,
  homepage `zones`, KPI descriptors → existing endpoints, nav manifest → existing routes, decision
  scope, notification defaults). `resolve_config` deep-copies; unknown roles degrade to `_default`.
  **No role-specific code paths anywhere else.** Adding a role = adding a config here.
- ✅ **API** `GET /api/experience` returns the caller's resolved config (server-driven UI).
- ✅ **Decision scope** (chain/region/store) threaded through the decision center: `scope_decisions`
  filters region/store users to their own stores (chain-wide findings excluded); a store manager's
  triage collapses the regional lane into "store" (they're the on-the-ground owner). Wired into
  `/api/decisions`, `/triage`, `/summary` via `decision_scope_for(role)`.
- ✅ **Sage persona** injected: `get_system_prompt(role)` appends the role's persona fragment
  (Store Coach / Regional Coach) — voice/focus only, explicitly subordinate to the grounding &
  honesty rules; threaded through `get_or_create_context(session_id, role)` on v2 + v3 paths.
- ✅ **Frontend engine** (no new dashboards): `contexts/ExperienceContext` (fetches config, fails
  open to default); `app/today/page.tsx` — a **generic zone renderer** (`ZONE_REGISTRY`: verdict /
  kpis / decisions / approvals / stock) with **zero role-specific code**; `Sidebar` renders the nav
  manifest (icon-name registry) or falls back to the full built-in sidebar when `nav === null`;
  `ClientLayout` redirects to the config `home`; `ChatBot` header shows the persona title. i18n
  EN/AR for the new nav keys.
- ✅ **Tests** `tests/test_role_experience.py` (14): distinct configs per role, unknown→default,
  copies-not-references, KPI descriptors reference valid sources/formats, nav references existing
  routes only, persona present but grounding wins, and the scope filter (chain sees all / store sees
  only its store & no chain-wide / region sees its stores / store triage has no regional lane).
  42 backend tests green; `tsc --noEmit` clean.
- ✅ **Verified live (2026-07-05):** one `/api/experience` → three experiences. **Store Manager
  (yash):** `/today` = Sage **Store Coach**, store-scoped verdict (AED 274k = Al Barsha alone),
  KPIs Sold-today/Revenue-today/Stockouts-now/Decisions-waiting, decisions all Al Barsha, 4-item nav
  (Today·My Work·My Store·Alerts). **Regional Manager (krishna):** the *same page* = **Regional
  Coach**, region-scoped verdict (AED 1.01M = 3 Dubai stores), KPIs incl. Trend + At-stake, 5-item
  nav (+Approvals, My Stores). **super_admin:** `_default`, full sidebar, `/` home — unchanged.
  Decision triage entities confirmed scoped: yash→Al Barsha only, krishna→Dubai stores, atharva→all.

### E3-1 — Daily Executive Briefing ✅ done (product surface)
The audit's "single highest-leverage feature" — the executive retention hook. Assembly of
existing data into one morning screen; no new ML, no fabrication.
- ✅ **Service** `services/briefing.py`: pure `build_briefing(raw)` (analyst-style narrative +
  WoW math + decision/leak assembly + win precedence) — unit-tested without a DB, mirroring
  `roi.py`; async `generate_briefing(db, tenant_id, allowed)` composes KPIs (week-over-week
  revenue/units), open findings ("why"), reorder risks + actionable findings ("decide today"),
  a measure-loop recovery else a growth "win", the UAE calendar + 14-day forecast, and the
  dead-stock+stockout **AED cost of inaction**. Tenant + accessible-store scoped.
- ✅ **API** `routes/briefing.py` → `/api/briefing`: `GET /` (JSON) + `GET /print` (self-contained
  emailable/printable one-pager, the same content you'd email a CEO). Registered in `main.py`.
- ✅ **UI** `/briefing` (`app/briefing/page.tsx`): **AI-first premium redesign** — a `hero-mesh`
  "Sage, your AI Chief of Staff" brief that types out a client-composed verdict (mood-aware: strong/
  steady/soft/attention), one **focal decision** ("What needs you") with a Sage recommendation +
  primary CTA, an editorial numbers strip (big tabular AED + trend), a tight "why it's moving" list,
  a forward-looking "on your radar" (season + cost-of-waiting), and a quiet win close. Orchestrated
  reveal + typewriter respect `prefers-reduced-motion`; premium "Sage is reading your stores" loading
  state; Sage-voiced empty state. All narrative composed **client-side from the existing API** (no
  backend change). Deep-links to Insights/Procurement/Value; "Email brief" download. Nav entry
  (Sunrise icon, under Dashboard) + i18n `nav.briefing` (EN/AR); auto-appears in the command palette.
  `tsc --noEmit` + `next build` clean (41/41 pages).
- ✅ **Tests** `tests/test_briefing.py` (10): WoW %/trend, decision merge+ranking, leak math, win
  precedence, empty-state, printable HTML. `tsc --noEmit` clean.
- **Deferred (ops, per the "product over infra" directive):** the 07:00 Asia/Dubai scheduled email
  send + unsubscribe. `/api/briefing/print` is the ready email body; only the scheduler/SMTP wiring
  (a non-blocking ops task) remains.

### E3-2 — AI Decision Center ✅ done (verified live)
An **inbox of decisions**, not a dashboard: every card carries the problem, business impact (AED),
evidence, confidence, recommended action, and expected outcome — money-ranked, Sage-voiced.
- ✅ **Service** `services/decision_center.py`: pure builders (`estimate_impact`, `confidence`,
  `expected_outcome`, `evidence_facts`, `build_decision`, `build_reorder_decision`, `sort_decisions`)
  — **everything derived from the finding's own evidence** (worker `rules.js` payloads): revenue rules
  → weekly AED gap; returns rules → units (returns carry no price — AED never fabricated); laggard →
  no figure, basis says why. Confidence is deterministic + explainable (window completeness,
  deviation-vs-threshold ratio, scale floor — factors listed, score is their sum). Composer merges
  open findings + forecast reorder risks (best-effort), sorted money-first.
- ✅ **API** `routes/decisions.py` → `/api/decisions` (`?state=pending|decided`) + `/summary`
  (nav badge: pending count + AED/week at stake). **Read-only by design** — approve/dismiss/draft
  reuse the tested `findings` (`accept-action`, `resolve`) and `action-drafts` endpoints, so the
  measure loop keeps proving outcomes unchanged.
- ✅ **UI** `/decisions` (`app/decisions/page.tsx`): executive inbox — Sage header ("N decisions
  ready · ~AED X/week at stake"), Needs-decision/Decided tabs, severity-accented cards with evidence
  chips, confidence pill, "Sage recommends + expected outcome" block, expandable "Why this
  confidence & impact" (factors + impact basis), **Approve / Draft the action / Dismiss** (reorder
  cards deep-link to Procurement). Top-12-by-money with "Show all N". **Decided tab shows the measure
  loop**: "Measuring…" → "Worked — metric recovered" / "No change yet" / "Worsened", with approver +
  date. Nav entry (Scale icon, badge = pending count) + i18n EN/AR.
- ✅ **Tests** `tests/test_decision_center.py` (13, pure): honest-derivation contract (AED only where
  derivable, units for returns, laggard claims nothing), confidence determinism/monotonicity,
  money-first sorting (AED-less critical sorts after any AED), summary sums only derivable AED.
- ✅ **Verified live (2026-07-05):** 55 pending decisions ranked AED 131,295 → … per week at stake
  (total ~AED 1.6M/week); approved "Seafood revenue down 88.8%" in the UI → moved to Decided with
  "Measuring…" + approver/date; `tsc --noEmit` clean; 23 pure tests green.

#### E3-2b — COO triage / delegation redesign ✅ done (verified live)
Reframed the inbox from "55 equal cards" to **the 3 that need an executive + the rest routed**, cutting
what a COO must read to ~3.
- ✅ **Triage engine** (`services/decision_center.py`, pure + tested): `strategic_score` (AED/units
  weighted by scope — chain-wide > store of equal money, so a category slump outranks one store's
  drop) picks the **top-3 executive** calls; `route_owner` sends the rest to **regional managers**
  (store performance, grouped by region via `_region_map` stores→regions), **store managers** (larger
  replenishment), or **Sage automation** (small POs ≤ `AUTO_PO_MAX_UNITS` + recurring supplier
  audits). Extra chain-wide issues fold into "N more to review", not a delegation lane. Each routed
  decision carries a plain-language `routing_reason`. **Bug fixed:** `build_decision` was dropping
  `entity_id`, so region grouping silently fell back to "Unassigned" — now carried through.
- ✅ **API** `GET /api/decisions/triage` → `{executive:{decisions[3], more}, lanes:[regional|store|
  automate], total, routed_count, at_stake_aed_per_week}`.
- ✅ **UI** `/decisions` rebuilt: a `hero-mesh` **triage banner** ("Sage read N · 3 need your decision
  · M routed"), a **"Decide now — your 3 calls"** section (full cards), and collapsible **delegation
  lanes** (regional shows region chips + per-region groups; automate is violet with an "enable
  automation / see drafts" note). Cards keep full explainability + Approve / Draft / Dismiss.
- ✅ **Tests** `test_decision_center.py` extended to 20 (from 13): exec picks exactly 3, scope
  weighting, owner routing (reorder threshold, high-return → automate, store → regional), regional
  grouping by region, "more chain-wide" fold, honest AED totals.
- ✅ **Demo volume reset** (`docker compose down -v && up`) → the seed now shows **Meridian**
  hypermarket names (was a stale "Lulu Hypermarket" volume). **Honest note:** the fresh Kaggle seed is
  smooth week-over-week (store revenue −0.5%…+3.1%), so the diagnostics loop currently yields only
  stockout/reorder decisions (exec + store lanes); the executive-category / regional / automate lanes
  populate once real week-over-week findings accumulate — the routing for all owner types is proven
  by the unit tests. Verified live: banner "10 → 3 + 7", "Store managers · 7" lane with per-card
  routing reasons, Meridian names throughout.

### Enterprise polish — Sage voice, trust & failure recovery ✅ done (verified)
A product-quality pass over the AI/Experience surfaces (**no new features**): make Sage
sound like a senior retail operator, and stop owned surfaces from lying or dead-ending when
a fetch fails. Scope stayed inside the AI/Experience vertical (`ChatBot.tsx`, `/today`,
`/insights`, `ai_assistant.py`).
- ✅ **Sage (ChatBot) speaks in the caller's persona**, not a generic "analytics assistant":
  the opening line is built from the role persona title and only advertises voice when the
  role actually has it (it previously pointed every user at a mic some roles can't use).
- ✅ **Sage's zero-LLM fallback reads like an operator, not an apology.** Dropped the "I could
  not generate an AI-written answer" preamble; it now presents the live operational picture
  (today's units + AED, alerts, stock, approvals) and closes with the one move it would make,
  ranked by cost (critical alerts → stockouts → approvals → low stock). Honest and confident;
  units/AED kept separate.
- ✅ **System prompt gains an "answer like a retail operator" section** (additive, strictly
  subordinate to the grounding/honesty rules): lead with the number + basis, then meaning →
  action → outcome → next step — but only claim impact/action the data supports. `test_ai_rbac`
  + `test_role_experience` (23) still green.
- ✅ **Failure recovery on the role homepage (`/today`) and Insights.** The verdict and
  decisions zones no longer spin an infinite skeleton on error — they offer a retry. The
  approvals and stock zones no longer report a false "all clear" when the fetch actually
  failed, and Insights shows an honest error on a first-load failure instead of "nothing needs
  attention". `tsc --noEmit` + `next build` clean (all 40+ pages).

### Enterprise polish sprints 2–4 — invisible AI, workflow delight, keyboard/a11y ✅ done
Continuation of the polish pass (no new features), inside the AI/Experience vertical.
- ✅ **Sprint 2 — invisible AI.** `GET /api/findings` rows now carry `impact`/`confidence`/
  `expected_outcome`/`evidence_facts` via `decision_center.enrich_finding` — the same pure
  builders `/api/decisions` uses, so Insights and the Decision Center can never disagree
  (+3 pure tests). Insights cards adopt the Decision Center's explainability grammar
  (confidence pill, evidence chips, expected outcome, "why this confidence & impact").
  `/value` gains "Sage's read" — a deterministic one-liner naming the biggest lever
  (dead stock vs stockout risk) with one next-step link. ChatBot welcome bullets became
  one-tap suggested-question chips.
- ✅ **Sprint 3 — workflow delight.** Resolve/dismiss are now undoable (acknowledge() is the
  verified server-side reopen path): Insights flips the card to a "Resolved · Undo" strip
  (auto-refresh pauses while an undo is pending); the Decision Center gets a single-slot
  undo bar for the last dismissal. Action-draft approve/reject (terminal server-side)
  became two-step arm→confirm with honest microcopy; the silent row-open failure now
  toasts. Insights cards exit with a collapse/fade (AnimatePresence).
- ✅ **Sprint 4 — enterprise polish.** The design-system `Tabs` (role=tablist,
  aria-selected, animated indicator) replaced raw filter buttons on Decisions, Insights,
  Action Drafts, and Forecast Lab. Forecast Lab gained a real error state (a failed fetch
  no longer masquerades as "no model metrics yet") + entrance motion. ChatBot: Esc closes,
  `role="log" aria-live="polite"` on the conversation, aria-labels/aria-pressed on all
  icon-only controls. CommandPalette: Gmail-style `g` sequences (g t/d/b/i → Today/
  Decisions/Briefing/Insights, role-filtered, never while typing) + a shortcut footer.
  Insights action buttons stack below content on narrow screens.
- **Verified:** `tsc --noEmit` + `next build` clean; backend owned suites green
  (decision_center 23, ai_rbac+role_experience 23, briefing/action_drafting).

### E0-1 — Automated backups + rehearsed restore ✅ done
Closes the audit's "no automated backup/restore test exists — disqualifying" gap and Risk #8.
- ✅ **Automated backups**: prod `backup` sidecar (both compose files; dev via `--profile backup`) —
  daily `pg_dump -Fc` at `BACKUP_AT_UTC` + on-start dump, each **self-verified**, writing a
  `latest.json` manifest (size/sha256/verified) for monitoring, pruned to `RETENTION_DAYS`.
  `scripts/backup-scheduler.sh` is a dependency-free busybox-`sh` loop (no cron daemon).
- ✅ **Offsite-capable**: `BACKUP_S3_URL` (+ `AWS_*`) offloads to object storage (aws-cli/rclone);
  documented managed-snapshot alternative for Render/RDS. A backup on the DB's own host isn't DR.
- ✅ **Dead-man's-switch**: `BACKUP_HEARTBEAT_URL` pinged only on a **verified** success (E0-2 hook).
- ✅ **Rehearsed restore**: `scripts/drill-restore.sh` — **non-destructive** (restores into a scratch
  DB, never the source), validates **every public table's row count** + a probe checksum, measures
  RTO and fails if over `RTO_BUDGET_SECONDS`. **Runs in CI on every push** (`backup-restore-drill`
  job, self-seeded, exact pg15 tools) — continuous proof, not a one-off.
- ✅ **Docs**: `docs/runbooks/BACKUP_AND_RESTORE.md` (schedule/retention/offsite/monitoring/drill +
  RPO/RTO targets), cross-linked `RESTORE_FROM_BACKUP.md`, DEPLOY.md section, README/CLAUDE.md
  commands; READINESS_CHECKLIST Phase 4 boxes checked; RISK_REGISTER #8 → MITIGATED.
- **Residual (per-deploy ops, not code):** set `BACKUP_S3_URL`/managed snapshots on the live deploy;
  run + log the first quarterly live drill against the real pilot DB.

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
