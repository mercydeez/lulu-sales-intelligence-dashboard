# Retail IQ — Post-Launch Monitoring

> What to watch after the pilot goes live, and where to look. Pairs with the
> incident runbooks in `docs/runbooks/` and the observability wiring from Phase 9.

## Health & availability

| Signal | Where | Healthy | Act when |
|--------|-------|---------|----------|
| Liveness | `GET /health/live` | 200, DB/Redis-independent | non-200 → restart loop; check process |
| Readiness | `GET /health/ready` | 200 (DB+Redis+migrations+config OK) | non-200 → pull from LB; see `DB_OUTAGE`/`REDIS_OUTAGE` |
| Deep | `GET /health/deep` | subsystems `healthy` | a subsystem degraded → its runbook |

## Golden signals (metrics endpoint, Phase 9)

- **Latency** — p50/p95/p99 per route. Watch `/api/kpis`, `/stream/*`, `/api/ai/ask`.
  Runbook: `HIGH_LATENCY.md`.
- **Errors** — 5xx rate and exception count by route. Runbook: `HIGH_ERROR_RATE.md`.
- **Traffic** — requests/min, SSE open connections. Sudden drop → `SSE_DEGRADED.md`.
- **Saturation** — DB connections/pool, Redis memory, worker queue depth.
  Runbooks: `DB_OUTAGE.md`, `REDIS_OUTAGE.md`, `WORKER_FAILURES.md`.

## Security & tenancy

- Watch `security_events` for spikes in `login_failed`, `api_key_invalid`,
  `permission_denied`, and any `token_tenant_mismatch` (**critical** — possible
  isolation breach → `SUSPECTED_DATA_LEAK.md`).
- Review audit events (`api_key_created/revoked`, `tenant_data_exported`,
  `data_request_filed`) for anomalies.
- Alert on any `enable_external_ai` flip in a real-data environment.

## Data pipeline

- Generator/seed should be **off** in a real-data pilot (`DEMO_MODE=false`).
- Migration drift: `pending_migrations()` should be empty (surfaced by readiness).
- Forecast trainer / cache warmer job success (Phase 2 dedicated processes).

## Backups

- Confirm scheduled backups succeed daily; verify one restore weekly in staging
  (`RESTORE_FROM_BACKUP.md`). Track against the documented RPO/RTO.

## First-week cadence

- Day 1: watch latency/errors hourly; confirm health stays green through a deploy.
- Week 1: daily review of security events + backup success; one runbook rehearsal.
- Ongoing: weekly restore test; monthly secret-rotation and dependency-scan review.
