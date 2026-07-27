# Backup & Restore

Tooling: [`scripts/backup-postgres.sh`](../../scripts/backup-postgres.sh),
[`scripts/restore-postgres.sh`](../../scripts/restore-postgres.sh),
[`scripts/verify-backup.sh`](../../scripts/verify-backup.sh). PostgreSQL is the
only stateful store that must be backed up — Redis holds cache/blacklist/rate-limit
state that is safe to lose (see [`../runbooks/REDIS_OUTAGE.md`](../runbooks/REDIS_OUTAGE.md)).

## Pilot RPO / RTO

| Objective | Target (pilot) |
|-----------|----------------|
| **RPO** (max data loss) | ≤ 24h with daily backups; ≤ 1h if WAL/managed PITR is enabled |
| **RTO** (max downtime to restore) | ≤ 1h for a single-DB restore on pilot data volumes |

Managed Postgres (Render/RDS/Cloud SQL) usually provides automated snapshots +
point-in-time recovery — prefer it. These scripts are for self-hosted compose and
for portable, off-provider copies.

## Backup

```bash
PGPASSWORD="$POSTGRES_PASSWORD" PGHOST=localhost PGUSER=salesuser PGDATABASE=salesdb \
BACKUP_DIR=./backups RETENTION_DAYS=14 ./scripts/backup-postgres.sh
```
- Custom-format (`-Fc`, compressed), timestamped `retailiq_<db>_<UTC>.dump`.
- Files are `chmod 600`; the password is never echoed.
- Prunes dumps older than `RETENTION_DAYS` (0 = keep all).

**Frequency / retention (pilot default):** daily backup, 14-day retention, plus a
manual backup immediately **before every release/migration**. Store at least one
copy off-host.

## Verify (do this routinely)

```bash
./scripts/verify-backup.sh ./backups/retailiq_salesdb_<ts>.dump
```
Confirms the archive is readable and non-trivial **without** restoring.

## Restore (destructive)

See [`../runbooks/RESTORE_FROM_BACKUP.md`](../runbooks/RESTORE_FROM_BACKUP.md).
`restore-postgres.sh` **overwrites** the target, requires `CONFIRM_RESTORE=RESTORE`
(or an interactive `RESTORE` prompt), and refuses a production/staging target unless
`CONFIRM_PRODUCTION=<db-name>` is also set. It runs in a single transaction, so a
failure rolls back and leaves the DB unchanged.

## Restore drill (quarterly)

1. `verify-backup.sh` the latest dump.
2. Restore it into a **scratch** database (`PGDATABASE=salesdb_drill`,
   `CONFIRM_RESTORE=RESTORE`).
3. Run `/health/ready` against an app pointed at the scratch DB; spot-check row
   counts and a tenant's data.
4. Record the drill date + RTO observed in the ops log.
