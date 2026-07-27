# Tenant isolation tiers (E10-2)

**Status:** control plane built; `dedicated_schema` data-plane primitive built + tested.
**Code:** `backend/app/services/provisioning.py`, `isolation.py`, migration 068,
routes `/api/admin/provisioning/*` (super-admin).

---

## The three tiers

| Tier | What the tenant gets | State in this build |
|---|---|---|
| `shared` | One schema, separated by `tenant_id` + Postgres RLS | **Served.** The default; needs no provisioning. |
| `dedicated_schema` | A private Postgres schema (`tenant_<id>`) holding the tenant's own copies of the core transactional tables | **Provisionable + served when active.** Raw-table isolation works; see the analytics boundary below. |
| `dedicated_db` | A fully separate database | **Operator-provisioned.** The control plane records + governs it; DB creation is a runbook step. |

## The control plane (what's new)

Before E10-2 completion, a tenant's tier was a flag and anything but `shared`
returned a bare `503`. Now there is a governed lifecycle:

```
requested ──provision──▶ provisioning ──▶ active
                                    └──▶ failed (records why)
active ──deprovision──▶ deprovisioning ──▶ deprovisioned ──▶ (back to shared)
```

Tracked in `tenant_provisioning` (migration 068). The key behavioural change:
**`isolation.enforce_tenant_isolation` consults the provisioning record, not just
the flag** — a dedicated tier is served ONLY when provisioning is `active`, and
still fails closed (`503`) otherwise. Both entry points (login and API-key auth)
go through this gate.

Admin API (super-admin only):

```
GET  /api/admin/provisioning                     # every tenant's state
GET  /api/admin/provisioning/{tid}
POST /api/admin/provisioning/request  {tenant_id, tier}
POST /api/admin/provisioning/{tid}/provision
POST /api/admin/provisioning/{tid}/deprovision[?force=true]
```

## `dedicated_schema` — what it isolates, and the honest boundary

`provision` creates schema `tenant_<id>` and, in it, isolated copies of the core
transactional tables (`stores`, `items`, `suppliers`, `sales_historical`,
`inventory`, `purchase_orders`, `promotions`, `item_costs`) via
`CREATE TABLE … (LIKE public.x INCLUDING ALL)`. Verified live: a write to
`tenant_2.stores` never appears in `public.stores`; deprovision drops the schema.

**The boundary, proven not glossed.** A Postgres VIEW binds to the schema of its
referenced tables *at creation time*, not at query time:

```sql
-- tenant_t.probe_base='TENANT', public.probe_base='PUBLIC', search_path=tenant_t,public
SELECT v FROM probe_base;              -- TENANT   (unqualified → search_path)
SELECT v FROM public.probe_view;       -- PUBLIC   (view bound to public at creation)
```

So the ~32 shared analytics views/matviews in `public` (`metric_*`,
`sales_fact_view`, `sage_*`, `mv_*`) still read `public` for a dedicated tenant.
Isolating the analytics layer too means **replicating that whole view/matview
stack into each tenant schema and applying every future migration to every tenant
schema** — a larger data-plane project, not done here.

Because routing a tenant's raw tables to their schema while the analytics still
read `public` would give them a *correct-looking-but-wrong dashboard*, live
`search_path` routing is **off by default** (`ENABLE_DEDICATED_SCHEMA_ROUTING`).
`dedicated_schema` today therefore delivers **physically isolated transactional
tables** (the tenant's PII/sales rows are not commingled in the shared tables),
governed by the control plane. Enabling full routing is the documented next step,
gated behind the view-stack replication.

## `dedicated_db` — the operator path

A separate database is the cleanest full isolation (it gets the entire schema via
the normal migrate job — no view-binding problem). It is **not** created from a
request handler (that would be dishonest infrastructure-by-API). `provision`
records the intent and returns the runbook:

1. `CREATE DATABASE tenant_<id>_db` (as a role with `CREATEDB`).
2. `DATABASE_URL=<new-db> python -m app.commands.migrate` to build the schema.
3. Register the per-tenant DB URL in the routing config and wire a per-tenant
   engine (extends the E10-7 read-replica routing pattern).
4. Activate the provisioning record.

## Safety

- Control-plane routes are **super-admin only** and audited (`tenant_provisioned`,
  `tenant_deprovisioned` security events).
- `deprovision` always drops any dedicated schema defensively, so switching tiers
  never orphans one.
- A dedicated tenant that is not `active` **cannot log in and cannot use an API
  key** — it is refused, never silently downgraded to shared.
