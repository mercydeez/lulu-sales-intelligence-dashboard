#!/usr/bin/env bash
#
# verify-backup.sh — sanity-check a PostgreSQL custom-format backup WITHOUT
# restoring it. Confirms the file exists, is non-empty, and is a readable
# pg_restore archive with a non-trivial table-of-contents.
#
# Usage:
#   ./scripts/verify-backup.sh <backup-file.dump>
# Exit: 0 valid, non-zero invalid.
#
set -euo pipefail

log() { printf '[verify] %s\n' "$*" >&2; }
die() { printf '[verify][ERROR] %s\n' "$*" >&2; exit 1; }

backup_file="${1:-}"
[ -n "$backup_file" ] || die "usage: verify-backup.sh <backup-file.dump>"
[ -f "$backup_file" ] || die "file not found: ${backup_file}"
[ -s "$backup_file" ] || die "file is empty: ${backup_file}"
command -v pg_restore >/dev/null 2>&1 || die "pg_restore not found on PATH"

log "inspecting archive table-of-contents: ${backup_file}"
if ! toc="$(pg_restore --list "$backup_file" 2>/dev/null)"; then
  die "not a valid pg_restore archive (custom format expected)"
fi

entries="$(printf '%s\n' "$toc" | grep -cvE '^\s*;|^\s*$' || true)"
if [ "${entries:-0}" -lt 1 ]; then
  die "archive contains no restorable entries"
fi

size="$(du -h "$backup_file" | cut -f1)"
log "OK — ${entries} archive entries, size ${size}"
printf 'valid: %s (%s entries, %s)\n' "$backup_file" "$entries" "$size"
