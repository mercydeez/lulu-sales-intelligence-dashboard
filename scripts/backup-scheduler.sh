#!/bin/sh
#
# backup-scheduler.sh — dependency-free daily backup loop for the backup sidecar.
#
# Runs `backup-postgres.sh` once per day at BACKUP_AT_UTC (HH:MM, UTC). No cron
# daemon needed: it polls every 30s and fires once when the wall clock reaches
# the target minute. Designed to run under busybox `sh` in postgres:15-alpine.
#
# Env (in addition to everything backup-postgres.sh reads):
#   BACKUP_AT_UTC    daily run time, HH:MM UTC        (default: 02:00)
#   BACKUP_ON_START  run one backup immediately (1/0) (default: 1)
#
# The immediate on-start backup proves the whole path works at deploy time
# instead of waiting until 02:00 to discover a broken credential or mount.
#
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
BACKUP_AT_UTC="${BACKUP_AT_UTC:-02:00}"
BACKUP_ON_START="${BACKUP_ON_START:-1}"

log() { printf '[scheduler] %s\n' "$*" >&2; }

run_backup() {
  log "starting backup run (target ${PGDATABASE:-salesdb})"
  if out="$(sh "${SCRIPT_DIR}/backup-postgres.sh")"; then
    log "backup OK -> ${out}"
  else
    log "ERROR: backup run FAILED (see [backup] lines above) — will retry at next window"
  fi
}

log "backup scheduler up — daily at ${BACKUP_AT_UTC} UTC (on-start=${BACKUP_ON_START})"

if [ "${BACKUP_ON_START}" = "1" ]; then
  run_backup
fi

last_run_day=""
while true; do
  now_hm="$(date -u +%H:%M)"
  today="$(date -u +%Y-%m-%d)"
  if [ "$now_hm" = "$BACKUP_AT_UTC" ] && [ "$today" != "$last_run_day" ]; then
    run_backup
    last_run_day="$today"
  fi
  sleep 30
done
