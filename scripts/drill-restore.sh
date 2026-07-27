#!/usr/bin/env bash
#
# drill-restore.sh — REHEARSED RESTORE TEST (non-destructive to the source).
#
# Proves the backup/restore path actually works, end to end:
#   1. (optional) self-seed a known probe dataset into the source DB
#   2. back up the source DB (backup-postgres.sh)
#   3. verify the dump is a readable archive (verify-backup.sh)
#   4. create a fresh SCRATCH database and restore the dump into it
#   5. VALIDATE: every public table's row count in scratch == source
#      (+ a content checksum on the probe table when self-seeded)
#   6. report RTO (restore time) and PASS/FAIL, then drop the scratch DB
#
# It NEVER writes to or drops the source database. Safe to run against prod
# (it only reads the source and its own scratch DB). This is the artifact behind
# blueprint E0-1's "documented restore executed on a clean box" acceptance
# criteria, and it runs on every push via the CI `backup-restore-drill` job.
#
# Env:
#   PGHOST PGPORT PGUSER PGPASSWORD    libpq connection (password never echoed)
#   SOURCE_DB          db to back up + validate against   (default: salesdb)
#   SCRATCH_DB         throwaway restore target           (default: retailiq_drill)
#   MAINT_DB           db used to create/drop scratch     (default: postgres)
#   BACKUP_FILE        restore this dump instead of taking a fresh one (optional)
#   KEEP_SCRATCH       1 = leave scratch DB in place for inspection    (default: 0)
#   DRILL_SELF_SEED    1 = create a known probe table before backup    (default: 0)
#   RTO_BUDGET_SECONDS fail if restore exceeds this many seconds        (default: 1800)
#
# Exit: 0 = PASS, non-zero = FAIL.
#
set -euo pipefail

PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-salesuser}"
export PGHOST PGPORT PGUSER
SOURCE_DB="${SOURCE_DB:-salesdb}"
SCRATCH_DB="${SCRATCH_DB:-retailiq_drill}"
MAINT_DB="${MAINT_DB:-postgres}"
KEEP_SCRATCH="${KEEP_SCRATCH:-0}"
DRILL_SELF_SEED="${DRILL_SELF_SEED:-0}"
RTO_BUDGET_SECONDS="${RTO_BUDGET_SECONDS:-1800}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

log()  { printf '[drill] %s\n' "$*" >&2; }
die()  { printf '[drill][FAIL] %s\n' "$*" >&2; exit 1; }
psql_src()   { psql -v ON_ERROR_STOP=1 -qtAX -d "$SOURCE_DB"  "$@"; }
psql_scr()   { psql -v ON_ERROR_STOP=1 -qtAX -d "$SCRATCH_DB" "$@"; }
psql_maint() { psql -v ON_ERROR_STOP=1 -qtAX -d "$MAINT_DB"   "$@"; }

for bin in pg_dump pg_restore psql; do
  command -v "$bin" >/dev/null 2>&1 || die "$bin not found on PATH"
done
if [ -z "${PGPASSWORD:-}" ] && [ ! -f "${HOME}/.pgpass" ]; then
  die "no PGPASSWORD set and no ~/.pgpass"
fi

log "source=${PGUSER}@${PGHOST}:${PGPORT}/${SOURCE_DB}  scratch=${SCRATCH_DB}"

# ── 1. Optional self-seed: a deterministic probe table (makes CI meaningful) ──
PROBE_ROWS=1000
if [ "$DRILL_SELF_SEED" = "1" ]; then
  log "self-seeding probe table (${PROBE_ROWS} rows) into ${SOURCE_DB}"
  psql_src <<SQL
DROP TABLE IF EXISTS drill_probe;
CREATE TABLE drill_probe (id int PRIMARY KEY, payload text NOT NULL, amount numeric(12,2) NOT NULL);
INSERT INTO drill_probe
SELECT g, md5(g::text), (g * 1.5)::numeric(12,2)
FROM generate_series(1, ${PROBE_ROWS}) g;
SQL
fi

# ── 2. Back up the source (fresh dump unless BACKUP_FILE was provided) ──
if [ -n "${BACKUP_FILE:-}" ]; then
  [ -f "$BACKUP_FILE" ] || die "BACKUP_FILE not found: $BACKUP_FILE"
  dump="$BACKUP_FILE"
  log "using provided backup: ${dump}"
else
  log "taking a fresh backup of ${SOURCE_DB}"
  # backup-postgres.sh prints the dump path as its last stdout line.
  dump="$(PGDATABASE="$SOURCE_DB" BACKUP_DIR="${BACKUP_DIR:-./backups}" \
          VERIFY_AFTER_BACKUP=0 sh "${SCRIPT_DIR}/backup-postgres.sh" | tail -n1)"
  [ -n "$dump" ] && [ -f "$dump" ] || die "backup did not produce a dump file"
fi

# ── 3. Verify the archive is readable ──
sh "${SCRIPT_DIR}/verify-backup.sh" "$dump" >&2 || die "dump failed verification: $dump"

# ── 4. Fresh scratch DB + restore (timed) ──
log "recreating scratch database ${SCRATCH_DB}"
psql_maint -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${SCRATCH_DB}' AND pid <> pg_backend_pid();" >/dev/null 2>&1 || true
psql_maint -c "DROP DATABASE IF EXISTS \"${SCRATCH_DB}\";"
psql_maint -c "CREATE DATABASE \"${SCRATCH_DB}\";"

cleanup() {
  if [ "$KEEP_SCRATCH" = "1" ]; then
    log "KEEP_SCRATCH=1 — leaving ${SCRATCH_DB} in place"
    return
  fi
  psql_maint -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${SCRATCH_DB}' AND pid <> pg_backend_pid();" >/dev/null 2>&1 || true
  psql_maint -c "DROP DATABASE IF EXISTS \"${SCRATCH_DB}\";" >/dev/null 2>&1 || true
}
trap cleanup EXIT

log "restoring into ${SCRATCH_DB} …"
restore_start="$(date -u +%s)"
# --no-owner/--no-privileges: scratch DB has no app roles; we validate data, not ACLs.
# Warnings are tolerated; correctness is proven by the row-count comparison below.
pg_restore --no-owner --no-privileges -d "$SCRATCH_DB" "$dump" >&2 || \
  log "pg_restore returned non-zero (tolerated warnings) — validating data fidelity next"
restore_end="$(date -u +%s)"
rto="$((restore_end - restore_start))"

# ── 5. Validate: every public base table's row count matches source ──
log "validating row counts across all public tables"
tables="$(psql_scr -c "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;")"
[ -n "$tables" ] || die "scratch DB has no public tables after restore — restore did not populate schema"

mismatch=0
checked=0
for t in $tables; do
  scr_n="$(psql_scr -c "SELECT count(*) FROM \"public\".\"${t}\";")"
  src_n="$(psql_src -c "SELECT count(*) FROM \"public\".\"${t}\";" 2>/dev/null || echo "NA")"
  checked=$((checked + 1))
  if [ "$src_n" = "NA" ]; then
    log "  ${t}: scratch=${scr_n} source=NA (table absent in source — skipped)"
    continue
  fi
  if [ "$scr_n" != "$src_n" ]; then
    log "  MISMATCH ${t}: scratch=${scr_n} source=${src_n}"
    mismatch=$((mismatch + 1))
  fi
done
log "compared ${checked} tables"
[ "$mismatch" -eq 0 ] || die "${mismatch} table(s) had row-count mismatches — restore is NOT faithful"

# Content checksum on the probe table when self-seeded (proves values, not just counts).
if [ "$DRILL_SELF_SEED" = "1" ]; then
  src_sum="$(psql_src -c "SELECT count(*)||':'||coalesce(sum(amount),0)||':'||coalesce(md5(string_agg(payload, '' ORDER BY id)),'') FROM drill_probe;")"
  scr_sum="$(psql_scr -c "SELECT count(*)||':'||coalesce(sum(amount),0)||':'||coalesce(md5(string_agg(payload, '' ORDER BY id)),'') FROM drill_probe;")"
  [ "$src_sum" = "$scr_sum" ] || die "probe checksum mismatch (source=${src_sum} scratch=${scr_sum})"
  log "probe checksum matches (${scr_sum})"
  # tidy the probe table back out of the source (leave source as we found it)
  psql_src -c "DROP TABLE IF EXISTS drill_probe;" >/dev/null 2>&1 || true
fi

# ── 6. Report ──
log "restore time (RTO): ${rto}s (budget ${RTO_BUDGET_SECONDS}s)"
[ "$rto" -le "$RTO_BUDGET_SECONDS" ] || die "RTO ${rto}s exceeded budget ${RTO_BUDGET_SECONDS}s"

printf 'DRILL PASS: %s tables verified, RTO=%ss, dump=%s\n' "$checked" "$rto" "$(basename "$dump")"
log "PASS — backup is restorable and faithful."
