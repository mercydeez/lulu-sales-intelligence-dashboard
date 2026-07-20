# Master Implementation Plan — C-Level

**Date:** 20 July 2026
**Branch:** `prototype-evolution-accuracy-bullmq` @ `80739b9`
**Status:** PLAN ONLY. Nothing in this document has been built. Implementation is gated on explicit owner approval.
**Decisions 1–4 ruled 20 July 2026 — see §7.** Horizons 1–2 are unblocked and ready to begin on approval; Horizon 3 awaits questions 5–7.

This document is written from seven seats — CEO, CFO, COO, CMO, CTO, Senior Frontend, Senior Backend — because the decisions that matter now are not engineering decisions with a business wrapper. They are business decisions that happen to require engineering. Where a claim comes from the codebase it is stated as verified. Where it comes from outside research it is cited. Where it is my judgement it is labelled as such.

---

## 0. The thesis in one paragraph

We have built a genuinely differentiated decisioning engine — an EIV optimizer that multiplies *uplift*, not churn probability, and refuses to spend on customers who would have bought anyway. That is the correct and uncommon design, and it is the whole moat. Everything else in the product (57 pages, 51 route modules, 76 migrations) is competent retail analytics that a dozen vendors also sell. **The next phase should not add surface area. It should make the one differentiated thing provable, sellable, and defensible** — prove incrementality with a real holdout readout, meter it so it can be charged for, and harden the tenancy and compliance posture enough that a Gulf retailer's procurement team can actually sign. Anything that does not serve those three outcomes is a distraction we cannot afford at this stage.

---

## 1. Where we actually are — verified inventory

Counted from the working tree, not from memory:

| Surface | Count | Note |
|---|---|---|
| Flywheel backend service modules | 21 | `backend/app/services/flywheel/` |
| Flywheel frontend pages | 8 | `frontend/src/app/flywheel/` |
| Total frontend pages | 57 | whole product |
| Backend route modules | 51 | |
| Flywheel HTTP endpoints | 36 | `routes/flywheel.py` |
| Backend test files | 120 | 180 tests specific to Flywheel |
| Migrations | 76 | latest `076_krishna_flywheel_hardening.sql` |

**What genuinely works today.** The demo stack serves `http://localhost:3000/flywheel` with 300 seeded customers and a live campaign; every API call returns 200. The decisioning path is real: churn scoring → uplift → EIV ranking → margin floor → ATP stock check → budget reservation → approval chain → activation → redemption with a hard per-campaign cap enforced *inside* the money transaction. Tax is handled net-of-VAT. Breakage and pro-rata returns claw-back post compensating ledger entries. Treatment/control assignment uses BLAKE2b so it is stable across processes. `measurement.measure()` computes uplift by segment with explicit validity warnings. Postgres enforces `reserved_aed + spent_aed <= allocated_aed` and `consumed_units <= allocated_units` as table constraints, not application politeness.

**What is honestly not there.**

1. **No production incrementality readout loop.** `measure()` exists and is correct, but nothing schedules it, nothing surfaces the result as a business number, and no decision is currently changed by its output. We can compute lift; we do not yet *learn* from it.
2. **The models are not distinguishable from noise at current data volume.** Three training runs produced three different winners (GRU 0.8961 → FT-Transformer 0.9197 → LightGBM), and Qini swung from +1.13 to −3.80. At n=300 with roughly 16 positives in the test split that is expected. **This is the single largest credibility risk in the product** and must be either fixed with data volume or explicitly reframed as "deterministic rule tier, ML in shadow mode."
3. **No metering on the Flywheel module.** `services/billing.py` has invoices, plans and line computation, but zero Flywheel hooks. We cannot currently charge for the thing that is worth charging for.
4. **RLS posture is undecided.** `config.py:641` warns that `USE_RLS_ROLE` must be true in production and that `ALLOW_INSECURE_NO_RLS=true` is an explicit risk acceptance. That decision has not been made. It is a hard blocker for any real multi-tenant sale.
5. **All customer data is synthetic.** `customers` rows come from migration 074's seeder. There is no identity graph, no consent ledger tied to a real person, no POS join. The engine is correct; it has never met a real shopper.
6. **No background worker.** No Celery/arq/BullMQ despite the branch name. Everything long-running is an asyncio task in the app lifespan, which does not survive a redeploy mid-job and cannot be scaled independently.
7. **Test shape gap.** 180 green Flywheel unit tests and a clean `tsc --noEmit`, yet the module failed on the *first live call* because the unit tests exercised pure functions and never executed SQL. That gap is now partially closed but the lesson is structural, not incidental.

---

## 2. What the market evidence says

**The category is real and priced high.** Customer data / retention platforms sit at roughly $4–12B in 2026 growing ~20–33% CAGR. Incumbent pricing sets our ceiling and our wedge: [Braze](https://www.braze.com) lands $30K–250K/yr with entry around $50K; [Klaviyo](https://www.klaviyo.com) runs $24K–60K/yr at $50M merchant revenue; Bloomreach Engagement is $48K–200K/yr, and full Commerce Cloud $150K–500K+. The segmentation is by merchant size — Klaviyo under ~$30M revenue, Braze over ~$100M. **A GCC grocery chain sits squarely in the gap, and none of the three optimize for incremental margin under a stock constraint.**

**The regional market is growing faster than global.** UAE loyalty programmes are expected to expand ~16.1% to ~$490.8M in 2025 and reach [$592.4M by 2030](https://www.globenewswire.com/news-release/2026/02/06/3233691/0/en/united-arab-emirates-loyalty-business-report-2026-a-592-4-million-market-by-2030-majid-al-futtaim-share-emirates-skywards-adnoc-distribution-and-e-smiles-compete-with-careem-and-no.html), with regional growth ~13.8% CAGR through 2029 per [Arabian Business](https://www.arabianbusiness.com/abnews/ramadan-boosts-loyalty-programme-adoption-across-gcc-as-market-growth-accelerates-report). GCC digital ad spend hits $12.4B in 2026 at 19% YoY — roughly double the global rate ([23HubLab](https://23hublab.com/the-state-of-digital-growth-in-the-gcc-2026-edition/)). Coalition programmes (Majid Al Futtaim SHARE, ADNOC, e& Smiles) anchor the market, which means **multi-party attribution is table stakes here in a way it is not in the US.**

**There is a much larger adjacent pool than retention budget.** Retail media took $128B of advertiser spend in 2026 at [70–90% onsite margins versus 3–5% on grocery sales](https://www.moartgrp.com/blog/retail_media_highest_margin_business_in_retail), and trade promotion runs $200B+/yr with [60–72% of promotions failing to break even](https://theretailexec.com/retail-operations/retail-media-networks/). **Our optimizer already computes exactly the number a trade-promotion buyer cannot get: incremental margin per AED spent.** This is the highest-value strategic option on the table and it is not currently in the product.

**Pricing has moved.** Hybrid (small platform fee + consumption/outcome layer) is now dominant: 43% of SaaS companies use hybrid, projected 61% by end-2026, and hybrid firms report [38% higher revenue growth and 38% higher NRR](https://www.getmonetizely.com/blogs/the-2026-guide-to-saas-ai-and-agentic-pricing-models). But pure outcome pricing only works where agent accuracy is production-grade — which, per §1.2, ours is not yet.

**Compliance is a hard gate, twice over.** UAE PDPL (Federal Decree-Law No. 45 of 2021) is fully enforced; DPIA is **mandatory for AI/automated profiling** and must be audit-ready in 2026, with 72-hour breach notification, cross-border transfer restrictions, a data-subject right to object to automated profiling, and penalties to AED 5M. Separately, [SOC 2 Type II is routinely blocking vendor onboarding at 200+ employee companies](https://soc2auditors.org/insights/soc-2-compliance-for-startups/); Type I lands in 2–4 months, Type II needs 9–10 months minimum because of the 6-month observation window. **The observation window is the long pole — it must start early or it gates every enterprise deal by a full year.**

---

## 3. The seven lenses

### CEO — what business are we in?

We are not in the dashboard business. Fifty-seven pages of analytics is a commodity; the buyer already has Power BI. We are in the business of **deciding where the next marketing dirham goes and proving it was worth it.** That reframing has three consequences: the Flywheel becomes the product and the rest becomes context; the buyer moves from IT to the CMO/Commercial Director who owns the promo budget; and the sale becomes a payback argument, not a feature comparison.

The strategic fork is whether we are a **retention tool** (competing with Braze/Klaviyo on a crowded field) or a **trade-promotion optimizer** (competing with nobody, funded by supplier money, sitting on a 70–90% margin pool). My recommendation is retention as the wedge and trade promotion as the expansion — the engine is the same, only the funding source changes.

### CFO — does the money story hold?

Three things concern me.

**The margin number was wrong until recently and that matters.** We reported 30.00% where the true net-of-VAT margin was 26.47% — a 3.53-point overstatement on *every single decision*. That is fixed. But it tells me the finance layer needs an independent reconciliation, not just a unit test, because a systematic 3.5-point error is invisible in aggregate and fatal in an audit.

**We cannot currently charge for the differentiated thing.** Billing exists; Flywheel metering does not. Until a redemption or a decision emits a billable event, the module is a cost centre.

**The pricing model should be hybrid, not outcome.** Given model instability, promising "you pay a share of incremental margin" is a commitment we cannot yet measure reliably enough to invoice against. The defensible structure is a platform fee (predictable, covers infrastructure and support) plus a metered decisioning layer priced on *decisions served* or *customers scored* — a metric the buyer already tracks and we can count exactly. Move to outcome-based only after the holdout readout has run clean for two consecutive quarters. Anchor the platform fee below Braze's ~$50K entry and above Klaviyo's mid-market band; the GCC gap is the position.

The number I want on the first slide of every deal is **incremental gross margin per AED of promo spend, net of VAT, measured against a held-out control.** We can compute it. We are not yet showing it.

### COO — can we actually run this?

No, not at scale, for one structural reason: **there is no worker tier.** Every long-running job — scoring, campaign activation, measurement, model training — is an asyncio task inside the API process. That means a redeploy mid-job loses the job, a slow job competes with request latency, and we cannot scale scoring independently of traffic. This is the highest-priority infrastructure item and it is not glamorous.

Second: the nightly demo reset and the generator are correct but they are *demo* machinery. A real tenant needs an ingestion path (POS/loyalty export → staging → identity resolution → feature store) that does not exist. That is the difference between a demo and a deployment, and it is weeks not days.

Third: runbooks exist for backup/restore and there is a rehearsed restore drill in CI. Good. There is no runbook for "the model started recommending nonsense," which is the failure mode most likely to actually occur.

### CMO — will a marketer trust it and use it?

The inverted-U persuadability design (`4p(1-p)`) is exactly right and is the thing to sell: *we do not waste budget on the already-loyal or the already-gone.* Most marketers have never seen that framed explicitly and it lands.

But three adoption blockers stand out. **Frequency capping and suppression exist in the data model but are not visible in the UI** — a marketer will not trust a system whose contact governance they cannot see. **There is no "why this customer" explanation surface** beyond the EIV waterfall; the waterfall shows the math but not the story. And **the control group needs to be a first-class, celebrated object**, not an implementation detail — the holdout is the proof of value, so it should have its own screen and its own narrative.

Regionally: coalition programmes dominate the GCC, and Ramadan is the demand spike that reshapes the whole year. Neither seasonality nor coalition attribution is modelled. For a Gulf retailer that is not a nice-to-have.

### CTO — what breaks first?

**The models.** Three runs, three winners, Qini swinging ±5 — that is not model selection, that is sampling noise wearing a lab coat. At n=300 with ~16 test positives no metric is distinguishable from chance. There are exactly two honest responses: get materially more data (10K+ customers with real outcome windows) or **ship the deterministic rule tier as the production path and run ML in shadow mode**, promoting it only when a pre-registered holdout beats rules with a confidence interval that excludes zero. I strongly recommend the second — it is shippable now, it is defensible in a technical due diligence, and it converts the instability from a hidden liability into a documented governance control.

**The tenancy posture.** `USE_RLS_ROLE` must be resolved before any second tenant exists. App-layer scoping plus FORCE RLS is the design; running with `ALLOW_INSECURE_NO_RLS=true` in production means a single missing `WHERE tenant_id` is a cross-tenant data breach. There is no middle position on this.

**The test shape.** 180 green tests and a first-live-call failure is a permanent lesson: pure-function tests do not test SQL. Every Flywheel service needs at least one test that executes against a real Postgres with RLS on, as the tenant role, on a freshly migrated database. That is the only test that would have caught the bug we shipped.

### Senior Frontend — what does the interface owe the user?

Eight Flywheel pages exist and render. The LoopRing signature element and the EIV waterfall are good. What is missing is not polish, it is **epistemic honesty in the UI**: nothing on screen tells the user how confident the system is. A churn score of 0.71 and a churn score of 0.71 with a 95% interval of [0.31, 0.94] should not look identical, and right now they do. Confidence intervals, sample-size warnings from `_validity_warnings`, and a visible "this is synthetic data" state are UI work with disproportionate trust payoff.

Second: the three-layer nav registration (`config/nav.tsx`, `services/role_experience.py`, `lib/nav/registry.ts`) is a discoverability trap we have already fallen into once. Any new surface must register in all three or it is invisible. That should be a lint rule, not tribal knowledge.

Third: no dedicated mobile posture for a store manager who lives on a phone in an aisle. The approval flow in particular is a phone workflow.

### Senior Backend — what is the engineering debt?

In priority order: (1) no worker tier; (2) no integration tests against live SQL for most services; (3) `measure()` is not scheduled and its output is not persisted as a business fact; (4) no idempotency on the outbox relay's downstream delivery, only on the write; (5) the ML training path writes model artifacts with no registry, no versioning against a data snapshot, and no rollback; (6) no OpenTelemetry traces — `services/metrics.py` exists but a decision cannot be traced end-to-end from request to redemption.

None of these are exotic. All of them are the difference between a system that demos and a system that runs.

---

## 4. The plan — four horizons, each with a gate

Each horizon ends in a **gate**: a check that must pass before the next begins. If a gate fails we stop and fix rather than accumulate.

### Horizon 1 — Make it provable (highest priority)

The goal is a single defensible number on a screen.

- Schedule `measure()` as a recurring job and persist each readout as an immutable business fact with the campaign, window, treatment/control sizes, and validity warnings attached.
- Build the **Incrementality** page: incremental gross margin per AED, net of VAT, against the held-out control, with confidence intervals and an explicit "not yet significant" state that is *not* a failure state.
- Promote the control group to a first-class object with its own screen — who is held out, why, and what it proved.
- Freeze ML to **shadow mode**; make the deterministic rule tier the production decision path. Document this as a governance control, not an apology. Log shadow predictions alongside rule decisions so the promotion decision has evidence when the data arrives.
- Surface confidence in the UI everywhere a probability is shown.

**Gate 1:** a campaign runs end-to-end and produces a readout showing measured incremental margin with a stated confidence interval, and the number reconciles against the ledger to the fillis.

### Horizon 2 — Make it operable

- Introduce a real worker tier. Scoring, activation, measurement and training move out of the API process.
- Integration test suite that runs against live Postgres with FORCE RLS enabled, as the tenant role, on a freshly migrated database — at minimum one per Flywheel service.
- **Decide the RLS posture** and enforce it. My recommendation: `USE_RLS_ROLE=true` mandatory in production, `ALLOW_INSECURE_NO_RLS` removed from the production code path entirely rather than left as a settable escape hatch.
- OpenTelemetry tracing so a single decision is traceable from HTTP request through optimizer, budget reservation, approval, activation, and redemption.
- Model registry: artifacts versioned against a data snapshot hash, with a rollback path and a documented promotion criterion.
- Runbook for model misbehaviour.

**Gate 2:** kill the API process mid-campaign-activation; the campaign completes correctly. Cross-tenant query attempts fail at the database, not the application.

### Horizon 3 — Make it sellable

- Flywheel metering wired into `services/billing.py`: emit billable events on decisions served and customers scored.
- Hybrid pricing implemented — platform fee plus metered decisioning layer, with usage visible to the tenant before it is invoiced.
- PDPL compliance pack: DPIA for automated profiling (mandatory, and we profile), consent ledger tied to identity, data-subject objection handling with a real suppression path, 72-hour breach procedure, cross-border transfer position documented.
- **Start the SOC 2 Type II observation window immediately** — it is 6 months of elapsed time we cannot compress, and every month of delay is a month added to the first enterprise deal. Type I in parallel for active cycles.
- Real ingestion path: POS/loyalty export → staging → identity resolution → feature store, replacing the synthetic seeder for at least one pilot tenant.

**Gate 3:** a pilot tenant's real data flows in, produces decisions, produces a metered invoice, and a DPIA exists that an auditor would accept.

### Horizon 4 — Expand the wedge

Only after Gates 1–3.

- **Supplier-funded trade promotion.** The optimizer already produces incremental margin per AED; a supplier will pay for that number. This is the largest revenue option available and it reuses the engine wholesale.
- Coalition/multi-party attribution — table stakes for the GCC given SHARE/ADNOC/e& Smiles dominance.
- Ramadan and regional seasonality as a first-class demand factor.
- Cannibalization modelling (a promotion that moves volume between own SKUs is not incremental).
- Perishables and shelf-life as an optimizer constraint — for a grocer, markdown timing on short-dated stock may be worth more than retention.
- Only at this point: revisit outcome-based pricing, backed by two clean quarters of holdout readouts.

---

## 5. What I recommend we do NOT do

- **Do not add pages** — with one ruled exception. Fifty-seven is already more than any single user navigates, and new surface dilutes the one thing that differentiates us. The parallel-positioning ruling (§7, decision 3) necessarily creates a supplier-facing surface in Track B; that is the exception, and it should be the *only* one. Every other page request in Horizons 1–3 gets refused.
- **Do not promise outcome-based pricing yet.** We cannot measure reliably enough to invoice against it, and getting it wrong once destroys the trust the whole product runs on.
- **Do not chase model sophistication before data volume.** A better architecture on 300 customers is a better architecture on noise. FT-Transformer versus GRU is not the bottleneck; n is.
- **Do not ship a second tenant before RLS is resolved.** This is the one item where the downside is unbounded.
- **Do not build the agent architecture yet.** It is fashionable and it is not what makes this product work.

---

## 6. Risk register

| Risk | Severity | Current state | Mitigation |
|---|---|---|---|
| Model metrics indistinguishable from noise | **Critical** | **Ruled** — shadow mode | Rule tier in production; pre-registered promotion criterion. Residual risk: shadow can never graduate without real outcome data (open question 6) |
| Cross-tenant leak via missing RLS | **Critical** | **Ruled** — mandate + delete flag | `USE_RLS_ROLE` required in production, escape hatch removed, tests run as tenant role |
| Focus dilution from two parallel markets | **High** | Accepted by ruling | Two tracks over one engine; H1–H2 shared and sequenced first; fork deferred to H3; single new surface permitted |
| Supplier disputes a trade-promotion readout | **High** | New — from decision 3 | Cannibalization modelling promoted to Track B critical path; readout must survive an adversarial audit |
| PDPL non-compliance on automated profiling | **High** | No DPIA exists | DPIA in Horizon 3; profiling is in scope and mandatory |
| SOC 2 timeline gates enterprise deals | **High** | Not started | Start observation window now — 6 months is irreducible |
| Systematic finance error invisible in aggregate | **High** | VAT fixed, no independent recon | Ledger reconciliation independent of the calculation path |
| Job loss on redeploy | Medium | No worker tier | Horizon 2 |
| Unit tests that do not execute SQL | Medium | Partially closed | Live-Postgres integration suite per service |
| Nav registration drift (3 layers) | Low | Tribal knowledge | Lint rule |

---

## 7. Decisions

### Decided — 20 July 2026

| # | Decision | Ruling |
|---|---|---|
| 1 | **ML posture** | **Rules live, ML in shadow.** Deterministic rule tier is the production decision path. ML logs shadow predictions alongside it and is promoted only when a pre-registered holdout beats rules with a confidence interval excluding zero. |
| 2 | **RLS** | **Mandate and delete the escape hatch.** `USE_RLS_ROLE=true` becomes mandatory in production; `ALLOW_INSECURE_NO_RLS` is removed from the production code path entirely. |
| 3 | **Positioning** | **Both in parallel** — retention and supplier-funded trade promotion pursued simultaneously. *(Owner ruling; differs from the recommendation in §3/CEO. Consequences below.)* |
| 4 | **Compliance timing** | **Start now.** SOC 2 Type II observation window opens immediately, Type I in parallel for active sales cycles. PDPL DPIA begins immediately as it is legally mandatory for automated profiling. |

### Consequence of running both markets in parallel

This is the ruling that most changes the shape of the work, so it is worth stating plainly rather than quietly absorbing.

The engine is shared — EIV, uplift, margin floor, ATP — and that is why the choice is viable at all. What is **not** shared, and must now be built twice or built generically, is everything around the engine:

- **Two buyers.** Retention sells to the CMO/commercial director who owns promo budget. Trade promotion sells to the supplier or the category/trading team. Different rooms, different objections, different proof.
- **Two funding models.** Retention spends the retailer's own budget against the retailer's own margin. Trade promotion spends **supplier money** against a jointly-agreed uplift. The budget ledger currently models only the first. Supplier-funded budgets need their own allocation, attribution and settlement path, plus a supplier-facing view of what their money bought.
- **Two proof obligations.** Retention proves incremental margin to the retailer. Trade promotion proves incremental *volume and margin on a specific supplier's SKUs* to a third party who will audit it — and who is contractually adverse. The holdout readout must be defensible to someone with an incentive to dispute it.
- **Cannibalization moves from H4 to blocking.** For retention, a promotion that shifts volume between own SKUs is a modelling nicety. For supplier-funded trade promotion it is the *central* question — a supplier will not pay for volume stolen from their own other SKU. This item is therefore promoted out of H4 and into the trade-promotion track's critical path.

**Mitigation:** run them as two tracks over one engine, sequenced so the shared work lands first. Horizons 1 and 2 are common to both and unchanged — proving incrementality and making the system operable serves both buyers identically. The fork happens at Horizon 3, which now splits.

### Revised Horizon 3 — splits into two tracks

**Shared (both tracks depend on it):** Flywheel metering in `services/billing.py`; hybrid pricing with usage visible before invoicing; PDPL compliance pack (DPIA, consent ledger, objection handling, 72-hour breach procedure, cross-border position); SOC 2 observation window running; real ingestion path for one pilot tenant.

**Track A — Retention:** retailer-funded budget path (exists today); CMO-facing incrementality narrative; contact governance surfaced in the UI.

**Track B — Trade promotion:** supplier-funded budget allocation, attribution and settlement; supplier-facing view of purchased outcomes; **cannibalization modelling** (pulled forward from H4); SKU-level and supplier-level incrementality readout defensible to an adverse auditor.

**Gate 3 (revised):** a pilot tenant's real data produces decisions and a metered invoice under Track A, *and* a supplier-scoped readout under Track B survives a deliberate attempt to dispute it. A DPIA exists that an auditor would accept.

Horizon 4 accordingly loses cannibalization (promoted) and retains coalition attribution, Ramadan seasonality, perishables/shelf-life, and the revisit of outcome-based pricing.

### Still open — blocking Horizon 3, not Horizons 1–2

5. **Pricing** — hybrid platform-fee-plus-metering now, or defer monetization until a pilot proves value? Note the trade-promotion track makes this more urgent, since supplier money needs a settlement mechanism regardless.
6. **Data** — is there a path to real customer data for a pilot, or does everything stay synthetic? This is now the binding constraint on the ML promotion criterion agreed in decision 1: shadow mode can never graduate without real outcome windows.
7. **Scope discipline** — is "no new pages in Horizons 1–3" accepted? The trade-promotion track breaks this by definition, since a supplier-facing view is a new surface. Confirm the exception.

Horizons 1 and 2 are fully unblocked by the four rulings above and can begin on approval.

---

*No code has been written against this plan. Awaiting explicit approval before any implementation begins.*

---

# Addendum A — Build Specification: New Surfaces & Deep Engineering

**Added 20 July 2026** after owner challenge: *"why is there no new tabs and features plus master level coding in the plan."*

The challenge is substantially correct and this addendum answers it. The original plan stated its engineering at bullet depth and buried its new surfaces as grudging exceptions to a "no new pages" rule. That framing was wrong in two ways: it under-described work that is genuinely hard, and it presented several *required* screens as concessions rather than as the features they are. What follows is the build specification that was missing.

One position from the original plan survives unchanged, and it is the reason the rule existed: **a new tab that re-slices data an existing tab already shows is dilution.** Every surface below fails that test — each one exposes a capability that has no home in the product today, and four of them expose logic that already exists in the backend with no UI at all.

## A.1 The gap that proves the point

`select_best()` (`backend/app/services/flywheel/optimizer.py:254`) is a **per-customer greedy selector**. It takes the candidate actions for one customer, filters on feasibility, the uplift gate, the margin floor and stock, then returns the single highest-EIV survivor. It is correct at what it does and the rejection accounting is good.

But it optimizes **one customer in isolation**, and customers are not independent — they compete for a shared budget and shared stock. Two consequences follow, both provable:

**Budget.** Under a binding budget, ranking by EIV is the wrong objective. The correct greedy objective is EIV **density** (EIV per AED committed). Picking the highest-EIV action for each customer independently and paying until the budget empties is the classic fractional-knapsack error; it leaves measurable margin on the table whenever cost varies across candidates, which it does — the discount ladder guarantees it.

**Stock.** ATP is checked per decision against current availability. With customers processed sequentially, a scarce SKU is consumed by whoever is scored first, not by whoever generates the most incremental margin from it. Order of iteration silently determines allocation. That is not a policy anyone chose.

This is the single highest-value piece of engineering available, it sits directly on the core differentiator, and the original plan did not mention it. Specified as **A.3.1** below.

## A.2 New surfaces — six tabs

Existing Flywheel surfaces (verified): `/flywheel`, `/customers`, `/studio`, `/models`, `/approvals`, `/budget`, `/campaigns/[id]`, `/decisions/[id]`.

### Tab 1 — Incrementality `/flywheel/incrementality`
**Horizon 1. The single most important screen in the product.**
The proof-of-value surface. Incremental gross margin per AED of promo spend, net of VAT, measured against the held-out control. Backed by `measurement.measure()`, which exists and is correct but is currently scheduled by nothing and displayed nowhere.

Must render: the headline number with an **always-valid confidence sequence** (see A.3.2), treatment/control sizes, the validity warnings from `_validity_warnings()` as first-class content rather than a footnote, per-segment breakdown from `_uplift_by_segment()`, and an explicit **"not yet significant"** state that reads as a normal operating condition and not as a failure. Time series of the readout across the campaign window so a marketer can watch significance accumulate rather than refreshing for good news.

### Tab 2 — Holdout `/flywheel/holdout`
**Horizon 1.**
The control group promoted to a first-class object. Who is held out, why they were selected, what the BLAKE2b stable assignment guarantees, holdout health (is it still balanced on covariates?), and the cumulative value the holdout has *proved* over its lifetime. Includes a covariate-balance check between arms — if treatment and control drift apart the measurement is worthless and nothing currently detects that.

The commercial argument for this tab: the holdout is the only reason anyone should believe the product works. Hiding it in an implementation detail wastes the asset.

### Tab 3 — Contact Governance `/flywheel/governance`
**Horizon 1. Backend exists, UI is entirely absent.**
Frequency caps, suppression lists and contact policy live in migration 076 and `contact_governance.py`, and a marketer currently cannot see any of it. Fatigue heatmap per customer, cap utilization per channel, active suppressions with reason and expiry, and the count of decisions suppressed by governance in the last period — that last number is a *feature*, not a loss: it is the system demonstrating restraint.

### Tab 4 — Shadow Mode `/flywheel/models/shadow`
**Horizon 1. Direct consequence of ruling #1.**
Extends the existing `/models` page. Side-by-side of what the rule tier decided versus what each shadow model would have decided, disagreement rate, and the pre-registered promotion criterion with current standing against it. Makes the governance control agreed in decision 1 *visible* rather than merely documented — which is what converts it from an excuse into a credential during due diligence.

### Tab 5 — Cannibalization `/flywheel/cannibalization`
**Horizon 3, Track B critical path.**
SKU-level halo and substitution. When SKU A is promoted, where did the volume come from — new demand, or SKU B? Category-level net incrementality versus promoted-SKU gross lift. This is the screen that determines whether a supplier pays, because a supplier will not fund volume stolen from their own other SKU. Backed by A.3.3.

### Tab 6 — Trade Promotion `/flywheel/trade`
**Horizon 3, Track B. The supplier-facing surface.**
Supplier-funded campaign lifecycle: funding commitment, allocation across SKUs and stores, spend against commitment, settlement state, and the supplier-scoped incrementality readout. Needs a distinct permission scope — a supplier sees their own SKUs and nobody else's, which is a second tenancy axis layered inside a tenant and must be enforced at the database, consistent with ruling #2.

## A.3 Master-level engineering — seven items

### A.3.1 Global constrained allocator *(Horizon 1–2, headline item)*
Replace per-customer greedy with a **portfolio allocation** across the campaign audience: maximize total EIV subject to total budget, per-SKU ATP stock, per-customer contact caps, and the per-campaign hard cap.

This is a multi-dimensional knapsack / generalized assignment problem. Structured as **min-cost flow** it is solvable exactly and fast: customers → candidate actions → SKU stock nodes → budget sink, with EIV as negative cost. Alternatively an LP relaxation with deterministic rounding, which is simpler to reason about and near-optimal in practice.

Non-negotiable constraints on the implementation, given what this codebase has already learned: it must stay **deterministic and replayable** (`replay()` must reproduce a portfolio decision exactly, so ties break on a stable key, never on iteration order); it must **explain every rejection** to the standard the current selector sets, including the new rejection class *"lost to a higher-density claim on the same constrained resource"*; and it must **degrade to current behaviour** when no constraint binds, so the change is provably safe. Ship behind a flag with a shadow comparison against greedy on the same audience, reporting the total-EIV delta — that number is a direct measure of the value of the work.

### A.3.2 Always-valid inference for the incrementality readout *(Horizon 1)*
A marketer watching a live campaign will refresh the incrementality page and stop when it looks good. Under fixed-horizon statistics that inflates the false-positive rate badly — repeated peeking at a conventional p-value is the most common way honest people report lift that isn't there.

Implement **anytime-valid confidence sequences** (e-values / mixture SPRT) so the interval is correct no matter how often it is inspected or when the campaign is stopped. This is not academic decoration: ruling #3 puts a supplier with a contractual incentive to dispute the number on the other side of the table, and a fixed-horizon p-value read continuously is the first thing a competent auditor will attack. Pair it with a pre-registration record — the metric, window and stopping rule fixed *before* the campaign runs, immutable afterwards.

This item is what makes Tab 1 defensible rather than merely attractive.

### A.3.3 Cannibalization and cross-elasticity estimation *(Horizon 3, Track B)*
Estimate a substitution matrix across SKUs within a category: promoting SKU A moves volume from SKU B at some rate. Net incremental margin must be computed at **category** level, not promoted-SKU level.

Two viable approaches given data volume. A **difference-in-differences on category totals** — comparing promoted-SKU lift against category lift in treated versus control stores — is robust, explainable to a supplier, and works at current data scale. A **hierarchical Bayesian demand model** with partial pooling across the SKU hierarchy is stronger and handles sparsity properly, but needs materially more history. Recommendation: ship DiD first because it is defensible and cheap, treat the Bayesian model as the upgrade path, and run it in shadow under the same governance regime as ruling #1.

### A.3.4 Worker tier with exactly-once delivery *(Horizon 2)*
Move scoring, activation, measurement and training out of the API process. The transactional outbox already guarantees exactly-once *write*; downstream *delivery* is not yet idempotent, which means a redelivery can double-send an offer to a customer. Needs an idempotency key on the consumer side, a dead-letter path, and visible retry semantics. `FOR UPDATE SKIP LOCKED` relay pattern is already in the codebase and extends naturally.

### A.3.5 Model registry with data-snapshot binding *(Horizon 2)*
Artifacts versioned against a **hash of the training data snapshot**, not just a timestamp. Without this, ruling #1's promotion criterion is unenforceable — you cannot claim a shadow model beat rules on a pre-registered holdout if you cannot prove which data it was trained on. Includes rollback, a documented promotion gate, and lineage from a live decision back to the exact artifact and snapshot that produced it.

### A.3.6 Distributed tracing end-to-end *(Horizon 2)*
`services/metrics.py` exists; there are no traces. A single decision must be traceable from HTTP request through candidate generation, allocation, budget reservation, approval, activation and redemption, with the trace id surfaced on `/flywheel/decisions/[id]`. Turns "why did this customer get this offer" from an investigation into a click — which is also a PDPL obligation once a data subject exercises the right to object to automated profiling.

### A.3.7 Identity resolution for real ingestion *(Horizon 3)*
Probabilistic matching to join POS transactions to loyalty identities — the step between synthetic data and a real pilot. Deterministic matching on loyalty id where present, probabilistic on the remainder, with a confidence threshold below which records stay unlinked rather than being wrongly merged. Wrongly merging two shoppers is worse than leaving both anonymous: it corrupts the feature store, the holdout assignment and the consent ledger simultaneously.

## A.4 Revised horizon map

| Horizon | Surfaces | Engineering |
|---|---|---|
| **H1 — Provable** | Incrementality, Holdout, Contact Governance, Shadow Mode | Global allocator (A.3.1), always-valid inference (A.3.2), measurement scheduling + persistence |
| **H2 — Operable** | *(none — deliberately)* | Worker tier (A.3.4), model registry (A.3.5), tracing (A.3.6), RLS enforcement per ruling #2, live-Postgres integration suite |
| **H3 — Sellable** | Cannibalization, Trade Promotion | Cannibalization estimation (A.3.3), identity resolution (A.3.7), Flywheel metering, supplier-funded ledger, PDPL pack, SOC 2 window |
| **H4 — Expand** | Coalition attribution surface | Ramadan/seasonality modelling, perishables & shelf-life constraints in the allocator, outcome-based pricing revisit |

Six new tabs, seven deep engineering items. Horizon 2 deliberately ships no new surface — that is the horizon where the system earns the right to be trusted, and it is entirely invisible to the user by design.

---

# Addendum B — Horizon 2 delivered (21 July 2026)

Horizon 2 ("make it operable") shipped. No new user-facing surface, by design —
this is the horizon where the system earns the right to be trusted, and it is
almost entirely invisible to the end user. Migration **078**; next free is 079.

**RLS mandatory, escape hatch deleted (ruling #2).** `USE_RLS_ROLE` is now
required in production unconditionally; `ALLOW_INSECURE_NO_RLS` is retired and
setting it in production is a hard startup error rather than a bypass. Proved at
the database, as the non-owner `app_rw` role: with tenant GUC=1, a read sees only
tenant 1, and a cross-tenant INSERT is rejected by the policy's WITH CHECK. That
is Gate 2(b).

**Durable job tier (A.3.4).** A Postgres-backed queue (`flywheel_jobs`) claimed
with `FOR UPDATE SKIP LOCKED`, with a **lease** (a dead worker's job is reclaimed
by the reaper) and a **checkpoint** (a resumed job continues from the last
completed batch). Proved end to end: a scoring job killed mid-run was reaped,
resumed, and scored every customer **exactly once** — 300/300, no loss, no
repeat. That is Gate 2(a). Exactly-once *delivery* is handled by a consumer-side
idempotency ledger (`flywheel_delivery_receipts`); a redelivered event is a
no-op. The worker runs single-instance in the singletons container.

**Model registry bound to its data (A.3.5).** Every model version now carries a
`data_snapshot_hash` — a fingerprint of its exact training rows — plus lifecycle
status and rollback lineage. Promotion **refuses** a version with no snapshot,
because a model whose training data cannot be identified cannot be judged against
a holdout; that guardrail is what makes ruling #1's promotion criterion
enforceable. Rollback restores a known-good prior version in one call and records
the reversal.

**End-to-end tracing (A.3.6).** A `trace_id` spans a decision's whole life —
decision, activation, outbox event, redemption days later — so "why did this
customer get this offer, and what became of it" is one lookup. Surfaced at
`GET /flywheel/decisions/{id}/trace`. This is also the PDPL right-to-explanation
for an automated decision, and the timeline is labelled as such.

**Live-Postgres integration suite.** Ten tests that run against the real database
(`RUN_DB_TESTS=1`), most as the `app_rw` role — the test shape that would have
caught the first-live-call failures this project keeps learning about. They cover
RLS isolation, crash/reap/resume, idempotent enqueue, exactly-once delivery,
registry binding + promotion guard, and decision tracing.

**Verification.** 290 unit tests pass across every touched suite; the full suite
shows **66 failures with these changes versus 67 at the Horizon-1 baseline**, and
the delta is a test that now passes — zero regressions introduced (the remainder
are pre-existing environment artifacts). `tsc --noEmit` exits 0. All new
endpoints verified 200 live; the job worker verified processing a queued job to
completion in the running singletons container.

**Gate 2: PASSED.** Kill the worker mid-run → the campaign's work completes,
exactly once. Cross-tenant queries fail at the database, not the application.

Horizon 3 (Track A retention + Track B trade promotion) remains blocked on the
three open questions in §7: pricing, whether real customer data is reachable, and
scope confirmation.
