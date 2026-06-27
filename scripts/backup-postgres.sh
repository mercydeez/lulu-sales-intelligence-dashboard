#!/usr/bin/env bash
#
# backup-postgres.sh — timestamped, compressed PostgreSQL backup.
#
# Env-driven (standard libpq vars; password is never echoed):
#   PGHOST     (default: localhost)
#   PGPORT     (default: 5432)
#   PGUSER     (default: salesuser)
#   PGDATABASE (default: salesdb)
#   PGPASSWORD (read from env or ~/.pgpass; never printed)
#   BACKUP_DIR (default: ./backups)
#   RETENTION_DAYS (default: 14; prune older dumps. 0 = keep all)
#
# Produces a custom-format dump (compressed, restorable with pg_restore):
#   $BACKUP_DIR/retailiq_<db>_<UTC-timestamp>.dump
#
# Usage:
#   PGPASSWORD=... ./scripts/backup-postgres.sh
#   # against the docker stack:
#   docker exec -e PGPASSWORD=$POSTGRES_PASSWORD app_db_prod \
#     pg_dump -Fc -U salesuser salesdb > backups/manual.dump
#
set -euo pipefail

PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-salesuser}"
PGDATABASE="${PGDATABASE:-salesdb}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

log()  { printf '[backup] %s\n' "$*" >&2; }
die()  { printf '[backup][ERROR] %s\n' "$*" >&2; exit 1; }

command -v pg_dump >/dev/null 2>&1 || die "pg_dump not found on PATH"

if [ -z "${PGPASSWORD:-}" ] && [ ! -f "${HOME}/.pgpass" ]; then
  die "no PGPASSWORD set and no ~/.pgpass — refusing to prompt interactively"
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR" 2>/dev/null || true

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
outfile="${BACKUP_DIR}/retailiq_${PGDATABASE}_${timestamp}.dump"

log "dumping ${PGUSER}@${PGHOST}:${PGPORT}/${PGDATABASE} -> ${outfile}"
# -Fc = custom (compressed) format; restorable with pg_restore.
if ! pg_dump -Fc -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" "$PGDATABASE" > "$outfile"; then
  rm -f "$outfile"
  die "pg_dump failed (partial file removed)"
fi

chmod 600 "$outfile" 2>/dev/null || true
size="$(du -h "$outfile" | cut -f1)"
log "backup complete: ${outfile} (${size})"

# Retention prune (best-effort).
if [ "${RETENTION_DAYS}" != "0" ]; then
  log "pruning dumps older than ${RETENTION_DAYS} days in ${BACKUP_DIR}"
  find "$BACKUP_DIR" -type f -name 'retailiq_*.dump' -mtime "+${RETENTION_DAYS}" -print -delete >&2 || true
fi

# Emit the path on stdout for scripting/cron.
printf '%s\n' "$outfile"
