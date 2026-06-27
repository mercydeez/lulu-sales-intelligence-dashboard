# Runbook: Failed Migration

**Symptom:** the `migrate` job exits non-zero; deploy halts (backend `depends_on`
migrate `service_completed_successfully`); `/health/ready` shows `migrations: pending`.

## 1. Confirm
- `docker compose -f docker-compose.production.yml --env-file .env.production logs migrate`
  → find the failing `0NN_*.sql` and the Postgres error.
- The runner applies each file in a transaction and records it in
  `schema_migrations`; a failed file **rolled back** and was **not** recorded, so
  the DB is consistent up to the last good migration.

## 2. Triage
- **Bad SQL / type error:** fix the migration file. Because the failed file was not
  recorded, re-running `migrate` re-applies it. Keep migrations idempotent
  (`IF NOT EXISTS`, guarded `DO` blocks).
- **Partially-applied effects from a non-transactional statement** (rare — most DDL
  is transactional in Postgres): inspect, write a compensating forward migration.
- **Migration assumes data/schema not present:** check ordering vs. `init.sql`
  bootstrap (see [`../production/MIGRATIONS.md`](../production/MIGRATIONS.md)).

## 3. Recover
- Re-run the migrate job: `... run --rm migrate`.
- If the schema was corrupted by the change: restore the pre-release backup
  ([`RESTORE_FROM_BACKUP.md`](RESTORE_FROM_BACKUP.md)) and redeploy the previous
  image ([`../production/ROLLBACK.md`](../production/ROLLBACK.md)).

## 4. Prevent
- CI runs migrations against a **fresh** DB and an **existing** DB (Phase 13).
- Always take a backup immediately before running migrations.
- Additive-only migrations; review for idempotency.
