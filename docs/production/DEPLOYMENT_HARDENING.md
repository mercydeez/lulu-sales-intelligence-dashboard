# Deployment Hardening & Scale Playbook

> Grounded audit of the running stack (2026-07) for cloud deployment, incoming
> traffic, and the deployment bugs that actually bite. Each item says what the
> code does today, the risk at scale, and the concrete action. Ordered by
> blast radius.

## TL;DR — the pre-deploy checklist (do these before any real traffic)

- [ ] **`TRUST_PROXY_HEADERS=true`** behind a cloud LB/nginx — or rate limiting
      treats every user as one IP (the exact bug that 429'd logins in Docker).
- [ ] **Real secrets**: `JWT_SECRET_KEY` + `SECRET_KEY` ≥ 32 chars, unique. The
      app *hard-fails* on defaults in prod (good) — set them or it won't boot.
- [ ] **`CORS_ORIGINS`** = your real frontend origin(s), no wildcard (enforced).
- [ ] **`NEXT_PUBLIC_API_URL`** = the browser-reachable API URL, set as a
      **build arg** (Next inlines it at build; changing it at runtime does
      nothing — redeploy the frontend image).
- [ ] **`RUN_MIGRATIONS_ON_STARTUP=false`** in prod; run migrations as a
      one-shot job (prod compose already has `app.commands.migrate`).
- [ ] Background singletons on **one** replica only (see §2).
- [ ] Postgres `max_connections` sized for `replicas × pool` (see §3).

## 1. Rate limiting behind a load balancer  🔴 highest-value

**Today:** `RateLimitMiddleware` is a Redis sliding window keyed on client IP.
`_get_client_ip` honors `X-Forwarded-For`/`X-Real-IP` **only when
`trust_proxy_headers=true`** (default `false` — a correct secure default, since
XFF is spoofable when you're *not* behind a trusted proxy).

**Risk:** In the cloud, all traffic arrives from the LB's IP. With
`trust_proxy_headers=false`, every user shares one bucket → one busy user
429's everyone, and logins fail. This is precisely what happened locally (Docker
gateway IP) and was worked around by raising the dev limit to 6000/min.

**Action:**
- Set `TRUST_PROXY_HEADERS=true` **and** ensure the LB strips/sets a trustworthy
  `X-Forwarded-For` (don't trust client-supplied XFF end-to-end).
- Keep the prod limit sane per *real* client (100–300/min is fine once IPs are
  per-user again).
- **Scale enhancement (later):** key the limiter on authenticated user id when a
  token is present, IP otherwise — so users behind one corporate NAT don't
  throttle each other. ~30 lines in the middleware; deferred (not a launch
  blocker once proxy headers are trusted).

## 2. Horizontal scaling — the API is stateless-ready ✅ (with one caveat)

**Today (good):** auth is JWT + Redis token blacklist (no server session
affinity); the rate limiter is in Redis; background tasks are each env-gated:
`RUN_CACHE_WARMER`, `RUN_FORECAST_TRAINER`, `RUN_MIGRATIONS_ON_STARTUP`, and the
demo generator (`DEMO_MODE` + `LIVE_GENERATOR_ENABLED`). So the API scales
horizontally behind a LB.

**Caveat:** those background singletons must run on **exactly one** place, or N
replicas duplicate the work (N cache-warmers, N trainers). The generator is
demo-only so it's off in prod already.

**Action — the leader pattern:**
- API replicas (scale freely): `RUN_CACHE_WARMER=false`, `RUN_FORECAST_TRAINER=false`.
- One dedicated instance (or the existing `worker`/a `jobs` service):
  runs the trainer + cache warmer. Migrations run as a separate job, not in any
  serving replica.
- Result: add replicas linearly with zero duplicate background work.

## 3. Database connections  🟠

**Today:** async SQLAlchemy engine `pool_size=20, max_overflow=30` (→ 50 conns
per process), `pool_pre_ping=true` (survives stale conns), `pool_recycle=1800`.
A separate RLS engine doubles this when `USE_RLS_ROLE` is on.

**Risk:** Postgres default `max_connections=100`. `replicas × 50` (× 2 with RLS)
blows past it fast — new connections error under load.

**Action:**
- Put **PgBouncer** (transaction pooling) in front of Postgres — the standard
  fix; lets many app processes share few DB connections.
- Or size Postgres `max_connections` and tune `pool_size` down per replica.
- On managed Postgres (RDS/Cloud SQL/Neon), use their pooler endpoint.

## 4. Concurrency / workers  🟠

**Today:** the backend image runs a **single** uvicorn process (`Dockerfile.backend`
CMD, no `--workers`). Async handles high concurrency per process, but one CPU
core and one event loop cap throughput, and long-lived SSE connections consume
loop capacity.

**Action:**
- Prefer **multiple replicas** behind the LB (with §2's leader gating) over
  in-process workers — cleaner scaling and matches the stateless design.
- If using in-process workers (`gunicorn -k uvicorn.workers.UvicornWorker -w N`),
  the background singletons MUST be gated to one worker — otherwise every worker
  reruns them. Replicas are simpler; prefer them.

## 5. SSE live stream at scale  🟠

**Today:** `/stream/*` holds one long-lived EventSource per browser per channel,
relaying Redis pub/sub. Tickets are short-lived (good). Each connection pins
event-loop + a DB/Redis resource for its lifetime.

**Risk:** thousands of concurrent streams × single-worker = saturation; LBs also
cap idle connection time and may buffer SSE.
**Action:** configure the LB for SSE (disable response buffering, raise idle
timeout); consider a dedicated stream tier (replicas that only serve `/stream/*`)
so a stream spike can't starve the REST API. Redis pub/sub fan-out already
decouples producers from consumers — that part scales.

## 6. Caching correctness + scale  🟡

**Today:** backend Redis cache (tenant-aware keys — verified). Frontend
`lib/api.ts` has an **in-memory TTL cache that is NOT user-aware** (per
CLAUDE.md). Fine within one browser tab, but never move it server-side as-is.
**Action:** keep client cache client-only; ensure every *server* cache key
includes `tenant_id` (already the pattern — audited in `test_tenant_isolation`).

## 7. Redis capacity & durability  🟡

**Today (prod compose):** `--maxmemory 256mb --maxmemory-policy allkeys-lru
--appendonly yes`. LRU eviction means rate-limit/cache keys can be evicted under
memory pressure (rate limiter fails *open* — acceptable). AOF gives durability.
**Action:** size maxmemory for your key volume (rate-limit windows + cache +
token blacklist + SSE); on managed Redis pick a plan with headroom; keep
`allkeys-lru`. Token-blacklist eviction only shortens logout-invalidation
window (fails safe).

## 8. Health, readiness, graceful shutdown  ✅

`/api/monitoring/live` (liveness) and `/ready` (DB + Redis) exist — wire them to
the orchestrator's liveness/readiness probes. Lifespan cancels background tasks
and closes cleanly on shutdown. `public-status` (cached 60s) backs the `/status`
page. This part is production-shaped already.

## 9. Deployment bugs that actually bite (seen or latent)

| Bug | Symptom | Guard |
|---|---|---|
| `NEXT_PUBLIC_*` not rebuilt | frontend calls wrong API URL | it's a build arg; redeploy image on change |
| `TRUST_PROXY_HEADERS` unset behind LB | mass 429 / "login failed" | §1 |
| default secrets in prod | app refuses to boot (by design) | set real 64-char secrets |
| `CORS_ORIGINS` wrong/wildcard | browser blocks API calls | set real origin(s) |
| migrations run in serving replica | duplicate/again on every replica | run as one job; `RUN_MIGRATIONS_ON_STARTUP=false` |
| duplicate background tasks | N trainers/warmers | §2 leader gating |
| DB pool exhaustion | 500s under load | §3 PgBouncer / sizing |

## 10. Cloud target (recommended shape)

- **Frontend:** container or static/edge (Vercel-style) — `NEXT_PUBLIC_API_URL`
  baked per environment.
- **API:** N stateless replicas behind an L7 LB; HPA on CPU/RPS; readiness gates
  rollout. `TRUST_PROXY_HEADERS=true`.
- **Jobs/leader:** one instance for trainer + cache warmer; migrations as a
  pre-deploy job.
- **Worker:** the existing BullMQ diagnostics worker (already separate).
- **Data:** managed Postgres + **PgBouncer**; managed Redis (persistence + LRU);
  read replica for analytics/vector reads (see SAGE_GROUNDED_INTELLIGENCE.md).
- **Observability:** wire `SENTRY_DSN` (backend init already present) + the
  telemetry substrate (`TELEMETRY_SETUP.md`).

## What's already solid (don't re-litigate)

Stateless JWT auth, Redis-distributed rate limiting, tenant RLS + app-layer
scoping, env-gated background tasks, fail-closed prod secret validation,
liveness/readiness probes, migrations-as-a-job, graceful shutdown, backup +
rehearsed-restore in CI. The architecture is scale-ready; the work is
configuration and the leader/pooler topology above — not a rewrite.
