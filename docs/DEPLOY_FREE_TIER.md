# Deploying the lighthouse on free tiers (zero spend)

For the Phase-A lighthouse pilot: one real retailer, real data, **no cash
outlay**. Host-agnostic — it works anywhere that runs a container and injects a
port (Render, Railway, Fly, Cloud Run) with a managed Postgres beside it.

Every claim below was verified by booting the production image against a real
Postgres on a non-default port with Redis absent. Where something did not work,
it says so.

## What had to change to make this possible

Two hard blockers, both now fixed:

1. **The container listened on a port nobody routed to.** `CMD` hardcoded
   `--port 8000` in exec form. Managed hosts assign a port at boot and inject it
   as `$PORT`, routing only there — so the app would look perfectly healthy in
   its own logs while every external request 502'd. The `CMD` is now shell form
   and honours `${PORT:-8000}`; compose, which sets no `PORT`, is unaffected.

2. **Redis absence killed startup.** Every publisher and cache helper in
   `redis_client.py` is already written `if redis_client:` — a Redis-less runtime
   was always a supported state — but `init_redis()` itself raised, so the app
   could not boot at all without Redis. It now pings, degrades to
   `redis_client = None` on failure, and logs loudly. `/health` reports
   `redis: unhealthy` and an overall `degraded`, so a degraded deployment is
   visible rather than silent.

## Required configuration

The app **refuses to start in production** if these are wrong. That is deliberate
— each refusal below is a guard working, not a bug to route around.

| Variable | Why it is required |
|---|---|
| `DATABASE_URL` | Must **not** contain the default `salespass`. `validate_security()` raises: *"Database URL contains default credentials!"* |
| `JWT_SECRET_KEY`, `SECRET_KEY` | ≥32 chars, non-default, or startup raises |
| `USE_RLS_ROLE=true` | Mandatory in production. Postgres-enforced tenant isolation; the `ALLOW_INSECURE_NO_RLS` override was removed (ruling #2, 20 Jul 2026) |
| `RLS_DATABASE_URL` | The non-owner `app_rw` connection. If unset it is derived by swapping in `app_rw:app_rw_dev_pass` — a **dev** password that will not exist on managed Postgres, so **set this explicitly** |
| `ENVIRONMENT=production` | |
| `RUN_SEED_ON_STARTUP=false` | Production is for the retailer's own data; never load demo data into a pilot |
| `RUN_MIGRATIONS_ON_STARTUP` | `true` is fine for a single instance; use the dedicated migrate job if the host scales to more than one |

Database setup (once, on the managed Postgres):

```sql
-- the app's own login role (whatever the provider gives you is fine,
-- as long as the password is not the compose default)
-- plus the non-owner role that FORCE RLS is enforced through:
CREATE ROLE app_rw LOGIN PASSWORD '<strong-password>';
GRANT CONNECT ON DATABASE <db> TO app_rw;
GRANT USAGE ON SCHEMA public TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_rw;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_rw;
```

The application role needs full DML, not just `SELECT` — login itself writes
(`last_login_at`), and the flywheel outbox relay writes continuously. A
read-only role produces a confusing `500` on login with
`permission denied for table flywheel_outbox` in the logs.

## Redis: the honest recommendation — provision it

The degrade-instead-of-die change means a Redis **blip** no longer prevents boot.
It does **not** make "no Redis" a good posture for a pilot, for one specific
reason found while testing:

`SessionInvalidationMiddleware` **fails closed** by default. With no Redis it
cannot consult the logout blacklist, so it rejects every authenticated request
with *"This session is no longer valid"* — login returns 200 and the next call
returns 401. That is the safe behaviour (a revoked token must not be honoured
during an outage), and it is exactly what you want in production.

There is an escape hatch, `AUTH_FAIL_OPEN_ON_REDIS_DOWN=true`, which was verified
to make the full stack work Redis-less (login 200 → authenticated call 200). **It
trades away logout enforcement**: a token that has been logged out or revoked
will still be honoured. Acceptable for a throwaway demo; not for a pilot holding
a retailer's real customer data.

> **Recommendation:** use a free managed Redis tier (Upstash has one). It costs
> nothing, and it keeps the fail-closed security posture intact. Reserve
> `AUTH_FAIL_OPEN_ON_REDIS_DOWN` for local demos.

Note also that `/health` returns overall `degraded` when Redis is down. If the
host treats a non-200/`degraded` health check as a failed deploy, point its probe
at `/health/ready` or accept `degraded`.

## What is lost without Redis

Postgres remains the source of truth throughout, so **no financial or inventory
state is affected**. Disabled: live SSE streams, response caching, rate limiting,
and logout/blacklist enforcement (see above).

## Verified

Production image, real Postgres, `PORT=7777`, `REDIS_URL` pointed at a dead port:

- boots and serves on the injected port
- logs `Redis unavailable (...) — starting in DEGRADED mode`
- `/health` → `status=degraded database=healthy redis=unhealthy`
- with `AUTH_FAIL_OPEN_ON_REDIS_DOWN=true`: `login 200`,
  `GET /api/flywheel/data-trust 200 READY`

## Not covered here

Frontend hosting (point `NEXT_PUBLIC_API_URL` at the deployed backend), custom
domains/TLS (the platform terminates TLS; the bundled nginx tier is for the
self-hosted production compose, not for free-tier hosts), and backups — managed
Postgres free tiers vary, so confirm the provider's retention before a pilot
holds real data.
