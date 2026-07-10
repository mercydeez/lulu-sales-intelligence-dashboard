# Demo / Sample Data vs. Real Customer Data

> **This is a binding honesty contract for the product.** Every user-facing surface — dashboards, KPIs, reports, AI (Sage) answers, exports, and docs — must make clear which kind of data the user is looking at. We never present synthetic/sample data as real customer data.

## The four data categories

| Category | What it is | How it enters the system | How it must be labelled |
|----------|------------|--------------------------|-------------------------|
| **Demo / sample data** | Synthetic, fictional. The "Meridian Hypermarket" demo retailer. | `init.sql` seed (date-shifted Kaggle store-item demand dataset) + the live `DataGenerator` | Visibly marked "Demo data" / "Sample data". Never described as real sales. |
| **Real imported customer data** | A tenant's own historical sales they load themselves. | CSV/Excel import or ingestion API (**deferred — not yet available**) | Marked as the tenant's real data, with source + ingestion timestamp. |
| **Derived AED revenue** | A **computed** value: `SUM(units × items.unit_price_aed)`. | Calculated at query time from units + a price table | Must read as **derived/estimated revenue**, never "actual revenue captured at POS". |
| **Raw unit volume** | The source-of-truth measure (the Kaggle dataset is units sold). | Stored directly | A **volume** metric. Never mixed with AED on one axis. |

## Non-negotiable rules

1. **Synthetic ≠ real.** No report, KPI, AI answer, or doc may claim demo/sample/synthetic data is real customer data.
2. **Units ≠ AED.** Volume metrics are in units; value metrics are in AED (derived). Never mixed on one axis. (See CLAUDE.md "Units vs currency" trap and `routes/kpis.py` as the reference implementation.)
3. **Derived ≠ captured.** AED revenue is derived from a price table, not captured at a point of sale. Phrase it as derived/estimated.
4. **Demo data is opt-in in production.** Synthetic seed + generator only run when `DEMO_MODE=true` (and the generator additionally requires `LIVE_GENERATOR_ENABLED=true`). A real-tenant production deployment shows real or empty data — never auto-generated synthetic sales.
5. **Synthetic writes are confined to the demo tenant, by the database.** Every generated sale is stamped `tenant_id = DEMO_TENANT_ID` and `is_synthetic = true`, and migration 057's trigger on `sales_stream_raw` *rejects* a synthetic row carrying any other tenant_id. The `DEMO_MODE` flag is a process-level intent; the trigger is the guarantee. The generator additionally draws only store/item ids that the demo tenant actually owns, and refuses to start if it owns none. Generated rows are wiped nightly (`DEMO_RESET_HOUR_UTC`, retaining `DEMO_RESET_RETAIN_HOURS`) so the demo never drifts into a fabricated all-time high.
6. **Disclosure travels with the answer.** When Sage answers from demo data, the answer says so. When data is stale, freshness is shown.

## Current state (be honest)

- **Today the product ships with demo data only.** All sales are synthetic; there is no real-customer-data path yet.
- **Self-serve import (CSV/Excel) and the public ingestion API are deferred** to a later cycle (see `docs/production/KNOWN_LIMITATIONS.md`). Until they ship, a pilot either runs on demo data or has data loaded manually by an operator — and this is stated plainly to the customer.
- **AED figures are always derived.** There is no POS integration. We do not claim one.

## Where this is enforced

- Backend: `routes/kpis.py` (units/AED reference), `DEMO_MODE`/`LIVE_GENERATOR_ENABLED`/`SAMPLE_DATA_ENABLED` flags (Phase 1), AI evidence/disclosure block (Phase 11).
- Frontend: demo/sample labels and data-freshness indicators on major pages (Phase 10).
- Docs: this file, `README.md` honesty notes, `BASELINE_AUDIT.md`.
