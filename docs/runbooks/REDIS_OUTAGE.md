# Runbook: Redis Outage

Redis backs the JWT blacklist, rate limiting, response cache, and SSE pub/sub. It
holds **no durable customer data** — losing it is recoverable.

**Symptom:** `/health/ready` 503 with `redis: error`; SSE streams stall; auth slow.

## 1. Confirm
- `/health/deep` → `checks.redis`.
- `docker logs app_redis_prod --tail=100`; `docker exec app_redis_prod redis-cli -a "$REDIS_PASSWORD" ping`.

## 2. Behavior during the outage (by design)
- **Session revocation:** fail-**closed** by default (`AUTH_FAIL_OPEN_ON_REDIS_DOWN=false`)
  — requests are rejected rather than honoring a possibly-revoked token. If
  availability must win during an incident, set it to `true` temporarily (accepting
  that logged-out tokens may be honored) and revert after.
- **Rate limiting / cache:** degrade; the app continues.

## 3. Recover
- Restart Redis: `docker compose -f docker-compose.production.yml up -d redis`.
- The append-only file (`redis_data`) restores cache state; if lost, caches simply
  re-warm. No restore-from-backup needed.
- Confirm `/health/ready` returns 200.

## 4. Prevent
- Alert on `/health/ready` 503 with `redis: error`.
- Ensure `REDIS_PASSWORD` is set (self-hosted Redis must require auth — enforced by
  `validate_security` when `REDIS_SELF_HOSTED=true`).
