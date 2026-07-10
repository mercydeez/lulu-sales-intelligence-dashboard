# Improvement Roadmap — What Else Makes This SaaS Better

> The prioritized brainstorm: what to build next, honestly costed, grounded in what
> the repo actually contains today (every item cites the real service/migration it
> builds on). Companion to `SAAS_PATH.md` (the strategic frame) and
> `PLATFORM_CONSOLE.md` (the bespoke→product loop several items close).
> Rule inherited from the rest of the docs: no item claims more than the code does.

**How to read:** *Now* = ≤1 quarter, *Next* = 1–2 quarters, *Later* = 2+ quarters.
Effort is S/M/L relative to this three-developer team. "Wins" names the commercial
mechanism — a deal-closer, a retention hook, or both — because a roadmap item that
can't say who pays for it is a hobby.

---

## Now (≤ 1 quarter)

### 1. Self-serve onboarding wizard — first import → first insight in <30 minutes
- **What:** One guided flow: sign up (self-serve provisioning already exists —
  `services/tenant_provisioning.py`, migration 068) → upload a sales CSV
  (`services/csv_import.py`) or connect a source (`services/data_sources.py`) →
  see your own daily briefing (`services/briefing.py`). The pieces all exist; the
  wizard is the missing thread through them, plus a time-to-first-insight metric.
- **Wins:** deals — trials that reach an insight convert; trials that stall in setup
  churn before sales ever calls. This is the single highest-leverage funnel fix.
- **Effort:** M. **Depends on:** nothing new — sequencing existing surfaces.

### 2. Email digests of findings and briefings
- **What:** The daily executive briefing already renders an emailable one-pager
  (`briefing.build_briefing_html`), and notifications already have an email hook
  (`services/notifications.py :: _maybe_email`) plus SMTP plumbing
  (`services/security_notify.py`). Wire a scheduled per-user digest (daily/weekly,
  respecting notification preferences) instead of relying on users logging in.
- **Wins:** retention — the product shows up in the inbox even in weeks nobody opens
  a dashboard. Cheapest habit-forming surface available.
- **Effort:** S. **Depends on:** deployment SMTP config (exists, currently global).

### 3. Data-quality scorecard
- **What:** Every import already produces and stores a data-quality report with a
  letter grade (`csv_import.build_quality_report`, E1-5; persisted per job by
  `routes/imports.py`) — but it lives per-import, in the import history. Roll it up:
  a tenant-level scorecard page trending grade, rejected rows, duplicates, and data
  freshness across imports, prominent on the tenant's data page.
- **Wins:** both — buyers distrust dashboards built on data they can't inspect;
  "here's your data health, trending" is a trust feature competitors skip.
- **Effort:** S. **Depends on:** import jobs tables (migration 047, exists).

### 4. Tenant config export/clone — the bespoke productization loop
- **What:** All per-tenant customization now lives in one JSONB namespace
  (`tenants.settings -> 'customizations'`, `services/customization.py`). Add
  export/import of that namespace so one negotiated bespoke spec becomes a reusable
  template ("the fresh-food-chain preset") applied to the next similar client.
- **Wins:** deals — bespoke work stops being one-off cost and starts compounding.
  Sales can offer "the configuration proven at a peer retailer" on day one.
- **Effort:** S–M. **Depends on:** customization engine (Platform Console change-set).

### 5. Bespoke-request → productization metrics
- **What:** The bespoke ledger (Platform Console) records every ask the catalog
  couldn't satisfy, with statuses and decline reasons. Report on it: which asks
  recur, which got declined for the same gap, which delivered bespoke items should
  be promoted to first-class catalog keys. The ledger is the cheapest honest market
  research the company owns.
- **Wins:** retention indirectly — the roadmap starts tracking demand instead of
  hunches, and recurring asks become catalog features every tenant gets.
- **Effort:** S. **Depends on:** bespoke ledger (Platform Console change-set).

### 6. Alert-rule tuning UI
- **What:** Alerting exists (`services/alerting.py`, `services/alert_service.py`,
  `docs/production/ALERTS.md`) but thresholds are deployment-level configuration.
  Give tenant admins a rules screen: per-alert-type thresholds, severities, mute
  windows, and routing — on top of the existing notification preferences.
- **Wins:** retention — mistuned alerts are the top reason ops tooling gets muted
  and then abandoned. Tunable alerts survive contact with real stores.
- **Effort:** M. **Depends on:** nothing new.

---

## Next (1–2 quarters)

### 7. Saved views + custom dashboards
- **What:** Let users save filter/date/store combinations as named views, and
  compose a personal dashboard from existing panels. Today every page is a fixed
  layout; role defaults come from the role experience work (`services/role_experience.py`),
  which is the right starting grid to make user-editable.
- **Wins:** retention — saved views are the classic switching-cost feature: the
  tenth saved view is the moment a user can't leave cheaply.
- **Effort:** M. **Depends on:** none hard; benefits from onboarding wizard (1).

### 8. Certified real provider integrations — payments, POS, e-invoicing
- **What:** The frameworks shipped honest: `services/payments.py` (Telr/PayTabs
  recognised, migration 069), `services/pos_connectors.py` (migration 070), and
  `services/einvoicing.py` + the FTA clearance harness (`services/einvoice_clearance.py`,
  migration 071) all gate on `IMPLEMENTED_PROVIDERS` / `IMPLEMENTED_VENDORS` sets
  that currently contain only the mock. Each certification — sandbox credentials,
  conformance tests, then adding the provider to the set — is a discrete unlock.
- **Wins:** deals, directly — "do you support Telr / our POS / FTA e-invoicing" are
  yes/no questions on UAE procurement checklists. Every certified provider converts
  a catalog flag from `enforced_by: planned` into a sellable line item.
- **Effort:** M per provider (the frameworks absorbed the hard part).
  **Depends on:** provider sandbox accounts + accreditation
  (see `EINVOICING_ACCREDITATION.md`) — external, start the paperwork now.

### 9. Mobile PWA for store managers
- **What:** Store managers live on the floor, not at desks — the role blueprints in
  `ROLE_EXPERIENCE_BLUEPRINT.md` already specify device context per role. Ship the
  Next.js app as an installable PWA with an offline-tolerant, store-scoped subset:
  today's numbers, alerts, approvals.
- **Wins:** deals — "works on the floor" demos exceptionally well to multi-store
  buyers; also lifts DAU for the seats that renew the contract.
- **Effort:** M. **Depends on:** saved views (7) helps but isn't required.

### 10. Report builder
- **What:** Reports and exports exist as fixed endpoints (`routes/reports.py`,
  gated by the `modules.reports` catalog flag). Add a builder: pick metrics/dimensions/
  filters from the governed set (`sales_fact_view` and the metric views of
  migrations 050/061 — units vs AED conventions enforced by construction), save,
  schedule, deliver via the digest pipeline (2).
- **Wins:** retention — scheduled reports embed the product in a customer's weekly
  operating rhythm; ripping it out then means changing how their meetings run.
- **Effort:** M–L. **Depends on:** digests (2) for delivery.

### 11. Per-tenant SMTP + white-label domains
- **What:** Outbound email today uses one global SMTP config (`security_notify.py`);
  branding is centralized but single-product (`frontend/src/lib/brand.ts`,
  `settings.product_name`). Let enterprise tenants bring their own SMTP identity and
  a custom domain, so digests and invites arrive from the retailer's own name.
- **Wins:** deals — a hard requirement in enterprise procurement, and table stakes
  for the reseller channel (16).
- **Effort:** M. **Depends on:** digests (2); interface catalog keys
  (`interface.*` — currently `enforced_by: planned`) getting real enforcement.

### 12. Prospect sandbox tenants with deterministic demo data
- **What:** The machinery exists: a demo tenant with DB-level synthetic-data
  confinement (migration 057), a deterministic seeded dataset date-shifted to look
  current (`services/db_seeder.py`), and a nightly reset (`services/demo_reset.py`).
  Productize it: one operator action (Platform Console) mints a time-boxed sandbox
  tenant per prospect, seeded, isolated, auto-expiring via the tenant lifecycle
  (`services/tenant_lifecycle.py`).
- **Wins:** deals — prospects explore alone before talking to sales, and every
  sandbox is a lead with observable behaviour.
- **Effort:** S–M. **Depends on:** Platform Console ops actions.

### 13. Public status page + published SLAs
- **What:** Health infrastructure exists (`services/health_checks.py`,
  `docs/runbooks/UPTIME_MONITORING_AND_ALERTING.md`); publish it — a public status
  page with component states and incident history. Publish SLAs only after the
  single-worker topology is fixed: the load-test baseline
  (`docs/production/LOAD_TEST_BASELINE.md`) found the API runs one uvicorn worker
  with in-process singletons, and `docs/production/KNOWN_LIMITATIONS.md` is explicit
  that current RPO/RTO are targets, not contract. Don't publish an SLA the topology
  can't back.
- **Wins:** deals — security/IT reviews ask for it by name; honesty here is itself
  a differentiator.
- **Effort:** S (page) / L (the HA work behind a real SLA).
  **Depends on:** multi-worker scale-out (the baseline's named blocker).

---

## Later (2+ quarters)

### 14. Embedded-analytics SDK
- **What:** The per-tenant public API with `lsk_` keys and an embeddable AI assistant
  already exist (`routes/public_api.py`, `docs/PUBLIC_API.md`, B4/B5) under a
  versioned contract (`docs/api/VERSIONING.md`). Grow that into an SDK: embeddable
  KPI/chart components a retailer can drop into their own intranet or supplier
  portal, on the same keys and version rules.
- **Wins:** retention at platform depth — embedded surfaces make Retail Intelligence
  infrastructure rather than a tab; also opens per-seat expansion revenue.
- **Effort:** L. **Depends on:** report builder (10) for the component inventory.

### 15. SOC 2 / ISO 27001 posture
- **What:** `docs/production/KNOWN_LIMITATIONS.md` currently (correctly) claims no
  certification.
  Much of the evidence base exists: audited security events
  (`services/security_events.py`), a CI-rehearsed backup restore drill, RLS
  isolation (migrations 010–012), key rotation (`services/jwt_keys.py`), SSO/SCIM
  (migrations 051–052). The work is the formal program: policies, evidence
  collection, an auditor, and closing whatever the gap assessment finds.
- **Wins:** deals — unblocks the enterprise segment where "SOC 2 report?" is a
  gate, not a preference.
- **Effort:** L (and calendar-bound). **Depends on:** status page (13) helps;
  mostly external.

### 16. Partner / reseller portal
- **What:** A portal for implementation partners to provision and support their own
  client tenants — a scoped, partner-facing slice of what the Platform Console does
  internally, built on the same fail-closed boundary discipline
  (`services/platform_access.py` is the pattern: explicit grant, never role-implied).
- **Wins:** deals — resellers are the realistic path to GCC retailers the team
  can't reach directly.
- **Effort:** L. **Depends on:** config export/clone (4), white-label (11),
  sandbox tenants (12).

### 17. Multi-region data residency beyond UAE
- **What:** UAE residency shipped as a deliberate single-region posture
  (`services/data_residency.py`, E5-3; `docs/runbooks/DATA_RESIDENCY.md`). Expanding
  to KSA (a plausible next market with its own residency law) means region-pinned
  deployments and region-aware provisioning — infrastructure, not a flag.
- **Wins:** deals in new geographies; irrelevant until sales actually points there,
  which is why it's Later despite being frequently asked about.
- **Effort:** L. **Depends on:** SLA-grade topology (13), provisioning maturity.

---

## What this roadmap deliberately does not include

- **Building money movement ourselves** — payments stay gateway-embedded
  (`SAAS_PATH.md` §8's rule stands).
- **Autonomous AI actions** — the assistant remains read-only with human-approved
  drafts (`services/action_drafting.py`); that constraint is a trust feature.
- **Anything the catalog would have to lie about** — a feature ships when its
  `enforced_by` names real code, not before (`PLATFORM_CONSOLE.md` §3.1).
