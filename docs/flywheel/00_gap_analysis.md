# Flywheel — Repository Audit & Gap Analysis

**Date:** 2026-07-20 · **Author:** Krishna Mathur · **Branch:** `flywheel-ai`

Audit performed per Section 1 of `FLYWHEEL_MASTER_PROMPT.md` before any feature code
was written. Everything below is read from the actual codebase, not assumed.

---

## 1. What exists (and what Flywheel reuses rather than rebuilds)

The platform is far more built-out than the blueprint assumed. 47 route modules,
90+ services, 73 applied migrations. The following are **reused as-is**:

| Concern | Existing asset | Flywheel's use |
|---|---|---|
| Tenancy | `tenant_id` + `current_tenant_id()` SQL fn (migration 012), FORCE RLS, `tenant_context` ContextVar, `apply_tenant_guc()` | Every Flywheel table carries `tenant_id` and gets the identical `tenant_isolation` policy |
| Auth | `app/auth_deps.py` — `get_current_user`, `require_role`, `require_permission`, `get_accessible_store_ids`, `get_current_user_from_ticket` | Flywheel routes depend on these unchanged; no new auth code |
| DB session | `services/database.py` — `get_db`, `async_session`, `rls_session`, `exempt_statement_timeout` | Flywheel uses `get_db` for request paths, `async_session` for background/seed |
| Route registration | `routes/registry.py` `ROUTERS` list | One-line append in the Krishna block — `main.py` untouched |
| Nav registration | `frontend/src/config/nav.tsx` `navItems` | One-line append — `Sidebar.tsx` untouched |
| SSE | `routes/stream.py` + `auth_deps.get_current_user_from_ticket` (`?ticket=`), `services/redis_client.py` channels | Flywheel adds channels + a `/stream/flywheel` endpoint following the same ticket pattern |
| Money | `items.unit_price_aed` (DECIMAL), **`item_costs`** table — effective-dated `unit_cost_aed NUMERIC(12,4)` per (tenant, item) | Price **and cost** snapshots for margin math already have a source of truth |
| Inventory | `inventory` (store×item, `current_stock`, `reserved_stock`, generated `available_stock`, `reorder_point`), `inventory_transactions`, `inventory_batches` | ATP is layered **on top** — Flywheel adds allocations/reservations, does not fork stock |
| Procurement | `suppliers` (`lead_time_days`), `product_suppliers` (`unit_cost`, `moq`, `lead_time_days`, `is_preferred`), `purchase_orders`, `purchase_order_lines`, `stock_transfers` | Requisitions aggregate into these existing PO/transfer structures |
| Audit | `audit_log` (actor, action, resource_type/id, old/new JSONB, ip) | Flywheel writes every decision/approval/ledger event here |
| ML runtime | **`lightgbm==4.3.0`, `scikit-learn==1.5.2`, `torch==2.2.2` (CPU), `pandas`, `numpy` already pinned** | Baseline + sequence model + FT-Transformer need **zero new dependencies** |
| Frontend | Next 14 App Router, `framer-motion@^11`, `@tanstack/react-query@^5`, `recharts`, Tailwind, `AuthContext`, `lib/api.ts`/`apiClient.ts` (TTL cache keyed on full auth scope), `hooks/useEventStream.ts` | Flywheel pages use the installed stack — no new frontend deps |

## 2. What is genuinely missing (Flywheel must add)

- **No customer layer at all.** No `customers`, no per-customer event history, no consent.
  The sales facts are store×item×day aggregates (Kaggle units data) with no customer identity.
- **No churn/uplift modelling.** `predictions` exists but is forecast/stockout-oriented;
  there is no `model_versions` registry, no feature snapshots, no calibrated classifier.
- **No budget ledger.** No `budgets`, no reservations, no allocated→spent lifecycle.
- **No approval engine.** `approval_rules` exists but is a single scalar per tenant
  (`auto_approve_under NUMERIC`) — no multi-step, no parallel steps, no policy config.
- **No transactional outbox / idempotency keys.** Publishing is direct Redis `publish_*`.
- **No campaign concept.** `promotions` is a static discount catalogue with no audience,
  no state machine, no treatment/control, no measurement.

## 3. Decisions & assumptions recorded

1. ~~**`stores` and `items` carry no `tenant_id`**~~ — **CORRECTED 2026-07-20.**
   This claim was WRONG. It came from grepping the migration files rather than
   inspecting the live schema; both tables DO have `tenant_id` (added by a
   migration whose ALTER my grep pattern missed). Verified with `\d stores` against
   the running database. Flywheel still scopes by its own `tenant_id` and joins
   stores/items without a tenant predicate — matching every existing reader — and
   store-level access is enforced with `get_accessible_store_ids`, so no code
   changed. Recorded here because an audit that states a false fact is worse than
   one that omits it.
2. **Migration numbering** — highest applied is `073_krishna_bespoke_requests.sql`;
   Flywheel takes **074**. Runtime migrations stay plain SQL (alembic holds only the E6-2
   baseline squash).
3. **Frontend animation package** — the repo pins `framer-motion@^11`, not the newer
   `motion` package. Flywheel imports from `framer-motion` to avoid adding a dependency and
   breaking the existing build; the premium-frontend patterns are otherwise applied
   verbatim (variants, `whileInView`, `useReducedMotion`, transform/opacity only).
4. **Money** is `NUMERIC` in Postgres and `Decimal` in Python everywhere. Unit COST comes
   from `item_costs` (effective-dated); where a tenant has no cost row, Flywheel derives a
   documented default margin assumption and records it in the decision snapshot.
5. **No new roles.** Flywheel maps onto existing roles (`super_admin`, `regional_manager`,
   `store_manager`, `analyst`) plus existing permission flags on `user_permissions`
   (`can_manage_promotions`, `can_manage_inventory`, `can_view_financials`,
   `can_approve_transfers`). Approval *steps* are configuration rows, not new roles.
6. **Synthetic data is confined and labelled.** Flywheel customers are generated with a fixed
   seed, stamped `is_synthetic = TRUE`, and confined to `settings.demo_tenant_id`, following
   the E0-8 precedent for the sales generator. Every UI surface labels the data synthetic.
7. **No LangChain/CrewAI.** Explicit typed services + a persisted state machine, per §4 of
   the master prompt. The existing local-first Sage provider chain is reused for narration
   only — it never mutates money, stock, or approvals.

## 4. Sensitive-attribute / fairness note

No gender, ethnicity, religion, or nationality attribute is generated, stored, or used as a
model feature or offer-decision input. Features are strictly behavioural (recency,
frequency, spend drift, interpurchase gap, category diversity, return ratio, promo response).

## 5. Honesty statement

All customers, events, treatment histories and campaign outcomes are **synthetic**. Model
metrics are reported on synthetic holdouts and **no production accuracy is claimed**.
