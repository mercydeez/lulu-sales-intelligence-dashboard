# Observability

## Logs
- Structured JSON when `LOG_JSON=true` (one object per line): `timestamp`, `level`,
  `logger`, `request_id`, `message`, and — when the request is authenticated —
  `tenant_id` and `user_id` (numeric ids only; **never secrets**).
- `request_id` is minted (or reused from an inbound `X-Request-ID`) by
  `RequestIDMiddleware` and stamped on every log line via a contextvar.
- The global exception handler logs full tracebacks server-side and returns a safe
  generic message to clients (no internal detail leaks).

## Metrics
- `MetricsCollector` (`services/metrics.py`) records per request via
  `RequestIDMiddleware` (`start_request`/`end_request`): `http_requests_total`
  (by method/path/status), `http_request_duration_seconds`, and
  `http_requests_in_progress`. Paths are normalized (`/api/kpis/123` → `/api/kpis/:id`)
  so no ids leak.
- Domain counters via `metrics.incr(...)`: `auth_failures`, `rate_limit_hits`,
  `import_failures`, `ai_fallbacks`.
- Exposed at **`GET /api/monitoring/metrics`** (Prometheus text) — auth-gated.
  Per-process; scrape each replica for fleet totals. Contains no secrets/tenant data.

## Health
`/health/live`, `/health/ready`, `/health/deep` — see [`HEALTH_CHECKS.md`](HEALTH_CHECKS.md).
`/health/deep` reports generator mode, RLS state, table existence, and data freshness.

## Optional integrations (env-gated, no-op until set)
- `SENTRY_DSN` → error tracking (initialized in lifespan if the SDK is installed).
- `SECURITY_ALERT_*` / `NOTIFY_WEBHOOK_URL` → security + diagnostics notifications.
- OpenTelemetry is not wired by default; add it as a low-risk follow-up if a
  collector is available.

## What to watch
Request rate, 4xx/5xx ratio, p95 latency, DB pool saturation, Redis availability,
SSE client count, worker scan/measure freshness, AI fallback rate, auth-failure and
rate-limit spikes. Thresholds in [`ALERTS.md`](ALERTS.md).

## Security events
`security_events` (migration 030) records auth/RBAC/data-source/AI events with
tenant + actor + detail — the audit trail behind incident investigation.
