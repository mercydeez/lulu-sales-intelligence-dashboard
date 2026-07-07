# Telemetry setup — turning on product analytics

The instrumentation is already in the code (`frontend/src/lib/telemetry.ts` +
call sites across the app). It is **off until a key exists** — no key means
every `track()` is a silent no-op, so nothing changes in dev/demo. This doc is
the one-time switch to turn it on.

> Why a human step: creating the PostHog account is a signup under your
> identity, with a data-processing agreement and a decision to send product
> events to a third party. That's a founder call, not something automation
> should do for you. Everything on the code/infra side is already wired.

## 1. Create the PostHog project (~5 min)

1. Go to <https://eu.posthog.com> and sign up. **Use the EU cloud** — it keeps
   event data in-region, which is the clean PDPL story for UAE retail tenants.
2. Create a project (e.g. "Retail IQ").
3. Copy the **Project API Key** from *Project settings → Project API Key*. It
   starts with `phc_`. (This key is safe to expose in the browser — it's
   write-only; it is NOT the personal API key.)

## 2. Turn it on

### Local dev
Edit `frontend/.env.local` (already created, gitignored) — uncomment and paste:
```
NEXT_PUBLIC_POSTHOG_KEY=phc_your_key
NEXT_PUBLIC_POSTHOG_HOST=https://eu.i.posthog.com
```
Restart `npm run dev`. That's it.

### Production — Render
The frontend service already declares both keys in `render.yaml`. Set
`NEXT_PUBLIC_POSTHOG_KEY` in the Render dashboard (Environment tab) and trigger
a redeploy. **`NEXT_PUBLIC_*` values are inlined at build time**, so a redeploy
is required for the key to take effect — setting it without rebuilding does
nothing.

### Production — Docker Compose
`docker-compose.production.yml` reads the key from the host environment as both
a build arg and a runtime env. Set it and rebuild the frontend image:
```
export NEXT_PUBLIC_POSTHOG_KEY=phc_your_key
docker compose -f docker-compose.production.yml build frontend
docker compose -f docker-compose.production.yml up -d frontend
```

## 3. Verify it's live

1. Open the app, sign in, click around.
2. In PostHog → *Activity* (live events), you should see `login_succeeded`,
   `page_viewed`, `theme_changed`, etc. within a few seconds.
3. Build the activation funnel in PostHog from these events (in order):
   `login_succeeded → onboarding_step_clicked → import_cta_clicked →
   export_printed`. Time-to-first-value = `login_succeeded → export_printed`.

## What's already instrumented

Auth (`login_succeeded`, `login_2fa_succeeded`), navigation (`page_viewed`),
activation (`onboarding_step_clicked`, `import_cta_clicked`), value moments
(`export_printed`, `sage_nudge_clicked`), preferences (`theme_changed`,
`lang_changed`, `exec_mode_toggled`), commercial (`usage_meters_viewed`,
`upgrade_cta_clicked`), trust (`whats_new_opened`, `status_page_viewed`),
feedback (`feedback_submitted`, `nps_submitted`), and throttled `client_error`.
Add new events to the typed `TelemetryEvent` union — never pass free-form
strings at call sites.

## Guarantees (why this is safe to leave on)

- **No PII**: identity is user id + role only; names/emails never sent.
- **No autocapture, no session recording** — explicit events only, so the
  PDPL surface stays reviewable.
- **Never blocks the UI**: the SDK loads after first paint; events queue.
- **Sampling + error throttling** are built in, so 10× tenants is a config
  change, not an incident.

## Later: first-party ingest (Krishna, K1)

When we want events to never leave our own infra, the same `track()` interface
gets a first-party adapter (`POST /api/telemetry/events` → partitioned
`product_events` table). Call sites don't change — it's one adapter swap. See
`CX_LOOPS_PLAN.md`.
