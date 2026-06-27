# Runbook: High Latency

**Symptom:** p95 `http_request_duration_seconds` over threshold; `X-Process-Time`
headers and "SLOW:" log lines (>500ms) rising.

## 1. Localize
- Break down latency by path from `/api/monitoring/metrics`.
- Check DB pool saturation (`/health/deep`) and slow queries.
- Check Redis latency (cache misses force expensive recomputation).

## 2. Common causes & fixes
- **Cold cache** → ensure the cache warmer is running (`RUN_CACHE_WARMER`); it keeps
  heavy dashboard queries hot.
- **DB pool exhaustion / leaked connections** → restart API to reset the pool;
  review pool size vs. replica count.
- **Forecast trainer on the API host** starving CPU → run it as a dedicated worker
  (`python -m app.commands.forecast_trainer`), disable on the API (`RUN_FORECAST_TRAINER=false`).
- **A heavy endpoint** → profile; add an index or cache; the units/AED math should
  read from `sales_fact_view`.

## 3. Mitigate
Scale API replicas, warm caches, or temporarily disable the offending feature flag.

## 4. After
Confirm p95 recovers; capture the slow query/endpoint; add an index/cache + alert.
