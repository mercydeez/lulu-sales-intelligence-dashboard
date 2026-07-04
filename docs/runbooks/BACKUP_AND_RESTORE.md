# Runbook: Backups & Disaster Recovery

Implements blueprint **E0-1** ("Automated Postgres backups + one rehearsed restore").
The audit flagged the absence of an automated backup/restore *test* as **disqualifying
for any real tenant**. This is closed: backups are automated, self-verified, offsite-capable,
and the restore path is proven on **every push** by a CI drill.

## Targets (pilot)
| Metric | Target | How it's met |
|---|---|---|
| **RPO** (max data loss) | ≤ 24h (≤ 1h once offsite + more frequent runs are on) | Nightly `pg_dump`; tighten `BACKUP_AT_UTC` cadence per tenant |
| **RTO** (time to restore) | < 30 min | Drill measures actual restore seconds and fails if over `RTO_BUDGET_SECONDS` |
| **Verified** | Every backup | `verify-backup.sh` runs post-dump; `latest.json` records `verified` |
| **Offsite** | Required for real tenants | `BACKUP_S3_URL` → object storage (a backup on the DB's own host is not DR) |
| **Restore tested** | Every push | CI `backup-restore-drill` job runs a real backup→restore→row-count+checksum check |

## The moving parts
| Piece | File | Role |
|---|---|---|
| Backup | `scripts/backup-postgres.sh` | Timestamped `-Fc` dump → verify → `latest.json` manifest → optional offsite → prune → optional heartbeat |
| Scheduler | `scripts/backup-scheduler.sh` | Dependency-free daily loop (busybox `sh`); runs one backup on start |
| Verify | `scripts/verify-backup.sh` | Confirms a dump is a readable `pg_restore` archive with entries |
| Restore | `scripts/restore-postgres.sh` | **Destructive** restore into a target DB, with prod guards |
| Drill | `scripts/drill-restore.sh` | **Non-destructive** rehearsed restore into a scratch DB + validation |
| Sidecar | `backup` service (both compose files) | Runs the scheduler; prod = always-on, dev = `--profile backup` |

## Automated backups (how it runs)
Production (`docker-compose.production.yml`) runs an always-on `backup` sidecar
(`postgres:15-alpine`, so `pg_dump` matches the server version). It:
1. Takes an immediate backup on start (proves the path at deploy time), then daily at
   `BACKUP_AT_UTC` (default `02:00` UTC).
2. Verifies each dump and writes `/backups/latest.json` (file, timestamp, size, sha256, verified).
3. If `BACKUP_S3_URL` is set, uploads the dump + `latest.json` to object storage (aws-cli/rclone).
4. Prunes local dumps older than `RETENTION_DAYS` (default 14).
5. If `BACKUP_HEARTBEAT_URL` is set, pings it **only on a verified success** (dead-man's-switch;
   wire this to the E0-2 monitor so a *missing* ping alerts).

### Config (env)
| Var | Default | Meaning |
|---|---|---|
| `BACKUP_AT_UTC` | `02:00` | Daily run time (UTC, HH:MM) |
| `BACKUP_ON_START` | `1` | Run one backup immediately on container start |
| `BACKUP_RETENTION_DAYS` | `14` | Prune local dumps older than this (`0` = keep all) |
| `BACKUP_S3_URL` | *(unset)* | Offsite target, e.g. `s3://acme-retailiq-backups/prod` |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_DEFAULT_REGION` | *(unset)* | Offsite creds |
| `BACKUP_HEARTBEAT_URL` | *(unset)* | Dead-man's-switch ping URL |

### Managed-Postgres note (Render / RDS / Cloud SQL)
On managed Postgres the provider's **automated daily snapshots are the offsite tier** — enable
them and note the retention. The `backup` sidecar is still valuable there for **on-demand** and
**pre-migration** dumps you control and can restore anywhere. On the free Render tier (no sidecar),
run `backup-postgres.sh` from any box with network access to the DB, or rely on managed snapshots.

## Manual backup (on demand / before a risky change)
```bash
PGHOST=localhost PGUSER=salesuser PGDATABASE=salesdb \
PGPASSWORD="$POSTGRES_PASSWORD" ./scripts/backup-postgres.sh
# -> writes backups/retailiq_salesdb_<ts>.dump and backups/latest.json
```
Against the running stack (exact server version via the DB container):
```bash
docker compose --profile backup run --rm backup /bin/sh /scripts/backup-postgres.sh
```

## Rehearsed restore drill (non-destructive — safe against prod)
The drill backs up the source, restores into a **scratch** DB, and asserts every table's row
count (plus a probe checksum) matches. It never writes to the source.
```bash
# Local, against the dev stack:
docker compose --profile backup run --rm \
  -e SOURCE_DB=salesdb -e SCRATCH_DB=retailiq_drill -e DRILL_SELF_SEED=0 \
  backup /bin/sh /scripts/drill-restore.sh
# Expected tail: "DRILL PASS: <N> tables verified, RTO=<s>s, dump=..."
```
CI runs this on every push (`backup-restore-drill` job) with `DRILL_SELF_SEED=1` against a fresh
Postgres, so the DR path can never silently rot. **Run a manual drill against the real pilot DB
once per quarter** and record the result in the log below.

## Real restore (DESTRUCTIVE) — see the dedicated runbook
For an actual recovery (overwrites the live DB), follow
[`RESTORE_FROM_BACKUP.md`](RESTORE_FROM_BACKUP.md).

## Monitoring
- Read `/backups/latest.json` — alert if `timestamp_utc` is older than ~26h or `verified != "true"`.
- Prefer the heartbeat dead-man's-switch (`BACKUP_HEARTBEAT_URL`): a *missing* ping pages you even
  if the whole sidecar is down. (E0-2 wires the alert side.)

## Quarterly drill log
| Date | DB | RTO actual | Rows verified | Result | Operator |
|---|---|---|---|---|---|
| _(pending first live pilot)_ | | | | | |
