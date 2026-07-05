# 12-Month Execution Blueprint — Jul 2026 → Jun 2027

**Source of truth for strategy:** the enterprise audit (2026-07-04). This document turns it into
an execution plan. `implementation.md` remains the living tracker; this is the map it executes.

**Prime directive:** one real UAE retailer's real data through the product in 90 days.
Every task below either serves that, or serves the buyer who arrives because of it.

**Operating principles**
1. **Depth over surface.** Zero net-new modules until M4. The audit's verdict: 40 routes, 0 customers.
2. **The loop is the company.** Detect → diagnose → recommend → accept → measure → price-on-outcome.
   Every quarter must deepen the loop, not decorate around it.
3. **Calendar-driven GTM.** DSF (Dec 2026–Jan 2027) and Ramadan 2027 (~Feb 18–Mar 19) are immovable
   marketing deadlines. Ramadan-forecast credibility must ship by **January 2027** or wait a year.
4. **Honesty is the brand.** Keep the `needs: cost` / draft-marked / methodology-column culture. It is
   the moat's foundation.
5. **Solo-founder math.** Effort estimates assume founder full-time; engineer #1 joins ~M4. Anything
   marked 🧑‍🤝‍🧑 assumes the hire exists.

**Legend:** Pri P0 (blocks the milestone) / P1 (needed this quarter) / P2 (opportunistic).
Effort in engineer-days (d) or weeks (w). AC = acceptance criteria. Impact = business impact.

---

## The four proofs (quarterly arc)

| Quarter | Theme | Milestone (investor-legible) |
|---|---|---|
| **Q1 (Jul–Sep 26)** | Proof of **Data** | A real UAE retailer's real data live; `/value` shows their AED number; ops-safe platform |
| **Q2 (Oct–Dec 26)** | Proof of **Value** | First paying customer; briefing + AED-ranked findings driving weekly actions; DSF campaign live |
| **Q3 (Jan–Mar 27)** | Proof of **Repeatability** | 5 paying tenants; published Ramadan forecast accuracy; SSO + security review passable |
| **Q4 (Apr–Jun 27)** | Proof of **Business** | 10–15 paying tenants; outcome-pricing cohort data; seed round on metrics, not story |

---

# QUARTER 1 — Proof of Data (Jul–Sep 2026)

## EPIC E0 — Ops safety net (Month 1, non-negotiable)
*You cannot host a single real tenant without this.*

| ID | Issue | Pri | Effort | Deps | Acceptance criteria | Impact |
|---|---|---|---|---|---|---|
| E0-1 ✅ | Automated Postgres backups (pg_dump cron → object storage) + **one rehearsed restore** | P0 | 2d | — | ✅ Nightly backup verified (prod `backup` sidecar: verify + `latest.json` manifest + prune + offsite via `BACKUP_S3_URL`); ✅ restore drill (`scripts/drill-restore.sh`) restores into a scratch DB + validates row counts/checksum, **run in CI on every push** (`backup-restore-drill`) and manually against the pilot DB (RTO measured, budget-gated); ✅ runbook `docs/runbooks/BACKUP_AND_RESTORE.md`. Residual (per-deploy ops): set offsite target + log the quarterly live drill | Disqualifier removed; pilot-hosting becomes ethical |
| E0-2 | Uptime monitoring + alerting on API/worker health endpoints | P0 | 1d | — | Downtime alert reaches founder phone in <5 min; `/health` covers DB, Redis, worker heartbeat | First outage is known before the customer tells you |
| E0-3 | CI deploy pipeline: push to `main` → staging auto-deploy; tagged release → prod | P0 | 3d | — | Zero-manual-step deploy; rollback = redeploy previous tag; smoke test gates promotion | Velocity + safety for everything below |
| E0-4 | Delete stale prod-compose mounts (`seed_data.sql`, `train.csv`); reconcile prod compose with reality | P0 | 0.5d | — | `docker-compose.production.yml` boots clean on a fresh VM | Removes a known trap before it bites in front of a pilot |
| E0-5 | Reconcile token storage: verify httpOnly-cookie path is the only path; fix CLAUDE.md/docs | P0 | 1d | — | No token in localStorage in any flow; docs match code; XSS-theft test added | Closes the audit's security ambiguity |
| E0-6 | Fix `lib/api.ts` cache user-awareness → TanStack Query keyed by (user, tenant) | P0 | 3d | — | Role-switch in one tab never serves stale privileged data; test proves it | Data-leak bug killed; frontend data layer modernized |
| E0-7 | Per-user + per-API-key rate limits (extend Redis sliding window beyond IP) | P1 | 2d | — | Authenticated abuse throttled per identity; 429 with Retry-After; test in `test_middleware.py` | Bypass-by-IP-rotation closed |
| E0-8 | Demo-tenant auto-reset cron (generator + seeded data confined to tenant 1) | P1 | 1d | E0-3 | Demo resets nightly; no synthetic writes possible on real tenants (guard + test) | Demo can never contaminate a pilot |

## EPIC E1 — Design Partner Program (Months 1–3, the whole point)

| ID | Issue | Pri | Effort | Deps | Acceptance criteria | Impact |
|---|---|---|---|---|---|---|
| E1-1 | Target list: 30 UAE retailers, 5–50 stores (grocery/pharmacy/convenience), with named ops contact | P0 | 3d founder-sales | — | 30 rows: company, store count, POS system used, contact, warm-path | Pipeline exists |
| E1-2 | Design-partner offer: free 6-month license + white-glove onboarding for data access + logo + 2 calls/mo | P0 | 1d | — | One-page offer doc; 3 signed design-partner agreements by end of M3 | The only metric that matters in Q1 |
| E1-3 | **Excel (.xlsx) import** — extend the CSV wizard (UAE reality: it's never CSV) | P0 | 4d | — | .xlsx/.xls upload → same map/validate/commit path; messy-header tolerance; sample files | Halves onboarding friction for every pilot |
| E1-4 | Onboarding concierge runbook: founder imports partner's first export live on a call | P0 | 1d | E1-3 | Documented 45-min script: export → import → `/value` AED number on screen | Time-to-first-value < 1 hour |
| E1-5 | Data-quality report on import (missing days, duplicate SKUs, unit anomalies) | P1 | 3d | E1-3 | Import ends with a quality scorecard; unresolved rows downloadable | Trust: the product admits what it can't see |
| E1-6 | Real-data hardening sprint (reserved capacity for whatever partner data breaks) | P0 | 10d reserve | E1-2 | All partner-data crashes/wrong-numbers fixed within 48h SLA | The audit's #1 risk retired empirically |
| E1-7 | 10 recorded user interviews (store/ops/category managers), written up in `docs/research/` | P0 | ongoing | E1-1 | 10 writeups; each names top-3 pains ranked; roadmap deltas logged | Every §3 persona guess becomes validated or killed |

## EPIC E3a — Intelligence that sells (Months 1–3)

| ID | Issue | Pri | Effort | Deps | Acceptance criteria | Impact |
|---|---|---|---|---|---|---|
| E3-1 ✅ | **Daily executive briefing**: findings + forecast deltas + UAE calendar → email + `/briefing` page | P0 | 5d | — | ✅ `/briefing` in-app screen + `GET /api/briefing` (JSON) + `GET /api/briefing/print` (emailable/printable one-pager). Assembles headline WoW revenue/volume, top findings ("why"), severity-ranked decisions (findings + reorder), an honest win (measure-loop recovery else growth), UAE-calendar + forecast horizon, and AED cost-of-inaction — **all from existing data, no fabrication, tenant+store scoped**. Pure `build_briefing` unit-tested (`test_briefing.py`, 10). **Deferred (ops, per "skip infra" directive): the 07:00 Asia/Dubai scheduled send + unsubscribe** — the `/print` endpoint is the ready email body; wiring the scheduler is a non-blocking ops task | Highest value-per-line-of-code in the audit; the retention hook |
| E3-2 ✅ | **AED-ranked findings inbox**: every finding carries estimated AED impact (reuse `roi.py` derivations); insights sorted by money | P0 | 3d | — | ✅ Shipped as the **AI Decision Center** (`/decisions`, `/api/decisions`): an inbox of decisions (not a dashboard) where every card carries problem, **AED impact** (derived from the finding's own evidence; units where returns carry no price; explicit `basis` always), evidence facts, **explainable deterministic confidence**, recommended action + expected outcome — money-ranked. Approve/dismiss reuse `accept-action`/`resolve` so the measure loop reports whether each approved decision worked (Decided tab). `test_decision_center.py` (13) guards the honesty contract. Verified live | Turns findings from list into P&L instrument |
| E3-3 | **Store health score**: composite (sales trend, stockout days, dead-stock AED, return rate), trendable, format-normalized | P0 | 5d | — | Score 0–100 per store with sub-scores + 8-week trend; small-format stores not auto-penalized (per-format baseline); on dashboard + briefing | The COO's single number; demo centerpiece |
| E3-4 | Fix `laggard_store` rule: benchmark within format/size peer group | P1 | 1d | E3-3 | Rule compares vs peer-group median, not raw revenue | Kills the audit's D-grade benchmarking |
| E3-5 | Rules 6–12: stockout-days streak, dead-stock growth, forecast-miss, price-anomaly (unit_price drift), supplier-late (PO overdue), category share shift, zero-sales SKU | P1 | 6d | — | 7 new rules in `worker/src/rules.js` with tests; each maps to a recommended action + AED estimate where derivable | Diagnostic depth 5→12; loop gets real coverage |
| E3-6 | Per-tenant rule thresholds (config table + settings UI) | P2 | 3d | E3-5 | Tenant admin tunes thresholds; defaults sane; audit-logged | Pilots stop arguing with alerts |

## EPIC E6a — Architecture debt with deadlines (Months 2–3)

| ID | Issue | Pri | Effort | Deps | Acceptance criteria | Impact |
|---|---|---|---|---|---|---|
| E6-1 | **Metrics into SQL views**: all worker-rule math reads Postgres views shared with `routes/kpis.py`; JS computes nothing | P0 | 4d | — | `worker/src/rules.js` contains zero revenue arithmetic; accuracy guards cover the views once, both languages inherit | Two-language drift bomb defused |
| E6-2 | Adopt Alembic; collapse init.sql/migrations/runtime-seeder into migrations-only | P1 | 4d | — | Fresh env = `alembic upgrade head`; drift check in CI; 49 legacy migrations squashed to baseline | Team-ready schema management before hire #1 |
| E6-3 | Partition `sales_stream_raw` by month (native partitioning) | P1 | 2d | E6-2 | Insert/query plans verified; retention policy documented | Ready for real-tenant volumes |
| E6-4 | Statement timeouts on all analytics/report queries (not just Sage) | P1 | 1d | — | No endpoint can hold a connection >10s; test | One bad query can't take the API down |
| E6-5 | Load test: 100 concurrent SSE + Sage + dashboard mix (k6 or Locust) | P1 | 3d | E0-3 | Baseline published in `docs/production/`; breakpoints identified; asyncio side-task impact measured | Evidence replaces guesses before pilot #2 |
| E6-6 | API versioning: freeze `/api/v1/*`; deprecation policy for `public_api` | P2 | 3d | — | All public-API consumers on `/v1`; internal routes exempt; policy doc | External breakage risk capped before developer adoption |

### Q1 exit gate (all must be true)
- ≥1 design partner's real data live; their CFO has seen their `/value` AED number
- Backups restored once for real; deploys are one command; monitoring pages the founder
- Briefing + AED-ranked findings + store health score shipped and in the demo
- 10 user interviews written up
- **Investor artifact:** "Proof of Data" memo — screenshots of real-tenant findings + partner quote

---

# QUARTER 2 — Proof of Value (Oct–Dec 2026)

## EPIC E2 — Integrations wedge (Months 4–6)

| ID | Issue | Pri | Effort | Deps | Acceptance criteria | Impact |
|---|---|---|---|---|---|---|
| E2-1 | **POS connector #1** — pick from partner interviews (likely a Foodics/Loyverse-class cloud POS with API); daily sales + items + stock pull | P0 | 4w 🧑‍🤝‍🧑 | E1-7 (choice), hire | OAuth connect flow; nightly sync; same validation path as imports; one partner live on it | Answers "which of my systems does it connect to?" — the audit's kill-shot question |
| E2-2 | Scheduled recurring imports (SFTP drop + email-inbox ingestion) | P1 | 5d | E1-3 | Tenant configures a source; imports run unattended; failures notify | Retailers without APIs (most) get automation anyway |
| E2-3 | Cost price + margin data model (items.unit_cost_aed, effective-dated) + margin in KPIs/ROI/findings | P0 | 5d | — | GMROI/cash-at-cost stop returning `needs: cost` for tenants who load costs; margin never shown where cost absent (guard) | Unlocks profit-leakage class of intelligence; CFO conversations change |
| E2-4 | Import rollback (row-tagged, per-job undo) — the deferred item | P2 | 4d | E1-3 | Any committed import reversible in one click within 30 days; audit-logged | Pilot onboarding fear removed |
| E2-5 | Basket/transaction-grain schema design (spec only, tables created, unfilled) | P1 | 3d | E2-1 | ERD + migration for `transactions`/`transaction_lines`; POS connector writes to it where source supports | Foundation for shrink/promo/customer intel without blocking on it |

## EPIC E4 — UI/UX to premium (Months 4–6)

| ID | Issue | Pri | Effort | Deps | Acceptance criteria | Impact |
|---|---|---|---|---|---|---|
| E4-1 | Finish Track 6 across all remaining ~18 routes | P0 | 2w | — | Every route uses StatCard/ChartFrame/motion primitives; visual QA checklist per route in `docs/product/FRONTEND_QA.md` | Inconsistency — the #1 trust killer — eliminated |
| E4-2 | Restore dark mode (CSS-variable architecture kept dark-ready) | P1 | 4d | E4-1 | Full dark theme, user toggle, charts/series adjusted; no per-component forks | Premium-SaaS table stakes back |
| E4-3 | **Mobile store-manager view**: `/today` — exceptions, tasks, health score only | P0 | 1.5w | E3-3 | Loads <2s on mid-range Android; PWA-installable; store manager persona demo uses a phone | The persona most likely to love the product can finally use it |
| E4-4 | Full Arabic on 5 core screens (dashboard, insights, briefing, value, login) | P1 | 1w + translator | — | Native-speaker-reviewed AR strings; RTL visual QA; language toggle persisted | Half-Arabic embarrassment fixed where buyers look |
| E4-5 | Kill jspdf/html2canvas; all exports via server-rendered printable HTML | P1 | 3d | — | No client-side PDF code remains; every report branded, crisp, methodology-carrying | Export quality worthy of a CFO's inbox |
| E4-6 | Executive mode: dashboard density toggle (1 number, 1 trend, 1 anomaly per view; drill-down on demand) | P2 | 5d | E4-1 | Exec toggle persists per user; analytics wall demoted to drill-down | The CEO screen the audit said was missing |
| E4-7 | Ramadan/DSF/Eid shading annotations on every time-axis chart (`lib/chart.ts`) | P1 | 2d | — | Calendar bands render automatically from `uae_intelligence` calendar | Visible, cheap, regional differentiation in every screenshot |
| E4-8 | Accessibility CI: axe checks on core routes; focus management on modals | P2 | 3d | E4-1 | CI fails on new critical a11y violations; keyboard-only demo passes | Enterprise checklist item; decency |

## EPIC E8a — First revenue (Months 4–6)

| ID | Issue | Pri | Effort | Deps | Acceptance criteria | Impact |
|---|---|---|---|---|---|---|
| E8-1 | Convert design partner #1 to paid (bank transfer via existing manual billing) | P0 | founder-sales | Q1 gate | Signed order form; first VAT invoice issued through the Phase-4 billing layer | **First dirham.** Everything reprices after this |
| E8-2 | Payment gateway (Telr or PayTabs) wired to existing provider abstraction | P1 | 1w | E8-1 | Card payment settles a real invoice; webhook reconciles; manual path stays | Self-serve path opens |
| E8-3 | Usage quotas ON for free tier (`ENFORCE_USAGE_QUOTAS=true` for plan=free) | P1 | 2d | — | Free tier hits soft limits with upgrade CTA; paying tenants unaffected; tests | Free tier becomes funnel, not charity |
| E8-4 | Invoice PDF finish + dunning reminders (7/14/30-day, email stub → real SMTP) | P1 | 4d | E8-1 | Overdue invoices chase themselves; operator sees AR aging on `/admin/tenants` | Founder stops doing collections by memory |
| E8-5 | Outcome-pricing hardening: attribution dispute flow (operator + customer co-confirm; disputed = excluded) | P2 | 4d | E8-1 | Realization has `disputed` state; statement excludes disputed; renewal report shows agreed-only savings | The audit's renewal-risk pre-empted before the first renewal |

## EPIC E9a — GTM engine ignition (Months 4–6)

| ID | Issue | Pri | Effort | Deps | Acceptance criteria | Impact |
|---|---|---|---|---|---|---|
| E9-1 | Name decision + UAE/KSA trademark search + domain + bilingual landing page | P0 | 1w + fees | — | Shortlist (Wafra/Meridian/Noor/Verdict/Suqara) → decision; brand.ts + PRODUCT_NAME flipped once | Stop building equity in a placeholder |
| E9-2 | **Free ROI-report lead magnet**: public "upload CSV → dead-stock AED report" (sandboxed, rate-limited, email-gated) | P0 | 1w | E1-3, E0-7 | Anonymous upload → branded report emailed; data purged after 7 days (stated); conversion tracked | Self-serve pipeline; the audit's growth engine |
| E9-3 | Hub71 / in5 / DTEC applications + ADGM-vs-mainland incorporation decision | P0 | founder | E9-1 | Incorporated; ≥1 accelerator application submitted | Legal existence + free money + B2G door-openers |
| E9-4 | Case study #1 from design partner (AED found, actions taken, outcomes measured) | P0 | 3d | E8-1 | 2-page bilingual PDF + web page; partner-approved quotes | The only sales collateral that matters |
| E9-5 | DSF campaign (Dec): "DSF readiness check" — free report angle timed to festival stocking | P1 | 3d | E9-2 | Campaign live by Nov 15; ≥50 report runs during DSF window | Calendar-surfing demand capture |
| E9-6 | Founder content: 2 LinkedIn posts/week on the measure loop + UAE retail data honesty | P1 | ongoing | — | 26 posts by end of Q2; pipeline attribution tracked | Distribution is a feature; solo founders sell trust |

### Q2 exit gate
- ≥1 paying tenant (bank transfer fine); ≥3 design partners live
- POS connector #1 syncing nightly for ≥1 tenant; margin model live
- UI consistent across all routes; mobile `/today` shipped; brand decided
- **Investor artifact:** "Proof of Value" memo — first revenue, case study, activation funnel numbers

---

# QUARTER 3 — Proof of Repeatability (Jan–Mar 2027)

*Ramadan 2027: ~Feb 18–Mar 19. The quarter is built around it.*

## EPIC E7 — AI that earns the name (Months 7–9)

| ID | Issue | Pri | Effort | Deps | Acceptance criteria | Impact |
|---|---|---|---|---|---|---|
| E7-1 | **Forecasting v2**: UAE calendar features (Ramadan/Eid/DSF from `uae_intelligence`) + weather (free API) into LightGBM; backtest on partner data | P0 | 2w | E1-6 | MAPE/WAPE vs seasonal-naive published per tenant in Forecast Lab; Ramadan-window accuracy separately reported | The marketing weapon: "Ramadan-accurate, and we show our error rate" |
| E7-2 | Publish Ramadan forecast methodology + accuracy (public doc, by **Jan 31 2027**) | P0 | 3d | E7-1 | Public page with method, features, honest error bars on real (anonymized) data | Trust content no regional competitor dares publish |
| E7-3 | Hosted-LLM Sage tier (Claude Haiku-class) behind flag; local Ollama = privacy/B2G tier | P0 | 1w | revenue | Grounded-hit rate ≥85% on the sage3 eval suite (vs current 3B floor); per-tenant tier flag; cost metered per query | Sage demos stop stuttering exactly when it matters |
| E7-4 | Root-cause decomposition: finding → category/SKU/day contribution breakdown (pure SQL, no LLM) | P0 | 1w | E6-1 | Every revenue_drop/category_slump finding shows top-5 contributors with AED deltas; Sage answers "why" from it | The "why" question — vision pillar #2 — actually answered |
| E7-5 | **Promotion uplift measurement**: promo vs matched-baseline lift, measured by the outcome loop | P1 | 1.5w | E2-3 | Every promotion gets an uplift report (lift %, AED, cannibalization flag vs category peers); honest "insufficient baseline" state | Extends the moat sideways; category managers' #1 ask |
| E7-6 | Reorder-point/safety-stock suggestions on forecasts (service-level input, human-approved PO draft) | P1 | 1.5w | E7-1, E2-3 | Suggested order qty per SKU-store with formula shown; flows into existing procurement drafts + approval_rules | From "detect stockout" to "prevent stockout" |
| E7-7 | Sage "explain this chart" deep-link from every ChartFrame | P2 | 3d | E7-3 | Any chart → one click → grounded Sage explanation with SQL evidence | AI woven into the UI, not a chatbot bolt-on |
| E7-8 | Findings → task assignment (assign to store user, due date, done-state feeds measure loop) | P1 | 1w | E4-3 | Ops assigns finding → store manager sees it on `/today` → completion correlates with outcome | Closes loop between HQ decision and floor action |

## EPIC E5 — Enterprise door keys (Months 7–9)

| ID | Issue | Pri | Effort | Deps | Acceptance criteria | Impact |
|---|---|---|---|---|---|---|
| E5-1 | SSO: OIDC + SAML (WorkOS if budget, else self-built OIDC first) | P0 | 2w 🧑‍🤝‍🧑 | hire | Azure AD login works end-to-end for a pilot tenant; JIT user provisioning | No >50-seat deal closes without it |
| E5-2 | Enforce MFA (TOTP exists — mandatory for admin/super_admin) | P0 | 2d | — | Admin roles cannot skip TOTP enrollment; recovery codes; audit events | Cheap, visible security win |
| E5-3 | UAE-region hosting: production on AWS me-central-1 or Azure UAE North | P0 | 1w | E0-3 | Prod + backups + monitoring in-country; residency statement on `/trust` | B2G hard requirement; enterprise soft requirement — answered |
| E5-4 | SOC2 Type I evidence collection start (Vanta/Drata-class, or manual register) | P1 | ongoing | E5-3 | Controls mapped; evidence auto-collecting; Type I audit scheduled for Q4 | 6–9-month clock started before enterprise asks |
| E5-5 | Dependency scanning + SBOM + secrets scanning in CI | P1 | 2d | E0-3 | CI fails on critical CVEs and committed secrets; SBOM artifact per release | Hygiene gate before team growth |
| E5-6 | JWT → RS256; secrets to a managed vault; rotation runbook | P1 | 4d | E5-3 | Worker/public-API verify without signing key; documented rotation executed once | Key-compromise blast radius shrunk |
| E5-7 | Security questionnaire auto-answer pack (from `/trust` + audit log + this program) | P2 | 2d | E5-1..5-4 | CAIQ-lite doc; first real questionnaire answered in <1 day | Sales cycle time cut |
| E5-8 | Pen test (budget community/crowdsourced tier) + fixes | P1 | 1w + fees | E5-3 | Report on file; criticals fixed; summary on `/trust` | Evidence, not claims |

## EPIC E9b — Repeatable sales (Months 7–9)

| ID | Issue | Pri | Effort | Deps | AC | Impact |
|---|---|---|---|---|---|---|
| E9-7 | Self-serve trial: signup → sandbox with sample data → import own → paywall | P0 | 1.5w | E8-2, E8-3 | Stranger reaches their own AED number with zero founder touch; funnel instrumented | Founder stops being the onboarding bottleneck |
| E9-8 | Ramadan campaign (Jan): "Is your Ramadan order right?" — forecast-accuracy angle | P0 | 3d | E7-2 | Campaign live Jan 15; ≥10 qualified conversations from it | The year's biggest demand moment captured |
| E9-9 | Pricing page v2: 3 tiers + outcome-pricing explainer + ROI calculator embedded | P1 | 3d | E9-2 | Live AED pricing; outcome model explained in one scroll | Buyers self-qualify |
| E9-10 | Referral loop on free ROI report ("send your supplier/peer their report") | P2 | 3d | E9-2 | Referral source tracked; ≥10% of report runs from referrals | Organic growth mechanism |

### Q3 exit gate
- 5 paying tenants; ≥2 arrived without founder outbound
- Ramadan accuracy published before the season; ≥1 tenant reorders based on it
- SSO + MFA + UAE hosting + pen test done — mid-market security review passable
- **Investor artifact:** "Proof of Repeatability" memo — cohort funnel, NRR early signal, accuracy publication

---

# QUARTER 4 — Proof of Business (Apr–Jun 2027)

## EPIC E10 — Autonomy L2 + enterprise/B2G track (Months 10–12)

| ID | Issue | Pri | Effort | Deps | AC | Impact |
|---|---|---|---|---|---|---|
| E10-1 | **Autonomy L2 (scoped)**: auto-send approved supplier emails; auto-create POs under `approval_rules` threshold; measure-loop rollback trigger | P0 | 2w | E7-6, E5-* | Execution adapter with per-action-type kill switch; every auto-action audited + measured; one tenant opted in, net-positive outcomes over 30 days | "Agentic Retail OS" becomes demonstrably true, safely |
| E10-2 | Isolation tiers in provisioning: shared-RLS (default) / schema-per-tenant / dedicated instance | P1 | 2w 🧑‍🤝‍🧑 | E6-2 | Enterprise tenant provisioned on dedicated schema in <1 day; price tier attached | Enterprise/B2G objection answered |
| E10-3 | White-label theming (logo, palette, domain) for B2G/reseller | P2 | 1w | E4-1 | One resold/white-labeled deployment live or contracted | Reseller channel opens |
| E10-4 | E-invoicing accreditation path: real UAE-FTA gateway behind the existing provider abstraction | P1 | 2w + external | E8-2 | Sandbox clearance passing; accreditation application in flight | Regulatory-wave positioning cashes in as mandates phase in |
| E10-5 | B2G pilot pursuit (economic dept / free-zone authority price-monitoring use case) | P2 | founder | E5-3, E10-2 | 1 government pilot conversation past security review | Optionality proven, not bet on |
| E10-6 | SOC2 Type I report delivered | P1 | external | E5-4 | Report on file; badge on `/trust` | Enterprise paper complete |
| E10-7 | Read replica + analytics query routing | P2 | 1w | E5-3 | Dashboards read from replica; write path unaffected; failover tested | Headroom for 10× tenants |
| E10-8 | Waste/expiry intelligence v1 (batch/expiry model + expiring-stock findings) — only if ≥2 grocery pilots demand it | P2 | 2w | E2-5, demand | Expiry-risk finding with AED at stake; markdown suggestion draft | Opens the fresh-section moat when data supports it |

## EPIC E11 — Company & raise (continuous, peaks Q4)

| ID | Issue | Pri | When | AC | Impact |
|---|---|---|---|---|---|
| E11-1 | Pre-seed close (AED 1.8–5.5M / $0.5–1.5M) on Q1–Q2 proofs | P0 | Q2–Q3 | Term sheet on "Proof of Value" metrics; 18-month runway | Funds hires E11-2/3 |
| E11-2 | **Hire #1 (M4): founding full-stack engineer**, Python-strong, Dubai-based or GCC-remote | P0 | M4 | Owns E2-1 (POS connector) + E5-1 (SSO) within 60 days; bus factor 2 | The audit's #2 risk halved |
| E11-3 | Hire #2 (M8): founding GTM/CS (Arabic-speaking, retail network) | P0 | M8 | Owns pipeline + onboarding; founder exits concierge role | Sales repeatability |
| E11-4 | Advisor: retired UAE retail ops executive (equity, 2 hrs/mo) | P1 | Q1–Q2 | Signed; opens ≥3 doors; reviews rule library quarterly | Domain credibility + distribution |
| E11-5 | Contract designer (M4–M6, part-time) for E4 polish + brand | P1 | M4 | Design system documented; brand shipped | Premium look without a full-time hire |
| E11-6 | Seed-round dataset: outcome-pricing cohort report (savings confirmed vs fees, NRR, funnel) | P0 | M11–12 | Auto-generated from `value_realizations` + billing — the product produces its own fundraising evidence | The raise closes on data only this product can have |

### Q4 exit gate / 12-month scoreboard
- 10–15 paying tenants; MRR AED 40–120K; ≥1 enterprise/white-label contract
- Autonomy L2 live with measured net-positive outcomes at ≥1 tenant
- SOC2 Type I + UAE residency + pen test = enterprise paper done
- Team of 3; seed conversations running on cohort data
- **Investor artifact:** seed deck where every claim links to a measured outcome in the product

---

## Pricing evolution

| Phase | Model |
|---|---|
| Now → M3 | Design partners free; manual invoicing rails proven |
| M4–M6 | **Founder pricing**: Starter AED 1,500/mo (≤5 stores), Growth AED 6,000/mo (≤25 stores, API+Sage); annual = 2 months free; bank transfer normal |
| M7–M9 | Self-serve card payments; free tier = 1 store + ROI report (quota-enforced); outcome component offered on Growth+ (base + ≤30% share of co-confirmed savings, guarantee waiver) |
| M10–M12 | Enterprise: custom + isolation tier + SSO + SLA; B2G: dedicated instance, scope-priced; first renewals defended with agreed-savings statements (E8-5) |

## GTM strategy (one paragraph, per quarter)
**Q1:** founder-led design-partner hunting via warm UAE retail networks; the product's own ROI report is the pitch. **Q2:** first revenue + case study + brand + free-report lead magnet; DSF timing. **Q3:** Ramadan accuracy publication as the trust artifact; self-serve trial; founder content compounding. **Q4:** repeatable mid-market motion run by hire #2; enterprise/B2G pursued opportunistically on the paper earned in Q3, never as the main bet.

## What we deliberately do NOT do this year
Kubernetes; more federation adapters; voice; marketplace; KSA expansion (design for it, don't enter); customer-behavior/loyalty analytics (no data grain until POS connectors mature); any new module not traceable to a design-partner interview.

## Kill / pivot criteria (honesty applies to the plan too)
- **M3:** no design partner with real data → stop building entirely; 100% founder-sales until one exists.
- **M6:** no one pays anything → the wedge is wrong; re-interview and re-segment (pharmacy? F&B?) before writing more code.
- **M9:** paying tenants don't act on findings weekly (activation <40%) → the loop isn't landing; halt AI roadmap, fix core workflow.
