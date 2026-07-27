# Database Migrations

## Model

- Migrations are ordered SQL files in `database/migrations/00*.sql` … `0NN.sql`,
  applied by `app.services.migration_runner.run_migrations` (idempotent; tracks
  applied files). This remains the **authoring** path — new schema changes are
  still written as the next-numbered SQL file.
- **Base schema bootstrap:** on a fresh Docker volume, `database/init.sql` creates
  the base schema (and, in demo, seeds data + demo users). On managed Postgres
  where `init.sql` cannot run, the portable `run_seed` path (demo) creates the base
  schema. Incremental migrations layer on top.

## Alembic (E6-2)

Alembic is adopted as the **single-command entry point** and the **drift guard**,
without ripping out the working numbered-SQL system:

- `backend/alembic/` holds the config (`alembic.ini`, `env.py`) and one baseline
  revision, `0001_baseline`. `env.py` sources the URL from app settings (no secret
  in the ini) and uses the **sync psycopg2** driver (the app runtime stays on
  asyncpg); it targets `Base.metadata` so future revisions can autogenerate.
- **The squash:** `database/baseline/schema_baseline.sql` is a faithful, GENERATED
  `pg_dump` of the schema that `init.sql + database/migrations/*.sql` produce. The
  `0001_baseline` revision replays it, so on an **empty** database
  `alembic upgrade head` reproduces the entire current schema (verified: identical
  table/view/function/trigger/policy counts to the canonical build, plus Alembic's
  own `alembic_version` table).
- The baseline is **generated, never hand-edited**. After adding a numbered
  migration, run `./scripts/regenerate-schema-baseline.sh` and commit the updated
  `schema_baseline.sql`.
- **CI drift guard** (the `migrations` job): dumps the canonical schema and diffs
  it against the committed baseline — a stale baseline or an edited prior migration
  fails the build — then proves `alembic upgrade head` on an empty DB reproduces
  the same schema.

### Existing databases

An already-migrated DB (built by the numbered runner) becomes Alembic-aware once,
without re-running anything, by stamping the baseline:

```bash
cd backend && python -m alembic stamp 0001_baseline
```

### Remaining cutover (team-coordinated, deferred)

Deleting `init.sql` + the 57 numbered files and moving **all** authoring to
Alembic revisions is the final step. It rewrites everyone's migration workflow and
must be scheduled with the team (it is intentionally NOT done here so in-flight
numbered migrations keep working). The baseline + drift guard make that cutover
mechanical when the team is ready.

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

Numbered migrations `001` … `057` exist (contiguous). The Alembic baseline
(`0001_baseline`) squashes all of them; the next numbered migration is `058`.
After adding it, regenerate the baseline (see above).
