#!/usr/bin/env bash
#
# backup-postgres.sh — timestamped, compressed PostgreSQL backup.
#
# POSIX/ash-safe: this runs under bash (CI) *and* busybox `sh` (the alpine
# backup sidecar invokes it as `sh backup-postgres.sh`). Avoid bashisms.
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
# Post-dump steps (all best-effort, gated, never fail the backup silently):
#   VERIFY_AFTER_BACKUP  (default: 1) — run verify-backup.sh on the fresh dump
#   BACKUP_S3_URL        (unset)      — offsite offload target, e.g.
#                                       s3://my-bucket/retailiq  (needs aws or rclone)
#   BACKUP_HEARTBEAT_URL (unset)      — pinged on success (dead-man's-switch / E0-2)
#
# Produces a custom-format dump (compressed, restorable with pg_restore):
#   $BACKUP_DIR/retailiq_<db>_<UTC-timestamp>.dump
# plus a machine-readable manifest the monitor can read:
#   $BACKUP_DIR/latest.json
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
VERIFY_AFTER_BACKUP="${VERIFY_AFTER_BACKUP:-1}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

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
size_h="$(du -h "$outfile" | cut -f1)"
size_b="$(wc -c < "$outfile" | tr -d ' ')"
log "backup complete: ${outfile} (${size_h})"

# ── Verify the fresh dump is a readable pg_restore archive (default on) ──
if [ "${VERIFY_AFTER_BACKUP}" = "1" ] && [ -x "${SCRIPT_DIR}/verify-backup.sh" ]; then
  if sh "${SCRIPT_DIR}/verify-backup.sh" "$outfile" >&2; then
    verified="true"
  else
    verified="false"
    log "WARNING: fresh dump failed verification — keeping the file for inspection"
  fi
elif [ "${VERIFY_AFTER_BACKUP}" = "1" ]; then
  # verify-backup.sh present but not executable (e.g. read-only mount) — call via sh
  if [ -f "${SCRIPT_DIR}/verify-backup.sh" ] && sh "${SCRIPT_DIR}/verify-backup.sh" "$outfile" >&2; then
    verified="true"
  else
    verified="unknown"
  fi
else
  verified="skipped"
fi

# ── sha256 for integrity tracking (best-effort) ──
sha256=""
if command -v sha256sum >/dev/null 2>&1; then
  sha256="$(sha256sum "$outfile" | cut -d' ' -f1)"
elif command -v shasum >/dev/null 2>&1; then
  sha256="$(shasum -a 256 "$outfile" | cut -d' ' -f1)"
fi

# ── Manifest the monitor / heartbeat can read (latest.json) ──
manifest="${BACKUP_DIR}/latest.json"
printf '{"file":"%s","database":"%s","timestamp_utc":"%s","size_bytes":%s,"sha256":"%s","verified":"%s"}\n' \
  "$(basename "$outfile")" "$PGDATABASE" "$timestamp" "${size_b:-0}" "$sha256" "$verified" \
  > "$manifest" 2>/dev/null || log "WARNING: could not write manifest ${manifest}"

# ── Optional offsite offload to object storage (aws-cli or rclone) ──
if [ -n "${BACKUP_S3_URL:-}" ]; then
  dest="${BACKUP_S3_URL%/}/$(basename "$outfile")"
  if command -v aws >/dev/null 2>&1; then
    log "offsite: aws s3 cp -> ${dest}"
    aws s3 cp "$outfile" "$dest" >&2 || log "WARNING: offsite upload failed (aws) — local copy retained"
    aws s3 cp "$manifest" "${BACKUP_S3_URL%/}/latest.json" >&2 || true
  elif command -v rclone >/dev/null 2>&1; then
    log "offsite: rclone copyto -> ${dest}"
    rclone copyto "$outfile" "$dest" >&2 || log "WARNING: offsite upload failed (rclone) — local copy retained"
  else
    log "WARNING: BACKUP_S3_URL set but neither aws nor rclone is installed — skipping offsite"
  fi
fi

# ── Retention prune (best-effort) ──
if [ "${RETENTION_DAYS}" != "0" ]; then
  log "pruning dumps older than ${RETENTION_DAYS} days in ${BACKUP_DIR}"
  find "$BACKUP_DIR" -type f -name 'retailiq_*.dump' -mtime "+${RETENTION_DAYS}" -print -delete >&2 || true
fi

# ── Dead-man's-switch heartbeat: only ping on a verified success (E0-2 hook) ──
if [ -n "${BACKUP_HEARTBEAT_URL:-}" ] && [ "$verified" != "false" ]; then
  if command -v curl >/dev/null 2>&1; then
    curl -fsS -m 15 "$BACKUP_HEARTBEAT_URL" >/dev/null 2>&1 || log "WARNING: heartbeat ping failed"
  elif command -v wget >/dev/null 2>&1; then
    wget -q -T 15 -O /dev/null "$BACKUP_HEARTBEAT_URL" 2>/dev/null || log "WARNING: heartbeat ping failed"
  fi
fi

# Emit the path on stdout for scripting/cron (must stay the LAST stdout line).
printf '%s\n' "$outfile"
