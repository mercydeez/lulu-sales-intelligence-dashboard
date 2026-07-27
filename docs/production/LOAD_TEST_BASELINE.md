# Load-test baseline (E6-5)

**Measured:** 10 July 2026, commit on `prototype-evolution-accuracy-bullmq`.
**Harness:** [`loadtest/k6/mixed.js`](../../loadtest/k6/mixed.js) (HTTP mix) and
[`loadtest/sse_soak.py`](../../loadtest/sse_soak.py) (SSE).

Every number below was measured on the run described. Nothing here is a target, a
projection, or a promise. Where a scenario failed, the failure is the headline.

> **RESOLVED — the single-worker finding below is fixed.** The API now runs under
> `gunicorn` with N `UvicornWorker`s, and the continuous singletons moved to a
> dedicated `singletons` container so N workers don't run N of each. Re-run of
> Scenario 4 (100 SSE + 100 VUs, Sage every iteration) on **4 workers**, same box:
>
> | Metric | 1 worker (below) | **4 workers** |
> |---|---|---|
> | Throughput | 26 req/s | **249 req/s** |
> | Latency p95 | 12.45 s | **1.24 s** |
> | Overall failed | 10.16 % | **1.54 %** |
> | Sage success | 34 % | **93 %** |
> | Peak DB connections | — | 89 / 100 |
>
> The residual ~1.5 % is the same Post-`EOF` connection-reuse artifact documented in
> §"two wrong explanations", now amplified by gunicorn's `--max-requests` worker
> recycling — a harness effect, not server saturation. Verified live: 4 gunicorn
> workers, exactly one `singletons` container running all five loops, the generator
> writing at ~1 row / 5–15 s (NOT 4×), Sage multi-turn history surviving across
> workers (Redis-backed), and the startup advisory lock serializing all four workers'
> boot DDL with no duplicate-key crash. See `docs/production/RUNTIME_PROCESSES.md`
> for the process model and the fix's design.
>
> **`WEB_CONCURRENCY=8` was tested and REGRESSED — do not raise it on this box.**
> Same run, 8 workers (with dev Postgres `max_connections` raised to 200 to give it
> a fair chance): **29 % success**, TCP-level `connection refused` / `no route to
> host` failures, then the backend container **exited (code 3)** under sustained
> load. Cause is memory, not CPU: the app process is ~700 MB (pandas/langchain/torch
> at import), and 8 gunicorn workers without `--preload` ≈ **5.6 GB on a 7.7 GB
> Docker VM** already running Postgres, the 631 MB `singletons` container, worker and
> frontend → VM memory exhaustion → fork failures → arbiter halt. Compounding it, the
> mix is DB-bound (Sage/analytics over ~917 k rows), so Postgres — not the API — is
> the bottleneck past ~4 workers. **4 workers is the sweet spot for this hardware**
> (98 %, p95 1.24 s). Scaling past that means Postgres capacity / the read replica
> (E10-7) and cutting Sage's per-query cost, plus `gunicorn --preload` to share the
> import footprint — NOT more API workers. `WEB_CONCURRENCY` default stays 4 (dev) / 2
> (prod).

---

## What this is, and is not

This is a **regression baseline**, not a capacity statement. It ran on one laptop
with Postgres, Redis, the API, the diagnostics worker and the Next.js dev server
all sharing the same machine, while the synthetic sales generator kept writing.
A production number would come from production hardware with nothing else on it.

Treat these figures as a floor to detect regressions against, and as evidence for
the one real finding below.

**Hardware:** Apple M4 Pro, 12 CPUs and 7.7 GiB visible to Docker Desktop.
**Data:** 916,807 rows through `sales_fact_view`.
**Rate limits raised for the run** (`RATE_LIMIT_REQUESTS=1000000`) — all virtual
users share one source IP, so the default 100/min bucket would have made this a
load test of the rate limiter. A `429` in these results would be a broken harness,
and there were none.

---

## Results

### 1. Dashboard read mix — 100 VUs, no SSE, no Sage

KPI cards, analytics summary, analytics trend (30d), sales history, and the
unauthenticated `/api/public/versions`.

| Metric | Value |
|---|---|
| Requests | 10,446 |
| Throughput | **115.6 req/s** |
| Failed | **0.00 %** |
| Rate-limited | 0.00 % |
| Latency median | 720 ms |
| Latency p90 / p95 | 1.28 s / **1.53 s** |
| Latency max | 5.85 s |
| Checks passed | 10,445 / 10,445 |

Clean. 100 concurrent dashboard users are served without a single error.

### 2. SSE — 100 concurrent `/stream/sales` consumers

`EventSource` cannot set an `Authorization` header, so the endpoint takes a
short-lived signed **ticket** on the query string. The soak walks the real flow:
safe request → `csrf_token` cookie → login → `POST /api/auth/stream-ticket`.

| Metric | Value |
|---|---|
| Connections established | **100 / 100** |
| Failed | 0 |
| Received ≥ 1 event | 100 |
| Time to first `data:` — p50 / p95 / max | **1.27 s / 1.66 s / 1.78 s** |
| Events delivered (45 s hold) | 500 |

The event *rate* is a property of the generator (one sale every 5–15 s), not of
the server's fan-out capacity, so it is not a throughput number and is not
reported as one.

### 3. Combined — 100 SSE + 100 VUs, Sage on 1 iteration in 5

| Metric | Value |
|---|---|
| Requests | 6,383 @ 70.5 req/s |
| Overall failed | 2.67 % |
| **Sage `POST /api/ai/chat` success** | **30 % (76 / 246)** |
| Dashboard latency p95 | 2.0 s |
| Rate-limited | 0.00 % |

The dashboard held up. **Sage did not.** Failures were `EOF` — the server closed
the connection with no response and nothing in its log.

### 4. Combined — Sage on every iteration

| Metric | Value |
|---|---|
| Requests | 2,488 @ 25.9 req/s |
| Overall failed | **10.16 %** |
| Sage success | 34 % (131 / 379) |
| Latency p95 | **12.45 s** |
| Latency max | 37.0 s |
| Sage latency p50 / p95 | 5.08 s / 6.36 s |

Throughput collapsed from 115 req/s to 26 req/s and *other* endpoints began
failing. This is saturation, not a Sage-specific bug.

---

## The finding

**The API runs in a single uvicorn process.** `backend/Dockerfile` ends with

```
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

with no `--workers`, and neither `docker-compose.yml` nor
`docker-compose.production.yml` overrides it. Twelve CPUs are available; one is
used. Under sustained load `docker stats` showed the backend pinned around 80 % of
a single core.

We chased two wrong explanations first, and both are worth recording so nobody
re-chases them:

1. **"It's the rate limiter."** No — `rate_limited` is 0.00 % in every run.
2. **"It's a keep-alive race."** uvicorn's keep-alive is 5 s, and at Sage-every-5
   a VU's connection idles ~30 s between Sage calls, so `EOF` on connection reuse
   looked obvious. It was wrong: raising Sage to every iteration made things
   *worse*, not better. A 50-request burst of Sage succeeds 50/50 both with and
   without 100 SSE streams open. The limit is **sustained concurrency on one
   event loop**, not connection reuse and not SSE.

Sage is simply the most expensive endpoint — several aggregates over ~917k rows
per question — so it saturates that one core first, and drags everything else
down with it.

### What NOT to do about it

Do not just add `--workers 4`. The API process currently owns five singleton
background tasks started in `main.py`'s lifespan:

| Task | Safe with N workers? |
|---|---|
| `import_scheduler` | ✅ claims work with `FOR UPDATE SKIP LOCKED` |
| `data_generator` | ❌ N generators → N× the synthetic write rate |
| `demo_reset` | ❌ N concurrent nightly wipes |
| `partition_maintenance` | ❌ N concurrent `DROP TABLE` on the same partition |
| `cache_warmer` | ⚠️ harmless but N× the work |

Scaling out requires moving the singleton tasks out of the request process first
(a leader election, a separate scheduler container, or a cron sidecar). Adding
workers before that trades a latency problem for a data-integrity one.

### Suggested order

1. Move `data_generator`, `demo_reset` and `partition_maintenance` out of the API
   process into their own container.
2. Then `--workers $(nproc)` behind the existing NGINX in
   `docker-compose.production.yml`.
3. Re-run this harness and update the table. Scenario 4 is the one to watch.
4. Separately: `/api/ai/chat` deserves its own budget. It is metered
   (`sage_messages`, E8-3) but the quota is off by default, so a single tenant can
   currently spend the whole box.

---

## Reproducing

```bash
# 1. Raise the per-IP rate limit for the run (all VUs share one IP).
cat > /tmp/lt.yml <<'YML'
services:
  backend:
    environment:
      RATE_LIMIT_REQUESTS: "1000000"
      RATE_LIMIT_USER_REQUESTS: "1000000"
YML
docker compose -f docker-compose.yml -f docker-compose.override.yml -f /tmp/lt.yml \
  up -d --force-recreate backend

NET=$(docker network ls --format '{{.Name}}' | grep sales_network | head -1)
IMG=$(docker inspect sales_backend --format '{{.Config.Image}}')

# 2. Dashboard mix (SAGE_EVERY=0 disables Sage; default is 1).
docker run --rm --network "$NET" -v "$PWD/loadtest/k6:/scripts" \
  -e BASE_URL=http://backend:8000 -e SAGE_EVERY=5 grafana/k6:latest run /scripts/mixed.js

# 3. SSE soak (needs httpx — the backend image has it).
docker run --rm --network "$NET" -v "$PWD/loadtest:/lt" "$IMG" \
  python /lt/sse_soak.py --base http://backend:8000 --connections 100 --hold 45

# 4. Combined: start the soak, then run k6 while it holds the streams open.
```

Restore the normal rate limit afterwards:
`docker compose up -d --force-recreate backend`.
