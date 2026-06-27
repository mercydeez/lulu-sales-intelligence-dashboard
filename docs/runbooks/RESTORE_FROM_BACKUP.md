# Runbook: Restore From Backup

**Destructive.** Restoring overwrites the target database. Use only after data loss
or unrecoverable corruption, when forward fixes and image rollback are not enough.

## 0. Before you start
- Take a **fresh backup of the current (broken) state** for forensics:
  `./scripts/backup-postgres.sh` → keep it separately.
- Identify the backup to restore and verify it:
  `./scripts/verify-backup.sh ./backups/retailiq_salesdb_<ts>.dump`.
- Announce downtime; expect data written since the backup to be lost (RPO).

## 1. Stop writers
- Scale down / stop `backend`, `worker`, and (demo) `generator` so nothing writes
  during the restore:
  `docker compose -f docker-compose.production.yml stop backend worker generator`.

## 2. Restore
```bash
PGHOST=localhost PGUSER=salesuser PGDATABASE=salesdb \
PGPASSWORD="$POSTGRES_PASSWORD" ENVIRONMENT=production \
CONFIRM_RESTORE=RESTORE CONFIRM_PRODUCTION=salesdb \
./scripts/restore-postgres.sh ./backups/retailiq_salesdb_<ts>.dump
```
- Runs in a single transaction: a failure rolls back and leaves the DB unchanged.
- For a **drill**, restore into a scratch DB (`PGDATABASE=salesdb_drill`) instead.

## 3. Bring back up
- Run the `migrate` job (the backup may predate the latest schema):
  `... run --rm migrate`.
- Start services: `... up -d`.
- Verify: `/health/ready` 200; `/health/deep` row/freshness sane; spot-check a
  tenant's data and confirm tenant isolation still holds.

## 4. After
- Record: backup timestamp used, data-loss window (RPO actual), RTO actual.
- Re-enable writers/alerts; communicate resolution.
