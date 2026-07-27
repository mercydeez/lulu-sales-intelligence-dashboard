# Runbook: Database Outage

**Symptom:** `/health/ready` returns 503 with `database: error`; 5xx spikes; logs
show asyncpg connection errors.

## 1. Confirm
- `curl -f https://<host>/health/ready` → check `checks.database`.
- `curl https://<host>/health/deep` → `checks.database`.
- From the host: `docker compose -f docker-compose.production.yml ps postgres` and
  `docker logs app_db_prod --tail=100`.

## 2. Triage
- **Container down / unhealthy:** `docker compose ... up -d postgres`; watch
  `pg_isready`. The backend readiness probe keeps replicas out of rotation until DB
  is back — no manual LB change needed.
- **Disk full:** free space (old WAL, logs); never delete `postgres_data`.
- **Connection exhaustion:** check pool errors in logs; restart the API to drop
  leaked connections; verify pool size.
- **Managed DB incident:** check the provider status page; failover if HA is
  configured.

## 3. Recover
- Once DB is healthy, `/health/ready` returns 200 and traffic resumes automatically.
- If data is corrupted/lost: [`RESTORE_FROM_BACKUP.md`](RESTORE_FROM_BACKUP.md).

## 4. Prevent
- Alerts on `/health/ready` 503 and DB connection-error rate.
- Daily backups + verified restores ([`../production/BACKUP_RESTORE.md`](../production/BACKUP_RESTORE.md)).
- Disk-usage alert at 80%.
