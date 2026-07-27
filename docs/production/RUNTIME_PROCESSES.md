# Runtime Processes

The **API serves API only**. It runs under `gunicorn` with N `UvicornWorker`s;
every continuous background loop runs in ONE dedicated `singletons` container.
This is the E6-5 multi-worker fix — see [`LOAD_TEST_BASELINE.md`](LOAD_TEST_BASELINE.md)
for why (1 CPU of 12 used; throughput collapsed under load) and the measured
before/after. Source of truth: `backend/app/main.py`, `backend/app/commands/*`,
`backend/app/services/leader_lock.py`, `docker-compose*.yml`.

## Process map

| Process | Command | Cardinality | When |
|---|---|---|---|
| **migrate** (one-shot) | `python -m app.commands.migrate` | 1 per release | before API/singletons (prod) |
| **API** | `gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w N` | N workers | always |
| **singletons** | `python -m app.commands.singletons` | **exactly 1** (`replicas: 1`) | always |
| **worker** | (BullMQ diagnostics image) | 1+ | always |
| seed (demo) | `python -m app.commands.seed` | one-shot | demo only |

### Why the singletons container exists

`data_generator`, `demo_reset`, `cache_warmer`, `forecast_trainer` and
`partition_maintenance` each **must** run in exactly one process. They used to run
inside the API lifespan; under `gunicorn --workers N` that would run N of each — N
synthetic generators, N concurrent partition `DROP TABLE`s, N nightly demo wipes.
Moving them to one always-on container makes "exactly one" a **deployment fact**
(`replicas: 1`), not a runtime leader election that could silently fail over,
split-brain, or be invisible at 3am.

The generator and demo_reset self-gate on `DEMO_MODE` + `LIVE_GENERATOR_ENABLED`
(default false), so a real-production `singletons` container runs only the
maintenance loops and generates nothing. A demo deploy opts in by setting those.

The one background loop the API keeps is `import_scheduler` — safe across workers
because it claims work with `FOR UPDATE SKIP LOCKED`.

### Why gunicorn, not `uvicorn --workers`

uvicorn's multiprocess supervisor (0.27) does not restart a dead worker — an OOM'd
worker silently reduces capacity while `/health` still passes. gunicorn restarts
workers and recycles them (`--max-requests`). Worker count is set **per service**
in compose (`command:`), never in the Dockerfile CMD, so prod can't silently
inherit a value.

## Concurrent-boot safety (advisory lock)

Every booting process runs the ASGI lifespan, so N workers hit the startup DDL at
once — proven to crash 3 of 4 on a `duplicate key … pg_type` from concurrent
`CREATE TABLE`. All startup DDL (seed → migrate → employee → backfill) now runs
inside ONE **session-level** Postgres advisory lock (`leader_lock.startup_lock`):
one process applies, the rest block, then re-check their idempotent guards and
no-op. Session-scoped (not `_xact_`) because migration files embed literal
`COMMIT;` that releases a transaction lock mid-run; held on a dedicated non-pooled,
non-reapable connection. Migrations also `INSERT … ON CONFLICT DO NOTHING`.

## What the API lifespan does, by flag

| Lifespan step | Gate | Prod (DEMO off) | Dev / DEMO box |
|---|---|---|---|
| Seed synthetic data | `RUN_SEED_ON_STARTUP` | skipped | runs (under lock) |
| Apply migrations | `RUN_MIGRATIONS_ON_STARTUP` | skipped (migrate job) | runs (under lock) |
| Employee seeder | `RUN_EMPLOYEE_SEEDER_ON_STARTUP` | skipped | runs (under lock) |
| import_scheduler | `IMPORT_SCHEDULER_ENABLED` | started | started |
| **generator / demo_reset / cache_warmer / forecast_trainer / partition_maintenance** | — | **never (singletons container)** | **never (singletons container)** |

`validate_security` refuses to boot if `RUN_MIGRATIONS_ON_STARTUP` /
`RUN_SEED_ON_STARTUP` are forced on in a non-demo production, so you cannot
accidentally re-couple them to the API.

## Request-handling state is in Redis, not a worker's heap

With round-robin across N workers, per-process state diverges. Moved to Redis:
Sage conversation history + the `pending` clarification/readback
(`sage:context:<scoped-session>`); bulk-ingest job `state` (`ingest:job:*`); the
model-metrics warm dedup (a `SET NX` lease). Without this, a Sage follow-up on
another worker loses history and mishandles a clarification.

## Connection budget

The SQLAlchemy pool is per process. Sized to `db_pool_size=10 / db_max_overflow=10`
(from 20/30) so N workers stay under Postgres `max_connections`, raised to **200**
in production compose. Measured: 4 workers + singletons + worker peaked at
**89 / 100** in dev under the load test. Rule of thumb:
`(WEB_CONCURRENCY × engines-per-process × (pool+overflow)) + singletons + worker`
must fit `max_connections`; engines-per-process is 1, +1 if `USE_RLS_ROLE`, +1 if
`DATABASE_REPLICA_URL`.

## Command behavior

- All commands log clearly and **exit non-zero on failure** (orchestrator gating).
- `singletons` runs every flag-enabled loop, heartbeats to Redis
  (`health:worker:singletons`, surfaced in `/health/deep`, informational — does not
  gate API readiness), and stops cleanly on SIGTERM.
- `seed` refuses (exit 2) unless `DEMO_MODE` or `SAMPLE_DATA_ENABLED`.
- `generator` refuses (exit 2) unless `DEMO_MODE` **and** `LIVE_GENERATOR_ENABLED`.
- On API shutdown, only started tasks are cancelled; `close_db()` disposes the
  owner, RLS and replica engines.

## Startup ordering (compose)

```
postgres (healthy) ─┐
redis    (healthy) ─┼─► migrate (completes) ─► backend (N gunicorn workers) ─► frontend ─► nginx
                    ├────────────────────────► singletons (replicas: 1)
                    └────────────────────────► worker
```

`backend`, `singletons` and `worker` declare
`depends_on: migrate { condition: service_completed_successfully }`.

## Live verification

```bash
WEB_CONCURRENCY=4 docker compose -f docker-compose.yml up -d   # base only, no override
docker compose logs backend | grep "Booting worker"           # 4 lines
docker ps --filter name=singletons | wc -l                    # 1
docker logs sales_singletons | grep "running .* loop"         # all five
# generator NOT multiplied: ~4-12 rows / 60s, not 4x:
docker exec sales_db psql -U salesuser -d salesdb -tAc \
  "SELECT count(*) FROM sales_stream_raw WHERE created_at > now() - interval '60 seconds'"
# Sage multi-turn survives worker hops: N turns to one session_id, then
#   GET /api/ai/chat/summary/<sid> — message_count reflects all turns
docker compose logs backend | grep startup_lock              # serialized, no dup-key crash
```

Everyday dev (`docker compose up -d`, base + override) still runs single-worker
`uvicorn --reload` for hot reload; the singletons container runs regardless, so the
demo still gets live sales.
