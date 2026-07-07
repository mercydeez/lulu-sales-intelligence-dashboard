# Runbook — Uptime Monitoring & Alerting (E0-2)

> Goal: a downtime alert reaches the founder phone in **< 5 minutes**, and
> `/health` honestly covers DB, Redis, and the worker heartbeat.

## 1. Health endpoints

| Endpoint | Purpose | Deps touched | Use for |
|---|---|---|---|
| `GET /health/live` | Liveness — process is up | **none** (cheap) | container/keep-warm pings |
| `GET /health` | Simple summary | DB, Redis, worker heartbeat | quick human/CI check |
| `GET /health/ready` | Readiness (200 or 503) | DB, Redis, migrations, config, worker (strict in prod) | **external uptime monitor + load balancer** |
| `GET /health/deep` | Full subsystem detail (no secrets) | all of the above + backup + alerting | operator triage |
| `POST /api/monitoring/alerts/test` | Send a **test** alert (admin/super_admin only) | webhook | prove founder-phone delivery |

`/health/deep` `checks` shape: `database`, `redis`, `migrations`, `worker_heartbeat`
(`ok`/`stale`/`missing`/`unknown` + `age_seconds`, `stale_after_seconds`), `backup`
(manifest freshness), `alerting` (`configured`/`missing`, provider — **never the URL**).

Status policy: **healthy** = DB + Redis + migrations + worker heartbeat all OK;
**degraded** = core serves but worker stale/missing, migrations pending, or backup/
alerting unconfigured; **unhealthy** = DB or Redis down.

## 2. Recommended external monitor (the <5-minute path)

The code **emits** alerts and **exposes** health; actual phone delivery is done by an
external provider you configure. Recommended setup:

1. Point an external uptime monitor (Better Stack, Healthchecks.io, UptimeRobot,
   PagerDuty, Pingdom) at `https://api.<domain>/health/ready`.
2. Poll every **60 seconds**; alert after **2 consecutive failures** (~2 min to page).
3. Route that monitor's alert to the founder **phone / SMS / WhatsApp / call**.
4. Optionally also set `ALERT_WEBHOOK_URL` so the backend itself pages on a failed
   readiness check (deduped) — belt-and-suspenders alongside the external monitor.

## 3. Required environment variables

```env
ALERT_ENABLED=true                 # master switch (default false)
ALERT_WEBHOOK_URL=<secret>         # provider webhook that routes to a phone — SECRET
ALERT_WEBHOOK_TIMEOUT_SECONDS=5
ALERT_MIN_SEVERITY=critical
ALERT_DEDUP_TTL_SECONDS=300        # suppress duplicate pages within 5 min
WORKER_HEARTBEAT_INTERVAL_MS=30000 # worker emits every 30s
WORKER_HEARTBEAT_STALE_SECONDS=120 # older than 2 min => "stale"
BACKUP_MANIFEST_PATH=/backups/latest.json
BACKUP_STALE_AFTER_HOURS=30
```

The webhook URL is a **secret** — never commit it and never expose it in an API
response (health payloads only report `alerting: {status, provider}`).

## 4. How to test alert delivery

1. Set `ALERT_ENABLED=true` and `ALERT_WEBHOOK_URL=<your provider hook>`; redeploy backend.
2. As an admin/super_admin, call:
   ```bash
   curl -X POST https://api.<domain>/api/monitoring/alerts/test \
        -H "Authorization: Bearer <admin JWT>"
   ```
   Response: `{"alerting":{"status":"configured","provider":"webhook"},"result":{"sent":true},...}`
   (never the URL). Confirm the alert lands on the founder phone. Capture a screenshot.
3. If `result.sent` is `false`, check `reason` (`disabled` → not enabled/no URL;
   `deduplicated` → sent recently; `webhook_error` → provider/timeout).

## 5. How to verify the worker heartbeat

```bash
curl -s https://api.<domain>/health/deep | jq '.checks.worker_heartbeat'
# expect: {"status":"ok","age_seconds": <~30>, "stale_after_seconds":120, ...}
```
Directly in Redis: `GET health:worker:diagnostics` (JSON with `timestamp`,
`last_scan_status`, `last_measure_status`). The worker writes it every
`WORKER_HEARTBEAT_INTERVAL_MS` and around each scan/measure.

## 6. Incident response

- **DB down** (`checks.database=error`, status `unhealthy`, `/health/ready`=503):
  check Postgres container/managed instance, connections, disk. See DEPLOYMENT.md.
- **Redis down** (`checks.redis=error`): check Redis container/instance and password;
  SSE + caching + dedup degrade. App fails open on auth per config.
- **Worker heartbeat stale/missing** (`worker_heartbeat=stale|missing`): the diagnostics
  worker isn't beating. `docker compose logs worker`; restart the worker service.
  Findings/measure loop is paused but the API still serves (status `degraded`).
- **Backup manifest stale** (`backup=stale`): E0-1 backups aren't running. See
  `docs/runbooks/BACKUP_AND_RESTORE.md` — do NOT fix backups from here.

## 7. Acceptance evidence checklist

- [ ] Screenshot/log of a **test alert delivered** to the founder phone (via `POST /alerts/test`).
- [ ] `/health/deep` output showing `worker_heartbeat.status = ok` with a small `age_seconds`.
- [ ] External monitor configured on `/health/ready`, 60s interval, **<5-minute** alert window, routed to phone.
- [ ] `/health/ready` returns 200 on the healthy stack and 503 when a core dep is stopped.

## 8. Honest limitation

This repo can **emit** a webhook alert and **expose** health status. Actual phone/SMS/
WhatsApp delivery depends entirely on the **external provider** the webhook is wired to
(Better Stack / Healthchecks.io / PagerDuty / Twilio / Slack). No phone number or
provider is hardcoded; wiring that provider is a deployment step, documented above.
