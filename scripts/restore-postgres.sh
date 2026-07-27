#!/usr/bin/env bash
#
# restore-postgres.sh — DESTRUCTIVE restore of a PostgreSQL backup.
#
# This OVERWRITES the target database (pg_restore --clean --if-exists). It drops
# and recreates objects from the dump. There is no undo. Take a fresh backup of
# the current state first.
#
# Env (standard libpq vars; password never echoed):
#   PGHOST PGPORT PGUSER PGDATABASE PGPASSWORD
#   ENVIRONMENT (if "production"/"staging", an extra confirmation is required)
#
# Usage:
#   ./scripts/restore-postgres.sh <backup-file.dump>
#   # non-interactive (CI/drills):
#   CONFIRM_RESTORE=RESTORE ./scripts/restore-postgres.sh <file>
#   # restoring into a production target additionally requires:
#   CONFIRM_PRODUCTION=<db-name> ./scripts/restore-postgres.sh <file>
#
set -euo pipefail

PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-salesuser}"
PGDATABASE="${PGDATABASE:-salesdb}"
ENVIRONMENT="${ENVIRONMENT:-development}"

log() { printf '[restore] %s\n' "$*" >&2; }
die() { printf '[restore][ERROR] %s\n' "$*" >&2; exit 1; }

backup_file="${1:-}"
[ -n "$backup_file" ] || die "usage: restore-postgres.sh <backup-file.dump>"
[ -f "$backup_file" ] || die "backup file not found: ${backup_file}"
[ -s "$backup_file" ] || die "backup file is empty: ${backup_file}"
command -v pg_restore >/dev/null 2>&1 || die "pg_restore not found on PATH"

log "TARGET: ${PGUSER}@${PGHOST}:${PGPORT}/${PGDATABASE}  (ENVIRONMENT=${ENVIRONMENT})"
log "SOURCE: ${backup_file}"
log "This will OVERWRITE the target database. There is no undo."

# Primary confirmation (interactive or via CONFIRM_RESTORE=RESTORE).
if [ "${CONFIRM_RESTORE:-}" != "RESTORE" ]; then
  if [ -t 0 ]; then
    printf '[restore] Type RESTORE to proceed: ' >&2
    read -r answer
    [ "$answer" = "RESTORE" ] || die "aborted (confirmation mismatch)"
  else
    die "refusing non-interactive restore without CONFIRM_RESTORE=RESTORE"
  fi
fi

# Extra guard for production/staging targets: must name the DB explicitly.
case "$(printf '%s' "$ENVIRONMENT" | tr '[:upper:]' '[:lower:]')" in
  production|prod|staging)
    if [ "${CONFIRM_PRODUCTION:-}" != "$PGDATABASE" ]; then
      die "refusing to restore a ${ENVIRONMENT} target without CONFIRM_PRODUCTION=${PGDATABASE}"
    fi
    log "production restore explicitly confirmed for database '${PGDATABASE}'"
    ;;
esac

if [ -z "${PGPASSWORD:-}" ] && [ ! -f "${HOME}/.pgpass" ]; then
  die "no PGPASSWORD set and no ~/.pgpass — refusing to prompt for it"
fi

log "restoring… (pg_restore --clean --if-exists)"
# --single-transaction keeps the DB consistent: all-or-nothing.
if ! pg_restore --clean --if-exists --no-owner --single-transaction \
      -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" "$backup_file"; then
  die "pg_restore failed — the transaction was rolled back; database unchanged"
fi

log "restore complete into ${PGDATABASE}"
