# Health Checks

Three probes with distinct semantics, plus the legacy `/health`. Defined in
`backend/app/main.py`. None of them return secrets.

| Endpoint | Purpose | Dependencies | Codes |
|----------|---------|--------------|-------|
| `GET /health/live` | Liveness — process is up | **none** | always 200 |
| `GET /health/ready` | Readiness — can serve traffic | DB, Redis, migrations, config | 200 ready / 503 not_ready |
| `GET /health/deep` | Operator subsystem detail | DB, Redis, tables, mode | 200 (200/degraded) |
| `GET /health` | Legacy combined check (back-compat) | DB, Redis | 200 |

## `/health/live`
Returns `{"status":"alive"}`. No DB/Redis access — safe and cheap for
keep-warm pingers and liveness probes. **Use this for keep-warm**, not `/ready`,
so a pinger does not hammer the database.

## `/health/ready`
Returns `200` only when **all** of:
- `database` — `SELECT 1` succeeds
- `redis` — `PING` succeeds
- `migrations` — `current` (no pending migration files)
- `config` — `validate_security()` does not raise

Otherwise `503` with a per-check breakdown. Wire orchestrator readiness probes
and load-balancer health to this. Compose and `render.yaml` use `/health/ready`.

```json
{ "status": "ready",
  "checks": {"database":"ok","redis":"ok","migrations":"current","config":"ok"},
  "timestamp": "..." }
```

## `/health/deep`
Detailed, non-secret status for humans/dashboards:
- `database`, `redis`, `worker_queue` (BullMQ key count, best-effort)
- `migrations` (current or the list of pending files)
- `security_events_table`, `findings_table` existence
- `latest_stream_sale` (data freshness)
- `mode`: `demo_mode`, `live_generator_enabled`, `generator_running`,
  `use_rls_role`, `external_ai`, `local_ai`

Use it to answer "is the generator running? is RLS on? are migrations applied?
how fresh is the data?" during an incident — without shell access.

## Compose / probes
- Backend healthcheck: `curl -f http://localhost:8000/health/ready`.
- Render: `healthCheckPath: /health/ready`.
- A readiness `503` keeps a new replica out of rotation until DB + migrations are
  ready — preventing 5xx storms on deploy/restart.
