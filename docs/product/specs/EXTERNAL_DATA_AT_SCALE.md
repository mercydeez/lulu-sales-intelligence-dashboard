# External Data at Scale — can Retail Intelligence take 600 GB?

**Verdict up front: not as deployed today — and it shouldn't try to, the way it
currently stores data.** The fix is not a bigger Postgres; it is a tiered
pipeline where 600 GB of raw source data never sits in the serving database at
all. This spec gives the honest capacity math, the architecture, and the
build plan (SCALE-1..4), with measured benchmark numbers at the bottom.

Owners: Yash (pipeline + API), Atharva (read-path cutover), Krishna (ops).
Status: SCALE-1..3 implemented on this branch; read-path cutover deferred.

---

## 1. Where today's system actually breaks

| # | Component | Breaks at | Why |
|---|-----------|-----------|-----|
| 1 | `sales_fact_view` (UNION ALL over `sales_historical` + `sales_stream_raw`) | ~10–50 GB | It's a plain view — no partition pruning, no pre-aggregation. Every KPI hits both arms. At 600 GB a "revenue last 7 days" scan is minutes, not ms. |
| 2 | Ingestion (`db_seeder` at startup) | any real reload | One-shot, single transaction-ish, in-container CSV load. No chunking, no resume, no idempotency: a failure at hour 6 restarts from zero. |
| 3 | Backups (`pg_dump` sidecar) | ~50 GB | Nightly full logical dump of 600 GB ≈ many hours + 2× disk. Needs incremental physical backup (pgBackRest/WAL-G). |
| 4 | Sync FastAPI request → aggregate | ~5–20 GB | Big scans inside a request → gateway timeouts; the per-IP rate limiter then amplifies retries. |
| 5 | Single Docker volume on a dev box | immediately | 600 GB does not fit; even on a server, one volume = one failure domain. |
| 6 | pgvector (RAG corpus) | ~10⁷–10⁸ vectors | If the 600 GB includes documents: embedding compute is the real cost; single-node ANN indexes degrade past tens of millions of rows. |

**The one number that matters:** dashboards never need 600 GB. They need
*aggregates* of it. 600 GB of raw sales rows ≈ ~5–6 B rows; collapsed to
`(tenant, store, item, day)` daily rollups that is **~1–5 GB** — which a single
Postgres serves comfortably at interactive latency.

## 2. Two integration modes — pick per source

| | **Ingest** (copy in) | **Federate** (leave in place) |
|---|---|---|
| When | You own/receive the data (files, exports, POS dumps) | Customer already has a warehouse (their Postgres/BigQuery/Snowflake) |
| Cost | Storage + one-time load | Per-query latency, their compute |
| Freshness | Batch watermark | Live |
| Already in repo | `db_seeder` (too weak — replaced by SCALE-2) | Sage federation: `data_sources` table + `services/federation/` adapters (admin-only descriptors) |
| 600 GB answer | Raw → staging → **rollups**; detail stays cold | Push aggregation down; never move the data |

Rule of thumb: **ingest what you must serve fast and own; federate what the
customer already curates.** Both meet in the same serving contract (§3.3).

## 3. Target architecture (tiered)

```
 external sources (CSV/Parquet dumps, S3 bucket, POS exports, partner APIs)
        │
        ▼  chunked, checksummed, resumable          [SCALE-2 bulk.py]
 ┌─────────────────────────┐
 │ RAW ZONE                │  files on disk / S3-compatible store (MinIO later)
 │ keep original artifacts │  600 GB lives HERE — cheap, append-only
 └─────────────────────────┘
        │ COPY in batches (50–100k rows), ledger per chunk   [ingest_ledger]
        ▼
 ┌─────────────────────────┐
 │ STAGING: external_sales │  Postgres, RANGE-partitioned by month  [SCALE-1]
 │ monthly partitions,BRIN │  holds hot window (e.g. 13 months); older months
 └─────────────────────────┘  detached + archived back to raw zone as Parquet
        │ incremental upsert per batch (only touched days)
        ▼
 ┌─────────────────────────┐
 │ SERVING: rollup tables  │  sales_rollup_daily (tenant,store,item,day)
 │ 600 GB → ~1–5 GB        │  dashboards/KPIs read THIS — ms latency
 └─────────────────────────┘
        │                          ┌──────────────────────────────┐
        ▼                          │ FEDERATION (query pushdown)  │
   FastAPI endpoints  ◄────────────│ data_sources + adapters      │
   (+ Redis cache)                 └──────────────────────────────┘
```

### 3.1 Why these specific pieces

- **Monthly RANGE partitions + BRIN on `sale_date`** — partition pruning turns
  "last 7 days" into a scan of 1–2 partitions; BRIN indexes cost ~0 to
  maintain on append-mostly data and stay tiny at any scale.
- **Chunk ledger (`ingest_ledger`)** — every chunk is identified by
  `(source, chunk_no, sha256)`. Loading is *idempotent*: re-running a job skips
  completed chunks, so a crash at chunk 4 000/12 000 resumes, not restarts.
  This is the same content-hash idempotency the RAG ingest already uses.
- **Rollup upsert per batch** — `INSERT … ON CONFLICT … DO UPDATE` touching
  only the `(day, store, item)` keys in that batch. Cost stays proportional to
  the batch, not the table. No full-table refresh, ever.
- **Serving contract** — KPI endpoints keep their shapes; only the FROM
  changes (`sales_rollup_daily` instead of raw view). Deferred to Atharva's
  read-path cutover so the demo keeps working unchanged meanwhile.
- **Units ≠ AED invariant holds**: rollups store `units` and `revenue_aed`
  as separate columns, derived exactly as `routes/kpis.py` does today.

### 3.2 What stays OUT of scope (deliberately)

- MinIO/S3 container, Parquet cold storage, pgBackRest: documented, not built —
  zero value on a laptop; first thing to add on a real server.
- Read-path cutover of `routes/kpis.py`: teammates' demo reads stay untouched;
  the rollup table + parity test make the cutover a one-line FROM swap.
- Kafka/Airflow: BullMQ worker + Redis already give us a queue; don't add
  infra the team can't operate.

### 3.3 Serving contract (for the cutover PR)

`sales_rollup_daily(tenant_id, store_id, item_id, day, units, revenue_aed,
txn_count)` — primary key `(tenant_id, store_id, item_id, day)`.
Guarantee (tested): `SUM(rollup) == SUM(raw)` per key over any window.

## 4. Capacity math (assumptions stated)

- Row ≈ 110 B on disk incl. indexes ⇒ 600 GB ≈ **5.5 B rows**.
- Measured ingest throughput on this dev box (see §6): extrapolate as
  `rows / measured_rows_per_sec`. Server-grade NVMe + parallel COPY streams
  scale near-linearly until WAL fsync binds (~4–8 streams).
- Rollup cardinality: 10 stores × 50 items × 365 days × tenant ≈ 183 k
  rows/tenant-year → even 1 000 tenant-years ≈ 183 M rows ≈ **~15 GB** worst
  case, still single-node Postgres territory; typical demo-like tenancy ≪ that.
- Partition pruning: 7-day KPI query touches ≤ 2 monthly partitions regardless
  of total size — query cost is O(hot window), **not** O(600 GB).

## 5. Failure-mode checklist the pipeline must survive (tested in SCALE-4)

1. Kill -9 mid-load → resume skips completed chunks (ledger).
2. Same file submitted twice → 0 duplicate rows (checksum + ON CONFLICT).
3. Schema drift (extra/missing column) → chunk rejected, job continues, error
   recorded on the ledger row.
4. Rollup parity: raw sums == rollup sums after arbitrary partial loads.

## 6. Benchmark results (measured 2026-07-10, dev laptop, Docker, single stream)

Harness: `backend/scripts/bench_bulk_ingest.py` (runs the real pipeline —
chunked COPY + ledger + rollup upserts — against the live container DB).

| Metric | 2,000,000-row run |
|---|---|
| Ingest throughput | **19,136 rows/s** (104.5 s end-to-end, 40 chunks) |
| Resume / duplicate re-ingest | 40/40 chunks skipped, **0 rows duplicated** |
| Rollup parity | exact — SUM(units) raw == rollup == 40,996,617 |
| 7-day revenue query | raw staging **16.4 ms** vs rollup **5.5 ms** |
| Schema drift | poisoned chunk → ledger `failed`, job completed |

API path verified separately: `POST /api/imports/bulk` (drop-dir file) →
ledger-backed status → staging + rollup agree; path escape rejected (400);
non-admin rejected (403).

**600 GB extrapolation** (110 B/row ⇒ ~5.5 B rows): ~79 h single-stream on
this laptop; server NVMe with 4–8 parallel COPY streams (chunk model
parallelizes trivially — chunks are independent transactions) ⇒ **~10–20 h
one-time backfill**, after which daily increments are minutes. Serving
latency is the headline: the rollup read stays **~5 ms at any raw volume**
because its size is O(catalog × days), while raw scans grow with data
(already 3× slower at just 2 M rows).

Two operational notes discovered during verification (both encoded in code):
* the import drop dir must live OUTSIDE `/app` — dev uvicorn watches `/app`
  and arriving files would trigger reloads mid-ingest (`IMPORT_DROP_DIR`,
  default `/tmp/import_drop`);
* the dev auto-reloader can wedge on rapid successive file changes —
  `docker compose restart backend` recovers it.
