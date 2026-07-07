# K1 — First-party telemetry ingest (spec for Krishna)

> Owner: **Krishna** (platform/data). Consumer seam: **Yash** (`lib/telemetry.ts`).
> Parent: `docs/product/CX_LOOPS_PLAN.md` (measurement loop). Status: spec, not built.
> Effort: ~3 days. Blocked by: nothing (PostHog can run in parallel; this replaces it later).

## 1. Why this exists

The client already emits typed product events through a single `track()` API
(`frontend/src/lib/telemetry.ts`). Today the only sink is PostHog EU cloud. K1
adds a **first-party sink** so events never leave our infra — the clean PDPL
answer for UAE retail tenants who won't accept a third-party analytics vendor.

**The whole point is that the client doesn't change.** `track()` keeps its
signature; only the adapter behind it swaps (see §8). Build the pipe; the call
sites are already there.

## 2. Design constraints (non-negotiable — these are the reason to build it, not PostHog)

1. **Ingest must never slow a user action.** The client batches and sends via
   `sendBeacon`/`keepalive`; the server must 202 immediately and do all real
   work async. Adding 1ms to the UI is worse than losing 1% of events.
2. **Fire-and-forget durability.** The endpoint acknowledges receipt into a
   buffer, not into Postgres. A DB hiccup must not 500 the client or block it.
3. **No PII, enforced server-side too.** The client sends ids only, but the
   server must reject/scrub any payload with an email-shaped or obviously-PII
   field — defense in depth, and a reviewable PDPL guarantee.
4. **Bounded everything.** Payload size, batch size, event-name cardinality,
   and buffer depth all capped, with a sampling rate config. 10× tenants must
   be a config change, not an incident.
5. **Self-inflicted-DoS-proof.** A render loop on one client cannot fill the
   buffer or the table — per-session/per-IP caps + the client's own 10/session
   error throttle.

## 3. Architecture

```
browser (batched track events)
      │  POST /api/telemetry/events   (fire-and-forget, keepalive)
      ▼
FastAPI ingest handler  ──►  validate + scrub + sample  ──►  Redis list buffer
      │ 202 immediately                                        (telemetry:buffer)
      ▼
(client done — never waits for DB)

background flush worker (lifespan asyncio task, every ~2s or 500 events)
      │  LRANGE + LTRIM a batch off the buffer
      ▼
executemany INSERT into product_events  (monthly-partitioned, append-only)
```

Rationale for **Redis-buffer-then-flush** rather than insert-per-request: at
event volume the per-row insert cost and connection churn would dominate; a
buffered batch amortizes it and decouples ingest latency from DB health. This
mirrors the existing live-data pipeline's Redis-relay instinct (`redis_client`,
`data_generator`), so it fits the stack rather than adding a new pattern.

## 4. API contract

### `POST /api/telemetry/events`
- **Auth:** normal bearer (`get_current_user`). Tenant + user id come from the
  token, **never from the body** — the client cannot spoof another tenant.
- **NOT rate-limit-exempt** — but give it a generous per-IP allowance in
  `RateLimitMiddleware` (it's a batch endpoint; one call carries many events).
- **Body:**
  ```json
  {
    "events": [
      { "event": "login_succeeded", "props": { "path": "/" }, "ts": 1730000000000 },
      { "event": "export_printed", "props": { "report": "analytics" }, "ts": 1730000001000 }
    ]
  }
  ```
- **Limits (reject the whole batch with 422 if violated):**
  - `events` length ≤ 50
  - `event` ∈ a server-side allowlist mirroring the client's `TelemetryEvent`
    union (reject unknown names — this caps cardinality and blocks injection)
  - `props` ≤ 20 keys, values scalar (str ≤ 300 chars / number / bool), total
    serialized ≤ 4 KB
  - `ts` optional client epoch-ms; server clamps to `[now-24h, now+5m]` (clock skew)
- **PII scrub:** drop any prop whose key matches `/(email|phone|name|token|password|secret)/i`
  or whose value matches an email regex. Log a counter, don't fail the batch.
- **Response:** `202 Accepted`, body `{ "accepted": <int> }`. Even on a full
  buffer, return 202 with `{"accepted": 0}` — the client must never care.

### `GET /api/telemetry/summary` (admin-only, optional in v1)
Small aggregate for the in-app "product usage" admin view later — event counts
by type over a window, tenant-scoped. Not required to ship the pipe.

## 5. Redis buffer

- Key: `telemetry:buffer` (single list; events are self-describing with tenant/user).
- Push: `RPUSH` each event as a compact JSON string, tenant_id/user_id injected
  server-side from the token before pushing.
- **Cap:** after RPUSH, `LTRIM telemetry:buffer -N -1` where `N = TELEMETRY_BUFFER_MAX`
  (default 100_000). Oldest events drop first under sustained overload — bounded
  memory, graceful loss, never OOM.
- If Redis is down, the ingest handler still returns 202 (`accepted: 0`) and
  increments a dropped-events counter. Telemetry loss is acceptable; a 500 is not.

## 6. Flush worker

- Started in `main.py` lifespan alongside `data_generator`/`cache_warmer`
  (append to `started_tasks`), gated by `TELEMETRY_INGEST_ENABLED`.
- Loop: every `TELEMETRY_FLUSH_INTERVAL_S` (default 2s) OR when buffer depth
  crosses `TELEMETRY_FLUSH_BATCH` (default 500):
  1. `LRANGE telemetry:buffer 0 batch-1` then `LTRIM telemetry:buffer batch -1`
     (pop a batch atomically — do it in a MULTI/pipeline).
  2. `executemany` INSERT into `product_events` in one transaction.
  3. On DB failure: log, and **re-`RPUSH` the batch** (bounded retries, then
     drop) so a transient blip doesn't lose the batch.
- Runs as a role that inserts across tenants (see §7) — it's a platform worker,
  not a tenant request.
- Graceful shutdown: on lifespan teardown, flush the remaining buffer once.

## 7. Schema — migration `NNN_krishna_telemetry_events.sql`

Claim `max(existing)+1` at build time (currently 051 is the last, so likely 052).
Follow the `usage_events` (043) shape, but **partitioned** because this table is
high-volume and needs cheap retention.

```sql
-- Append-only product telemetry. Monthly RANGE partitions on created_at so old
-- data is dropped by DROP PARTITION (instant) instead of DELETE (bloat). No
-- pg_partman dependency — a startup function pre-creates the current + next
-- month (see ensure_telemetry_partition below).
CREATE TABLE IF NOT EXISTS product_events (
    id          BIGSERIAL,
    tenant_id   INTEGER NOT NULL,
    user_id     INTEGER,
    event       TEXT NOT NULL,
    props       JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, created_at)          -- partition key must be in the PK
) PARTITION BY RANGE (created_at);

CREATE INDEX IF NOT EXISTS ix_product_events_tenant_event_time
    ON product_events (tenant_id, event, created_at DESC);

-- RLS for the admin/tenant read path; the flush worker bypasses it (write role).
ALTER TABLE product_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON product_events;
CREATE POLICY tenant_isolation ON product_events
    USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());

-- Idempotent monthly partition maker: ensures the partition covering :months_ahead
-- from now exists. Call for 0 and 1 at startup; wire a daily call later if desired.
CREATE OR REPLACE FUNCTION ensure_telemetry_partition(months_ahead INT)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    start_date DATE := date_trunc('month', now() + (months_ahead || ' months')::interval);
    end_date   DATE := start_date + INTERVAL '1 month';
    part_name  TEXT := 'product_events_' || to_char(start_date, 'YYYY_MM');
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = part_name) THEN
        EXECUTE format(
            'CREATE TABLE %I PARTITION OF product_events FOR VALUES FROM (%L) TO (%L)',
            part_name, start_date, end_date);
    END IF;
END $$;

SELECT ensure_telemetry_partition(0);
SELECT ensure_telemetry_partition(1);
```

- **Write role:** the flush worker connects as a role with INSERT on
  `product_events` and BYPASSRLS — mirror the existing `worker_rw` pattern
  (migrations 029/035) rather than setting tenant context per row (a cross-tenant
  batch can't have a single `current_tenant_id`).
- **Retention:** `TELEMETRY_RETENTION_MONTHS` (default 6). A tiny scheduled job
  (or a daily lifespan tick) runs `DROP TABLE product_events_YYYY_MM` for
  partitions older than the window. Instant, no vacuum debt.

## 8. Client adapter change (Yash — one seam, when K1 is ready)

`lib/telemetry.ts` today calls `window.posthog?.capture()`. Add a first-party
adapter behind the same `track()`:
- Buffer events in-memory (array), flush on: 20 events, 5s timer, or
  `visibilitychange`/`pagehide` (via `navigator.sendBeacon('/api/telemetry/events', blob)`).
- Selection by config: `NEXT_PUBLIC_TELEMETRY_SINK = 'posthog' | 'firstparty' | 'off'`
  (default keeps current behavior). No call site changes — only the internal
  dispatch swaps. I'll ship this the day the endpoint is live; it's ~40 lines.

## 9. Config (append to `config.py` in Krishna's bannered block)

| Setting | Default | Purpose |
|---|---|---|
| `telemetry_ingest_enabled` | `false` | Master switch for the endpoint + worker |
| `telemetry_buffer_max` | `100000` | Redis list cap (LTRIM) |
| `telemetry_flush_interval_s` | `2` | Worker tick |
| `telemetry_flush_batch` | `500` | Max rows per flush transaction |
| `telemetry_sample_rate` | `1.0` | Server-side drop probability hook |
| `telemetry_retention_months` | `6` | Partition drop window |

## 10. Failure modes & guarantees

| Failure | Behavior |
|---|---|
| Redis down | Ingest returns 202/`accepted:0`, counter++, no user impact |
| Postgres down | Worker re-RPUSHes batch (bounded), buffer absorbs, LTRIM caps it |
| Buffer full | Oldest events dropped by LTRIM; bounded memory |
| Malformed/oversized batch | 422, nothing buffered |
| Unknown event name | Rejected (cardinality + injection guard) |
| PII in props | Scrubbed pre-buffer, counter++, batch still accepted |
| Worker crash | Lifespan supervises; buffer holds events until restart |

## 11. Acceptance criteria

- Firing 10k events across 3 tenants lands 10k rows in the correct monthly
  partition; tenant A's admin read returns 0 of tenant B's rows (RLS proof, a
  `pytest` like the tenancy tests).
- Ingest p99 latency < 15ms with the DB artificially stalled (proves decoupling).
- With `telemetry_ingest_enabled=false`, the endpoint 404/disabled and no worker
  runs — zero footprint when off.
- `DROP`-based retention removes a month in O(1), verified in a test.
- Load: sustained 1k events/s for 5 min stays flat on memory (LTRIM working).

## 12. Explicitly out of scope (counter-brainstorm)

- **ClickHouse / columnar store** — right at >100 tenants or when analytical
  queries get heavy; premature now. Partitioned Postgres is the correct first
  build and adds no new service.
- **Exactly-once delivery** — product analytics tolerates ~1% loss; the
  complexity isn't worth it. At-most-once with bounded retry is the target.
- **Real-time streaming/materialized dashboards** — batch is fine; the admin
  summary query over the indexed partitions is plenty for the tenant count.
- **Client→DB direct** — never; the buffer is the whole point.

## 13. Handoff seam summary

- **Krishna builds:** the ingest route (+ registry entry in his block), the
  Redis buffer helpers, the lifespan flush worker, migration `NNN`, the write
  role grant, retention job, and the 5 config flags.
- **Yash builds (when the endpoint is live):** the first-party adapter in
  `lib/telemetry.ts` behind the existing `track()` — one file, no call-site churn.
- **Contract between us:** the request body in §4. Lock that shape first (a
  tiny PR), then both sides build against it in parallel.
