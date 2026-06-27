# Deployment (self-hosted, docker-compose)

The reference production topology is `docker-compose.production.yml`. For the
hosted demo on Render see [`RENDER_DEMO_DEPLOY.md`](RENDER_DEMO_DEPLOY.md); for a
real customer pilot see [`PILOT_DEPLOYMENT.md`](PILOT_DEPLOYMENT.md).

## 1. Prerequisites

- Docker + Docker Compose v2.
- A DNS name and TLS certs in `nginx/ssl/` (the `nginx` service terminates TLS).
- Strong secrets. The API **refuses to boot** on insecure config — see
  [`ENVIRONMENT.md`](ENVIRONMENT.md).

## 2. Configure

```bash
cp .env.production.example .env.production
# Fill in EVERY <...> value. Required (compose fails fast if missing):
#   POSTGRES_PASSWORD, JWT_SECRET_KEY, SECRET_KEY, REDIS_PASSWORD,
#   WORKER_DB_PASSWORD, CORS_ORIGINS
```

### Tenant isolation (RLS) — required for real multi-tenant data
Production runs the request path as the non-owner `app_rw` role so Postgres
FORCE-RLS enforces tenant isolation. Set:

```
USE_RLS_ROLE=true
RLS_DATABASE_URL=postgresql+asyncpg://app_rw:<strong-app_rw-pw>@postgres:5432/<db>
```

and ensure the DB role password matches:

```sql
ALTER ROLE app_rw WITH PASSWORD '<strong-app_rw-pw>';
```

> If `RLS_DATABASE_URL` is left empty the app derives a **dev-grade** app_rw
> password — acceptable only for throwaway environments. `ALLOW_INSECURE_NO_RLS=true`
> disables RLS entirely (app-layer scoping only) and must not be used with real
> multi-tenant data.

### Demo users
`init.sql` seeds demo logins on a fresh volume. Keep `ALLOW_DEMO_USERS=false`
(auth refuses demo logins) and rotate/remove those accounts before onboarding a
real tenant.

## 3. Deploy

```bash
EF=.env.production
# 1) one-shot migrate (also runs automatically via depends_on)
docker compose -f docker-compose.production.yml --env-file $EF run --rm migrate
# 2) bring up the stack (API serves API only; no generator)
docker compose -f docker-compose.production.yml --env-file $EF up -d
# 3) verify
curl -f https://<host>/health/ready
```

The synthetic generator is **not** started. To run a demo stack with synthetic
live data, add `--profile demo` and set `DEMO_MODE=true` (see RENDER_DEMO_DEPLOY).

## 4. Operate

- Health: `/health/live`, `/health/ready`, `/health/deep` (see [`HEALTH_CHECKS.md`](HEALTH_CHECKS.md)).
- Backups: [`BACKUP_RESTORE.md`](BACKUP_RESTORE.md). Rollback: [`ROLLBACK.md`](ROLLBACK.md).
- Runbooks: [`../runbooks/`](../runbooks/).

## 5. Pre-flight checklist
See [`READINESS_CHECKLIST.md`](READINESS_CHECKLIST.md). At minimum: strong secrets,
RLS on, demo users off, docs off, migrate job run, backups configured.
