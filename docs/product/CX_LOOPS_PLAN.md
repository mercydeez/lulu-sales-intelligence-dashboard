# CX Loops Plan — closing the world-class-SaaS gap

> Companion to `SAAS_PATH.md` (demo→SaaS) and `../EXECUTION_BLUEPRINT_12M.md` (epics).
> Those cover product, tenancy, trust-infrastructure, and GTM. This doc covers the
> **five product loops** that world-class SaaS (Stripe, Linear, Intercom, Shopify,
> Datadog) treat as core product and our blueprint currently under-specifies:
> activation, measurement, trust-visibility, money, and feedback.
>
> Decision on GTM (July 2026): **concierge-led with a self-serve trial veneer.**
> Hypermarket chains don't credit-card their way in; the trial de-risks the sales
> call. So we optimize the buyer's first 10 minutes and the pilot's first week —
> not an anonymous signup funnel.

## The gap, cross-verified against the repo

| Loop | Have | Blueprint covers | Missing (this plan) |
|---|---|---|---|
| Activation | Onboarding checklist, CSV wizard, role engine | E9-7 trial, E1-3 xlsx | teaching empty-states, funnel *measurement* |
| Measurement | `sentry_dsn` config stub (unwired) | E9-7 *assumes* an instrumented funnel | the entire instrumentation substrate |
| Trust-visibility | /trust page, CI restore drills, signed webhooks | E0 ops, E10-6 SOC2 | status page, in-app changelog, published SLA |
| Money | plan_limits + usage_metering **backend-only** | E8a payments | usage meters UI, limit-hit upgrade moments, dunning |
| Feedback | Sage (differentiator) | — | NPS pulse, feedback widget, closing-the-loop |

## Telemetry architecture (Yash owns the client; Krishna the ingest)

**Principle: vendor-agnostic.** One typed `track()` API (`frontend/src/lib/telemetry.ts`);
adapters behind it. Call sites never change when the backend swaps.

- **Now:** PostHog **EU cloud** adapter, env-gated (`NEXT_PUBLIC_POSTHOG_KEY`; absent ⇒
  telemetry is a no-op — dev/demo unaffected). SDK is dynamically imported after first
  paint so it never costs LCP.
- **Later (self-host path, Krishna):** first-party ingest — `POST /api/telemetry/events`
  batch endpoint → Redis list buffer → background flush → **append-only, monthly-partitioned**
  `product_events` table (same partition discipline as E6-3 `sales_stream_raw`).
  Switching = one adapter file, zero call-site churn. PDPL story: events never leave
  the tenant's region.

**Scale rules (non-negotiable):**
1. Client batches events (≤20 or 5s) and flushes via `sendBeacon`/`fetch keepalive` —
   telemetry must never block a user interaction or a page unload.
2. No PII in event props — user *id* and tenant *id* only; names/emails stay out.
3. Ingest is fire-and-forget: client never retries more than once, server 202s
   immediately, verification happens async. Losing 1% of events is fine; adding
   1ms to the UI is not.
4. Sampling hook from day one (`TELEMETRY_SAMPLE_RATE`), so 10× tenants = config
   change, not incident.
5. Error reporting: window `error`/`unhandledrejection` forwarded through the same
   pipe now; `@sentry/nextjs` (client) + backend `sentry_dsn` (already in config.py,
   Krishna) when a DSN exists.

**Funnel to instrument first** (concierge GTM = pilot-week-one):
`login_succeeded → onboarding_step_done(step) → import_started → import_committed →
first_own_data_view → export_printed → sage_asked`. Time-to-first-insight =
`login_succeeded → first_own_data_view`.

## Owner handoffs

### Krishna (platform)
- **K1 — first-party telemetry ingest** (spec above). Effort ~3d. After PostHog
  validates which events matter.
- **K2 — status/uptime truth:** the E0-2 worker heartbeat + `/api/monitoring/ready`
  already exist; add a tiny public uptime endpoint (`GET /api/monitoring/public-status`,
  no auth, cached 60s in Redis: component states + 90-day uptime %). The frontend
  `/status` page currently binds to `/ready`+`/live`; swap to this when it exists. ~2d.
- **K3 — dunning:** invoice `overdue` state exists; add the reminder email sequence
  (D+3, D+10, D+17) via the existing notifications service + a `dunning_state` on
  invoices. ~2d.
- **K4 — wire backend Sentry:** `sentry_dsn` is already in config.py; init in main.py
  lifespan when set. ~0.5d.

### Atharva (AI/experience)
- **A1 — Sage-guided onboarding:** first-run Sage prompt per role ("Ask me what changed
  in your stores this week") wired to the role_experience configs; the concierge
  pilot's "wow" moment. ~3d.
- **A2 — insight digest:** weekly email/notification digest of top findings (uses
  existing findings + notifications infra) — retention loop for store managers who
  don't live in dashboards. ~1w, after E7-4.

### Yash (this sprint, frontend)
- Y1 telemetry substrate + funnel instrumentation ✅ (this sprint)
- Y2 usage meters + limit-hit upgrade moments on billing ✅
- Y3 what's-new changelog panel (Topbar) ✅
- Y4 public /status page (binds /ready + /live now, K2 later) ✅
- Y5 teaching empty-states on data-empty screens ✅
- Y6 NPS micro-pulse + feedback widget — next sprint (needs a tiny Krishna table or
  reuses notifications; decide at K1 time).

## Deliberately NOT doing (counter-brainstorm, so nobody re-litigates)
- **Feature flags service / A/B testing** — no statistical power below ~50 tenants;
  env flags in config.py suffice. Revisit at scale.
- **SCIM, data-residency tiers, SOC2 Type II** — blueprint already sequences these
  behind real enterprise demand (E5/E10). Building early is résumé-driven development.
- **Session replay** — PDPL-hostile on retail data screens; revisit self-hosted-only
  if support burden ever justifies it.
- **Third-party in-app tour SDKs** (Appcues/Pendo) — heavy, expensive, and our
  role_experience engine + checklist already carry this; Sage (A1) is the better bet.
