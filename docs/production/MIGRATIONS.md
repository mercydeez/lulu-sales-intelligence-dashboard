# Database Migrations

## Model

- Migrations are ordered SQL files in `database/migrations/00*.sql` … `0NN.sql`,
  applied by `app.services.migration_runner.run_migrations` (idempotent; tracks
  applied files).
- **Base schema bootstrap:** on a fresh Docker volume, `database/init.sql` creates
  the base schema (and, in demo, seeds data + demo users). On managed Postgres
  where `init.sql` cannot run, the portable `run_seed` path (demo) creates the base
  schema. Incremental migrations layer on top.
- `backend/alembic/` is present but unused. There is no Alembic.

## Production: migrations run in a dedicated job

The API no longer applies migrations on startup in production. The `migrate`
service runs once per release and the API/worker gate on its completion:

```bash
docker compose -f docker-compose.production.yml --env-file .env.production run --rm migrate
# or as part of `up -d` — backend depends_on migrate (service_completed_successfully)
```

`validate_security()` refuses to boot the API if `RUN_MIGRATIONS_ON_STARTUP=true`
in a non-demo production environment.

## Adding a migration

1. Create the next-numbered file: `database/migrations/0NN_short_name.sql`.
2. **Additive and idempotent** — prefer `ADD COLUMN IF NOT EXISTS`,
   `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`. Avoid destructive
   `DROP`/`ALTER ... TYPE` without a backfill + rollback plan.
3. Keep RLS intact: new tenant-scoped tables need a `tenant_id` column + an RLS
   policy consistent with migrations 010–012, 020–021, 026.
4. Test on a fresh DB **and** an existing DB (CI does both — Phase 13).

## Rollback

SQL migrations are forward-only. To roll back, see
[`ROLLBACK.md`](ROLLBACK.md): redeploy the previous image, and if a migration
must be reversed, write a new compensating forward migration (preferred) or
restore from backup ([`BACKUP_RESTORE.md`](BACKUP_RESTORE.md)).

## Current state

Migrations `001` … `035` exist. This program adds `036` (auth lifecycle) and
`037` (data-source per-tenant active index) in later phases.
