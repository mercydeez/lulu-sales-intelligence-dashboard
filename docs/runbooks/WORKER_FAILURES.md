# Runbook: Worker Failures

The diagnostics worker (Node + BullMQ) runs deterministic rules on a schedule and
writes `findings` the dashboard + Sage read.

**Symptom:** no new `findings`; stale diagnostics; `/health/deep` `worker_queue`
shows no activity.

## 1. Confirm
- `docker logs app_worker_prod --tail=100`.
- Check the worker connects via the least-privilege `worker_rw` role
  (`WORKER_DATABASE_URL`) and to Redis (`REDIS_URL` incl. password).
- `/health/deep` → `worker_queue` (BullMQ key count).

## 2. Common causes
- **Redis auth** — worker can't reach a password-protected Redis → fix `REDIS_URL`.
- **DB role/password** — `worker_rw` password mismatch → fix `WORKER_DB_PASSWORD`.
- **Gated on migrate** — worker `depends_on` the migrate job; a failed migration
  blocks it ([FAILED_MIGRATION](FAILED_MIGRATION.md)).
- **Crash loop** — inspect logs; restart `docker compose ... up -d worker`.

## 3. Recover
Restart the worker; confirm new `findings` appear and the queue drains.

## 4. After
Worker failures are non-customer-facing but degrade diagnostics; add a heartbeat
alert (no new scan in N minutes).
