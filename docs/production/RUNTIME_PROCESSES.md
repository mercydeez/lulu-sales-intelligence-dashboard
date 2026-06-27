# Runtime Processes

In production the **API serves API only**. One-shot and background work runs in
dedicated processes. Source of truth: `backend/app/main.py` (gated lifespan),
`backend/app/commands/*`, and `docker-compose.production.yml`.

## Process map

| Process | Command | Cardinality | When |
|---------|---------|-------------|------|
| **migrate** (one-shot) | `python -m app.commands.migrate` | exactly 1 per release | before API/worker start |
| **API** | `uvicorn app.main:app` | N replicas | always |
| **worker** | (worker image) | 1+ | always |
| **generator** (demo) | `python -m app.commands.generator` | 1 | **only** demo deployments |
| **cache_warmer** | `python -m app.commands.cache_warmer` | 1 (or per-API-instance) | optional |
| **forecast_trainer** | `python -m app.commands.forecast_trainer` | 1 | optional |
| **seed** (demo) | `python -m app.commands.seed` | one-shot | demo only |

In the compose topology, `cache_warmer` and `forecast_trainer` still run inside the
API lifespan by default (per-instance cache, harmless). They can be split into
dedicated workers via their command modules on larger deployments.

## What the API lifespan does, by flag

`main.py` gates every startup task. In a real production config (DEMO_MODE off) the
log shows:

```
Startup seed skipped (RUN_SEED_ON_STARTUP=false) — run `python -m app.commands.seed`
Startup migrations skipped (RUN_MIGRATIONS_ON_STARTUP=false) — run the migrate job
Data generator NOT started (demo/live-generator disabled)
```

| Lifespan step | Gate | Prod (DEMO off) | Dev / DEMO box |
|---------------|------|-----------------|----------------|
| Seed synthetic data | `RUN_SEED_ON_STARTUP` | skipped | runs |
| Apply migrations | `RUN_MIGRATIONS_ON_STARTUP` | skipped (migrate job) | runs |
| Employee seeder | `RUN_EMPLOYEE_SEEDER_ON_STARTUP` | skipped | runs |
| Synthetic generator | `DEMO_MODE && LIVE_GENERATOR_ENABLED` | not started | started |
| Cache warmer | `RUN_CACHE_WARMER` | started (per-instance) | started |
| Forecast trainer | `RUN_FORECAST_TRAINER` | started | started |

The validator (`validate_security`) **refuses to boot** if `RUN_MIGRATIONS_ON_STARTUP`
or `RUN_SEED_ON_STARTUP` is forced on in a non-demo production — so you cannot
accidentally re-couple them to the API.

## Command behavior

- All commands log clearly and **exit non-zero on failure** (orchestrator gating).
- `seed` refuses (exit 2) unless `DEMO_MODE` or `SAMPLE_DATA_ENABLED`.
- `generator` refuses (exit 2) unless `DEMO_MODE` **and** `LIVE_GENERATOR_ENABLED`.
- `cache_warmer` / `forecast_trainer` refuse (exit 2) if their flag is off.
- On shutdown, only tasks that were actually started are cancelled; `close_db()`
  disposes both the owner engine and the RLS engine.

## Startup ordering (compose)

```
postgres (healthy) ─┐
redis    (healthy) ─┼─► migrate (completes) ─► backend (N) ─► frontend ─► nginx
                    └────────────────────────► worker
                                               generator (profile: demo)
```

`backend`, `worker`, and `generator` declare
`depends_on: migrate { condition: service_completed_successfully }`.
