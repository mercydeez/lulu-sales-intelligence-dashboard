# AI Commercial Orchestration — Phase 0 + Phase 1

Extends the retention module into a campaign **decision control tower**: before
launch, a reviewer sees normal demand, low/expected/high outcomes across offer
depths, category effects, inventory & shelf-life risk, *proposed* procurement
options (never an auto-created PO), finance cash/profit with visible downside, a
risk-adjusted recommendation, and a plain-language view per department.

> All customer data, histories and effects are **synthetic**. Price-response,
> cannibalisation, halo and forward-buy are **transparent provisional
> heuristics (confidence: low)** — honest placeholders until randomized history
> trains them (Phase 4), never presented as measured causal effects.

## Phase 0 — verification & repair (done, evidence below)

Verified on the **live database** (`sales_db`), not asserted:

| Check | Result |
|---|---|
| Migration `074` recorded in `schema_migrations` | ✅ present |
| 7 retention tables exist | ✅ all present |
| RLS `tenant_isolation` policy on each | ✅ all 7 |
| Deterministic seed (tenant 1) | ✅ 115 customers, 1558 purchases, 10 archetypes, 15 no-consent lapsed |
| Tenant-2 cohort (isolation demo) | ✅ 5 customers |
| Retention unit tests, in-container (Linux, pinned deps) | ✅ 17/17 |
| Live scenario run over real SQL | ✅ pack built, **0 side effects** (PO 3→3, budget spent 0) |
| HTTP flow (login→create→audience→scenario) | ✅ 200s, pack + 9 dept views |

**RLS note (not a defect):** the DB owner role `salesuser` bypasses RLS by
design; RLS is FORCE-enforced only under the separate app role (migration 020).
App-layer `tenant_id` scoping is the primary control and every query carries it.

**Repair applied:** `simulate()` previously created a draft **purchase order**
via `_draft_requisition()` — a real procurement side-effect during simulation,
violating "no side effects" and "never auto-buy". Removed. Procurement is now
**proposed** by `campaign_scenario.procurement_options` (compared, never
committed); a real draft PO is created only at approval (Phase 2). The dead
`_draft_requisition` was deleted; `retention_campaigns.requisition_po_id` is
reserved for the Phase-2 link.

## Phase 1 — capability audit map

| Capability | Status | Where |
|---|---|---|
| Normal-demand baseline | reuse + extend | `forecast_service.demand_baseline` (category) + trailing-84d per-SKU query |
| Inventory ATP / safety stock | reuse | `inventory.available_stock`, `retention_service._atp` |
| Shelf-life / expiry (FEFO) | reuse | `inventory_batches.expiry_date/quantity` |
| Price/cost, margin | reuse | `items.unit_price_aed` / `unit_cost_aed`, `item_costs` |
| Supplier terms (MOQ/lead/cost) | reuse | `product_suppliers` |
| Overlapping-promotion detection | reuse | `promotions` + `promotion_items/stores` |
| Churn score + audience | reuse | `retention_service.churn_score`, `build_audience` |
| Response estimate | reuse | `retention_service.response_prob` |
| Treatment/control split | reuse | `retention_service.assign_cohort` |
| Budget position | reuse | `retention_campaigns` columns + `retention_budget_ledger` |
| Audit trail | reuse | `retention_events` |
| Scenario simulator (baseline, L/E/H, category effects, inventory risk, procurement options, finance, risk-adjusted recommendation, conflicts, department views) | **new (Phase 1)** | `campaign_scenario.py` |
| Data-readiness gate | **new** | `campaign_scenario.data_readiness` |

No new tables were added in Phase 1 — the pack persists into the existing
`retention_campaigns.simulation` JSONB under `scenario_pack`.

## Formulas (all money in Decimal)

```
campaign demand      = baseline_units + baseline_units × price_response(discount)
demand L/E/H         = baseline + expected_lift × {1−band, 1, 1+band}   (band 0.40)
net category units   = promoted_lift − cannibalized + halo − forward_bought
                       (0.35 / 0.15 / 0.20 of promoted_lift; confidence low)
ATP                  = available_stock − safety_stock − live soft allocations
shortfall (high)     = max(0, demand_high − (ATP + incoming_supply))
expected expiry loss = min(units_expiring_before_end, leftover) × cost × (1 − salvage 0.20)
net profit(units)    = max(0, units − baseline) × (price×(1−d) − cost)
                       − media − comm − expiry_loss
worst credible loss  = profit(demand_low) − committed_procurement_cash
risk-adjusted value  = expected_profit − 0.5×|worst_loss| − 0.10×proc_cash
                       − expiry_loss − customer_harm         (penalties kept visible)
```

Margin floor: a discount depth selling below `min_margin_pct` (or with unknown
cost) is `policy_ok=false` and excluded from the recommendation ranking.

## Recommendation logic

`NEEDS_MORE_DATA` if data NOT_READY → else rank policy-compliant scenarios by
risk-adjusted value → `REJECT` if best ≤ 0 or a blocking conflict → prefer the
**cheapest effective action** (a 0%-discount scenario within 5% of best RAV
wins, so a discount is never wasted) → `PILOT` on warnings / low confidence /
irreversible procurement → `APPROVE_WITH_CONDITIONS` if non-blocking conflicts →
else `APPROVE`. High churn / big lift never wins on its own.

## Conflict catalogue (Phase-1 computable subset)

`C1` discount>budget (blocks) · `C3` MOQ over demand · `C6` supplier too late ·
`C7` cannibalisation net-negative · `C9` forward-buy dip · `C10` overlapping
promotion · `C13` shelf-life waste · `C26` low-confidence spend (blocks when
NOT_READY) · `C28` severe low-case downside. Each carries evidence, impact,
resolution, required approver, and a `blocks_campaign` flag.

## API (added)

`POST /api/retention/campaigns/{id}/scenario` — build + persist the decision
pack (read + compute only; no money/stock/PO). The pack is also embedded in the
`simulate` lifecycle step. Campaign create now accepts an `objective` (churn
retention, lapsed reactivation, excess-stock clearance, near-expiry waste, …).

## Frontend

`/retention` gains: objective selector on the draft form, a **Run scenario
analysis** action, a recommendation banner (decision + conditions + data
readiness), a **scenario comparison** table (demand L/E/H, net category, stock
risk, profit L/E/H, worst loss, risk-adjusted value, policy), a chosen-scenario
**fulfilment options + conflicts** panel, and **department review** cards for all
nine roles. RTL/keyboard/reduced-motion inherited from the shared UI kit.

## Test evidence (commands actually run)

- `pytest tests/test_campaign_scenario.py tests/test_retention.py` — **41 passed**
  (host and in-container).
- Live integration (container, real DB): audience 6/11, baseline 330, four
  scenarios L/E/H, PILOT recommendation, **PO 3→3, budget 0** (no side effects).
- HTTP smoke (demo super_admin login): create→audience→scenario all 200; pack
  persisted under `simulation.scenario_pack`; decision reproducible from stored inputs.
- Full existing suite: see the session report; the only failures are pre-existing
  container **path/env artifacts** (`test_alembic_baseline`, two
  `test_tenant_isolation` file-path checks, `test_default_rate_limits` env
  override) that fail identically on unmodified code.

## Known limitations

- Heuristics are provisional (confidence low); no trained price/uplift/
  cannibalisation models yet (Phase 4).
- Per-SKU baseline is a trailing-84-day mean, not the full seasonal model
  (that anchors the category baseline); good enough for Phase-1 ranges.
- Operations capacity is a single rules-based flag.
- One store + one SKU per campaign (multi-scope is Phase 4).

## Deferred to Phase 2 (do NOT auto-start)

Cross-functional approval matrix, budget reservation at approval, soft stock
allocation, transfer/requisition **commitment**, staged/conditional PO creation
from the chosen scenario's procurement option.
