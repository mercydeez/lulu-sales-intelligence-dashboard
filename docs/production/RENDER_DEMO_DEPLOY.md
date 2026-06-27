# Render Demo Deploy

`render.yaml` is a **demo** blueprint: a single always-on box that seeds synthetic
data and runs the live generator so the dashboard shows live-looking activity. It
is explicitly **not** a real-tenant production deployment.

## What makes it a demo

The backend service sets:

| Env | Value | Why |
|-----|-------|-----|
| `ENVIRONMENT` | `production` | real security middleware, docs hidden, fail-fast secrets |
| `DEMO_MODE` | `true` | permits on-startup migrate/seed + the live generator on this one box |
| `ALLOW_DEMO_USERS` | `false` | demo logins stay disabled even here |
| `ALLOW_INSECURE_NO_RLS` | `true` | free-tier managed PG has no `app_rw` role; app-layer scoping only |
| `JWT_SECRET_KEY`, `SECRET_KEY` | `generateValue` | strong secrets from Render |
| `LOG_JSON` | `true` | structured logs |

Because `DEMO_MODE=true`, the single web service runs migrate + seed + generator in
its lifespan (there is no separate process on free tier). On a real deployment you
would instead use `docker-compose.production.yml` with `DEMO_MODE=false` and the
dedicated `migrate`/`worker` processes.

## Steps

1. Push to GitHub → Render → **New + → Blueprint** → pick the repo.
2. After first deploy, set the two `sync: false` values in the dashboard:
   - frontend `NEXT_PUBLIC_API_URL` → the backend's `https` URL
   - backend `CORS_ORIGINS` / `CSP_CONNECT_SRC` → the frontend's `https` URL
3. Redeploy so the frontend bakes in the API URL.
4. Keep the backend awake (free services sleep after ~15 min): add a pinger hitting
   `/health/live` (cheap, no DB) so the keep-warm does not hammer the database.

## Honesty

Everything shown is **synthetic demo data** (see
[`../product/DEMO_VS_REAL_DATA.md`](../product/DEMO_VS_REAL_DATA.md)). Do not present
a Render demo as real customer data. Free Postgres expires ~90 days after creation.
