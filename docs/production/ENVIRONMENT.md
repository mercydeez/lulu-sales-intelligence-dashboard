# Environment & Production Modes

How Retail IQ resolves configuration, and the fail-closed rules that protect production. Source of truth: `backend/app/config.py` (`Settings`, `_resolve_mode_defaults`, `validate_security`). Templates: [`.env.example`](../../.env.example) (dev) and [`.env.production.example`](../../.env.production.example) (prod).

## How flag resolution works

Operational and demo toggles are **"auto"** (`Optional[bool] = None`). When unset they resolve by environment:

| Environment | Auto behaviour |
|-------------|----------------|
| `development`, `testing` | Convenience **on** — demo data, live generator, on-startup migrate/seed, docs, demo users. |
| `production`, `staging` | Safe **off** — no demo data, no generator, no on-startup migrate/seed, docs hidden, demo users disabled. |

Set any env var explicitly (`true`/`false`) to override the auto default in either direction. `enable_external_ai` is the one exception: **off by default everywhere** — it must be opted into.

## Fail-closed rules (production / staging)

`validate_security()` runs at startup and **raises `RuntimeError`** (refusing to boot) on any of these. Warnings are logged but do not block.

| Rule | Result |
|------|--------|
| Default/weak `JWT_SECRET_KEY` or `SECRET_KEY`, or `<32` chars | raise |
| `salespass` (default) in `DATABASE_URL` | raise |
| Wildcard `*` in `CORS_ORIGINS` | raise |
| `ALLOW_DEMO_USERS=true` | raise |
| `LIVE_GENERATOR_ENABLED=true` without `DEMO_MODE` | raise |
| `SAMPLE_DATA_ENABLED=true` without `DEMO_MODE` | raise |
| `RUN_MIGRATIONS_ON_STARTUP=true` (non-demo prod) | raise |
| `RUN_SEED_ON_STARTUP=true` (non-demo prod) | raise |
| `USE_RLS_ROLE=false` without `ALLOW_INSECURE_NO_RLS=true` | raise |
| Self-hosted Redis (`REDIS_SELF_HOSTED=true`) with no password in `REDIS_URL` | raise |
| Default/dev password in `RLS_/SAGE_/WORKER_DATABASE_URL` | raise |
| `EXPOSE_API_DOCS=true` | warn (protect it at the proxy) |
| `DEBUG=true` | warn |
| `ENABLE_EXTERNAL_AI=true` with no key | warn |

### The demo-in-production exception
A **demo** deployment can run in a prod-env single box (e.g. Render free tier) by setting `DEMO_MODE=true`. That permits on-startup migrate/seed and the live generator **on that one box** — but `ALLOW_DEMO_USERS` and the secret/RLS/Redis rules still apply. A real-tenant production deployment keeps `DEMO_MODE=false`.

### The dangerous override
`ALLOW_INSECURE_NO_RLS=true` lets production boot without the `app_rw` RLS role. Only app-layer tenant scoping protects you then. Do not use it with real multi-tenant data.

## Full flag reference

| Env var | Type | Dev default | Prod default | Purpose |
|---------|------|-------------|--------------|---------|
| `ENVIRONMENT` | str | `development` | — | `development`/`testing`/`staging`/`production` |
| `DEMO_MODE` | bool | true | false | Master switch for synthetic demo behaviour |
| `SAMPLE_DATA_ENABLED` | bool | true | =DEMO_MODE | Seed synthetic historical data |
| `LIVE_GENERATOR_ENABLED` | bool | true | =DEMO_MODE | Run the synthetic sale generator |
| `ALLOW_DEMO_USERS` | bool | true | false | Seed/permit demo logins |
| `RUN_MIGRATIONS_ON_STARTUP` | bool | true | =DEMO_MODE | API applies migrations at boot |
| `RUN_SEED_ON_STARTUP` | bool | true | =DEMO_MODE | API seeds at boot |
| `RUN_EMPLOYEE_SEEDER_ON_STARTUP` | bool | true | =DEMO_MODE | API runs employee seeder at boot |
| `RUN_CACHE_WARMER` | bool | true | true | Per-instance dashboard cache warming |
| `RUN_FORECAST_TRAINER` | bool | =`FORECAST_TRAINER_ENABLED` | same | Offline forecast training |
| `EXPOSE_API_DOCS` | bool | true | false | Serve `/docs`,`/redoc`,`/openapi.json` |
| `ENABLE_SIGNUP` | bool | true | true | Public self-signup |
| `ENABLE_PUBLIC_API` | bool | true | true | Per-tenant public REST API |
| `ENABLE_EXTERNAL_AI` | bool | false | false | Allow a 3rd-party LLM (opt-in only) |
| `ENABLE_LOCAL_AI` | bool | true | true | Local Ollama provider |
| `ENABLE_DATA_SOURCE_CONNECTORS` | bool | true | false | Arbitrary connector testing |
| `REQUIRE_EMAIL_VERIFICATION` | bool | false | true | Require verified email |
| `REQUIRE_MFA_FOR_ADMINS` | bool | false | false | Force 2FA for admin roles |
| `USE_RLS_ROLE` | bool | per `.env` | required | Connect as `app_rw` for FORCE-RLS |
| `RLS_DATABASE_URL` | str | optional | required | `app_rw` connection |
| `SAGE_DATABASE_URL` | str | optional | recommended | `sage_ro` connection |
| `WORKER_DATABASE_URL` | str | optional | recommended | `worker_rw` connection |
| `REDIS_SELF_HOSTED` | bool | false | set true if self-hosting | Forces a Redis password |
| `ALLOW_INSECURE_NO_RLS` | bool | false | false | Dangerous: boot prod without RLS |

> **Note (program state):** Phase 1 adds these flags + validation. The API lifespan begins honoring them in **Phase 2** (process split). Until Phase 2 lands, `docker-compose.production.yml` / `render.yaml` must set `USE_RLS_ROLE` (or `ALLOW_INSECURE_NO_RLS`) so the tightened validator does not block boot — handled in Phase 2.

## SSO / OIDC (E5-1a)

Enterprise OIDC login, OFF by default. Full setup + security model: [`../security/SSO.md`](../security/SSO.md).

| Variable | Type | Default | Notes |
|---|---|---|---|
| `SSO_ENABLED` | bool | false | Master switch for all SSO |
| `SSO_OIDC_ENABLED` | bool | false | Enable the OIDC login path (needs `SSO_ENABLED` too) |
| `SSO_STATE_TTL_SECONDS` | int | 600 | Single-use auth-state lifetime |
| `SSO_JWKS_CACHE_TTL_SECONDS` | int | 3600 | In-memory discovery/JWKS cache TTL |
| `SSO_REQUIRE_VERIFIED_EMAIL` | bool | true | Reject IdP emails not marked verified |
| `SSO_DEFAULT_ROLE` | str | analyst | JIT default; never an admin role |
| `SSO_TRUST_IDP_MFA_DEFAULT` | bool | false | Fail-closed: local admin MFA is not bypassed |
| `SSO_ALLOWED_REDIRECT_HOSTS` | str | "" | Comma-separated hosts a `return_to` may target |
| `SSO_MAX_RETURN_TO_LENGTH` | int | 500 | Max `return_to` length |
| `<client_secret_env>` | secret | — | Per-provider client secret; the env var **name** is stored in `tenant_sso_providers.client_secret_env`, the value only in the environment (e.g. `SSO_AZURE_CLIENT_SECRET`). **Never commit it.** |
