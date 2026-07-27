# Runbook: High Error Rate

**Symptom:** 5xx ratio above threshold (Prometheus `retailiq`/`http_requests_total{status=~"5.."}`).

## 1. Confirm & scope
- `/health/ready` and `/health/deep` — is a dependency (DB/Redis) down?
- Filter JSON logs by `request_id`/`level=ERROR`; the global handler logs the full
  traceback server-side. Group by path to find the failing endpoint.

## 2. Common causes
- **DB/Redis outage** → [DB_OUTAGE](DB_OUTAGE.md) / [REDIS_OUTAGE](REDIS_OUTAGE.md).
- **Bad release** → roll back the image ([../production/ROLLBACK.md](../production/ROLLBACK.md)).
- **Pending migration after deploy** → [FAILED_MIGRATION](FAILED_MIGRATION.md).
- **A single tenant/endpoint** → consider a feature flag to disable the path.

## 3. Mitigate
- Roll back to the last good image if errors started at a deploy.
- If isolated to one feature, disable it via its flag ([../production/ENVIRONMENT.md](../production/ENVIRONMENT.md)).

## 4. After
Confirm 5xx returns to baseline; record the cause; add a regression test/alert.
