#!/usr/bin/env bash
# Regenerate the canonical schema baseline (E6-2).
#
# The baseline is a faithful pg_dump of the schema that the CANONICAL build path
# (database/init.sql + the numbered database/migrations/*.sql, in order) produces.
# It is the "squash to a single baseline" artifact: Alembic's 0001 revision replays
# it so `alembic upgrade head` reproduces the full current schema on an empty
# database, and CI diffs a fresh build against it to catch drift (an edited prior
# migration, or a baseline left stale).
#
# It is GENERATED, never hand-edited. Run this after adding a numbered migration,
# then commit the updated database/baseline/schema_baseline.sql.
#
# IMPORTANT: it builds a THROWAWAY database from init.sql + migrations rather than
# dumping the long-running dev DB — a dev DB can silently drift from the canonical
# path (e.g. a view rebuilt out of order), which would bake drift into the baseline.
#
# Requires the docker stack's postgres to be reachable as the `sales_db` container
# (the same image CI uses: pgvector/pgvector:pg15). Pass a container name as $1.
set -euo pipefail

CONTAINER="${1:-sales_db}"
DB_USER="${POSTGRES_USER:-salesuser}"
BUILD_DB="schema_baseline_build"
OUT="database/baseline/schema_baseline.sql"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

normalize() {
  # Strip volatile pg_dump lines so the baseline diffs byte-stably:
  #   - `-- …` comments (pg_dump/server version + timestamps)
  #   - `\restrict` / `\unrestrict` (per-session random token)
  #   - collapse blank-line runs
  grep -vE '^--' | grep -vE '^\\(un)?restrict ' | cat -s
}

echo "Building a fresh canonical schema in '$BUILD_DB' (init.sql + migrate — same as CI)…"
docker exec "$CONTAINER" psql -U "$DB_USER" -d postgres -q \
  -c "DROP DATABASE IF EXISTS ${BUILD_DB};" -c "CREATE DATABASE ${BUILD_DB};"

echo "  applying database/init.sql…"
docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$BUILD_DB" -q -v ON_ERROR_STOP=1 < database/init.sql >/dev/null

echo "  applying numbered migrations via app.commands.migrate…"
docker compose run --rm -T -e RUN_MIGRATIONS_ON_STARTUP=false \
  -e DATABASE_URL="postgresql+asyncpg://${DB_USER}:salespass@postgres:5432/${BUILD_DB}" \
  backend python -m app.commands.migrate >/dev/null

echo "Dumping schema…"
docker exec "$CONTAINER" pg_dump -U "$DB_USER" -d "$BUILD_DB" \
  --schema-only --no-owner --no-privileges | normalize > "$OUT"

docker exec "$CONTAINER" psql -U "$DB_USER" -d postgres -q -c "DROP DATABASE IF EXISTS ${BUILD_DB};" >/dev/null

lines=$(wc -l < "$OUT" | tr -d ' ')
echo "Wrote $OUT ($lines lines). Review the diff and commit if intended."
