# Runbook: SSE Degraded

The live dashboard uses Server-Sent Events relayed from Redis pub/sub
(`sales:stream`, `alerts:stream`, `inventory:stream`) via `/stream/*`. The frontend
shows a degraded banner when the stream drops.

**Symptom:** users see the "live updates degraded" banner; SSE client count drops;
no new live events.

## 1. Confirm
- `/health/deep` → `redis` (pub/sub depends on Redis) and `mode.generator_running`.
- Logs for SSE connection errors; check the reverse proxy isn't buffering/closing
  long-lived connections.

## 2. Common causes
- **Redis down** → [REDIS_OUTAGE](REDIS_OUTAGE.md). Pub/sub stops; REST still works.
- **Generator not running** (demo): live events only flow when `DEMO_MODE` +
  `LIVE_GENERATOR_ENABLED` and the generator process is up. In a real-data deploy
  there is no synthetic generator — "live" reflects real ingestion.
- **Proxy timeout** — nginx must not buffer or time out `/stream/*` (keepalive,
  `proxy_buffering off`).

## 3. Mitigate
- Restore Redis / restart the generator (demo).
- The dashboard falls back to periodic REST refresh; no data is lost (history is
  durable in Postgres).

## 4. After
Confirm SSE reconnects and the banner clears. SSE degradation is cosmetic/real-time
only — historical data and KPIs remain correct.
