# AI Commercial Orchestration — one module

> **Merged.** There is now ONE closed-loop retention decisioning module:
> **Flywheel** (`/api/flywheel`, `app/services/flywheel/`). The separate
> `/api/retention` module was folded into it. This document records what moved,
> what was retired, and why.

## Why they merged

Two modules had been built independently against the same business domain
(churn → uplift → offer → stock/budget/approval → execution → measured lift):

| | Retention (retired) | Flywheel (kept) |
|---|---|---|
| Backend | ~1,500 lines, 3 modules | ~12,200 lines, 36 service modules |
| Tables | 7 (`customers`, `retention_*`, `campaign_*`) | 52 (`flywheel_*`, self-contained) |
| Routes | 18 | `/api/flywheel` (1,774-line router) |
| Frontend | 1 page | 16 pages |
| Tests | 41 | 295 |

They shared **no tables and no routes** — flywheel has its own
`flywheel_customers` and never referenced retention's. So this was duplication of
a domain, not a layered design. Flywheel is the more complete implementation
(causal uplift, sequential/SPRT testing, shadow mode, cannibalization, coalition,
seasonality, trade promotion, transactional outbox, decision trace, contact
governance, identity/erasure, liability/tax) and it kept its 52 tables and 16
surfaces. Retention was retired into it.

## What retention contributed (kept, not lost)

Retention had exactly two things flywheel lacked. Both were ported.

### 1. Scenario mathematics → `services/flywheel/scenario_math.py`

Flywheel's `campaigns.simulate()` derived its three scenarios by multiplying
redemption by fixed **0.6× / 1.0× / 1.4×** factors. That band is arbitrary: the
same width whatever the audience size or model confidence, and structurally
unable to express a probability of loss — the exact failure mode the board pack
calls out (p.2 "show uncertainty rather than one sales promise"; p.9 "shows
expected result and tail loss, not only average profit").

`simulate()` now also returns an `uncertainty` block from
`monte_carlo_campaign()`, which samples a **lognormal response multiplier**
(always positive, right-skewed like real redemption), applies it to the
response-driven components while holding fixed costs fixed, and reports:

- `net_value_p10_aed` / `p50` / `p90` and the mean
- `cvar_5pct_aed` — mean of the worst 5% of outcomes (tail loss, not a quantile)
- `loss_probability` — which the fixed band could never produce
- `expected_spend_aed`, `roi_mean`

Seeded from `(tenant, campaign, "simulate")` so a persisted decision reproduces
exactly. **Additive** — `scenarios.pessimistic/expected/optimistic` are unchanged,
so all 16 existing flywheel pages keep working.

The module also carries the SKU-level demand tools (`base_demand_quantiles`,
`empirical_quantiles`, `monte_carlo`, `cash_at_risk`), including the
Croston-style **intermittent-demand guard**: a series with ≥35% zero-demand
periods is flagged `intermittent_low_confidence` rather than smoothed. These are
the documented seam for a LightGBM quantile model, per the board pack's
instruction to benchmark before adopting.

### 2. Transaction-safety gate → `tests/test_flywheel_concurrency.py`

`decisioning.redeem()` asserted in a *comment* that "FOR UPDATE here is what
makes concurrent redemptions safe", but nothing in a 295-test suite ever ran two
redemptions at once. Retention's Phase 0 gate was retargeted onto flywheel's
redemption path. Each concurrent actor gets its own `AsyncSession`, so the row
locks and the campaign cap are genuinely contended:

1. **No negative stock** — 10 concurrent redemptions vs 4 units → exactly 4 apply, stock lands on 0.
2. **No cap breach** — 10 concurrent redemptions vs a cap fitting 3 → exactly 3 apply, spend 6.00. Guards the in-transaction hard cap that stops a campaign outspending its own ceiling.
3. **Idempotency under race** — the same key fired 8× concurrently applies once; the rest replay the original.
4. **Ledger reconciles** — `flywheel_budget_ledger` SPENT entries match the redemption rows (asserted non-vacuously; skips if no active DISCOUNT budget rather than fabricating one).

conftest pins `DATABASE_URL` to a throwaway `testdb`, so the module builds its
own engine **per test** (pytest-asyncio uses a fresh event loop per test and
asyncpg connections cannot cross loops). Skips cleanly with no database, so
database-free CI stays green.

## What was retired

Deleted: `routes/retention.py`, `services/retention_service.py`,
`services/campaign_scenario.py`, `frontend/src/app/retention/page.tsx`, and the
four retention test modules. Removed from `routes/registry.py`,
`config/nav.tsx`, `locales/nav.ts` (EN + AR) and `lib/nav/registry.ts`.

**Migration 074 was deliberately NOT dropped.** Its 7 tables (`customers`,
`customer_purchases`, `retention_campaigns`, `campaign_offers`,
`campaign_allocations`, `retention_budget_ledger`, `retention_events`) still
exist and still hold seeded rows. Dropping data is irreversible and belongs in
its own deliberate migration, not in a refactor — and migrations are immutable
history, so 074 itself must not be rewritten. The tables are now unreferenced by
any code path. A follow-up `DROP TABLE` migration is the clean way to retire
them once someone confirms nothing external reads them.

Retention's decision-pack extras that had **no flywheel equivalent and no
consumer after the merge** — the nine department views, the conflict catalogue
and the data-readiness gate — went with `campaign_scenario.py`. They were built
against retention's schema and would have needed a full rewrite onto flywheel's
52-table model to survive; re-adding them belongs with the board pack's
governance phase, against flywheel's own approval and trace tables (which
already cover much of the same ground via `flywheel_approval_*` and
`services/flywheel/trace.py`).

## Verification (commands actually run)

- `pytest tests/ -k flywheel` in-container → **295 passed, 17 skipped, 0 failed**
- `pytest tests/test_flywheel_scenario_math.py` → **21 passed** (16 ported + 5 new campaign-MC)
- `pytest tests/test_flywheel_concurrency.py` → **4 passed** against live Postgres
- `npx tsc --noEmit` → clean
- Backend imports: 48 routers (retention router gone, flywheel present)
- Migrations 075–080 applied to the dev database: 52 `flywheel_*` tables

## Known limitations

- `response_cv` (0.35) is a fixed assumption, not fitted from redemption history.
- The campaign Monte Carlo varies the response multiplier only; base-demand
  uncertainty is modelled in `monte_carlo()` but flywheel's simulator aggregates
  across many (store, SKU) pairs rather than a single SKU, so it is not yet wired
  into `simulate()`.
- The `uncertainty` block is not yet surfaced in the flywheel UI.
