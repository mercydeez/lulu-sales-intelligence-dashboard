-- 056: External data at scale — partitioned staging + ingest ledger + rollups.
-- See docs/product/specs/EXTERNAL_DATA_AT_SCALE.md. Additive only: nothing
-- here touches sales_fact_view or existing read paths. Idempotent.
--
-- Design in one breath: bulk external data COPYs into external_sales (RANGE
-- partitioned by month, BRIN-indexed) in checksummed chunks recorded in
-- ingest_ledger (crash-resume + duplicate-file no-ops), and each batch upserts
-- only its touched (tenant,store,item,day) keys into sales_rollup_daily — the
-- table dashboards will read, whose size is O(catalog×days), not O(raw rows).

-- ── staging: raw external rows, monthly partitions ──────────────────────────
CREATE TABLE IF NOT EXISTS external_sales (
    tenant_id    INTEGER      NOT NULL,
    source_name  TEXT         NOT NULL,
    store_id     INTEGER      NOT NULL,
    item_id      INTEGER      NOT NULL,
    sale_date    DATE         NOT NULL,
    units        NUMERIC(14,2) NOT NULL DEFAULT 0,
    -- VALUE metric kept separate from VOLUME (units ≠ AED, see CLAUDE.md).
    -- Nullable: sources without prices get revenue derived at rollup time.
    revenue_aed  NUMERIC(16,2),
    txn_count    INTEGER      NOT NULL DEFAULT 1,
    ingested_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
) PARTITION BY RANGE (sale_date);

-- BRIN: near-zero maintenance on append-mostly data, tiny at any scale.
-- Partitioned index → auto-created on every partition.
CREATE INDEX IF NOT EXISTS idx_external_sales_date_brin
    ON external_sales USING brin (sale_date);
CREATE INDEX IF NOT EXISTS idx_external_sales_tenant
    ON external_sales (tenant_id, store_id);

-- Create (idempotently) the monthly partition covering a date. The ingest
-- service calls this before each COPY so loads never fail on a missing month.
CREATE OR REPLACE FUNCTION ensure_external_sales_partition(p_day DATE)
RETURNS TEXT
LANGUAGE plpgsql
AS $$
DECLARE
    m_start DATE := date_trunc('month', p_day)::date;
    m_end   DATE := (date_trunc('month', p_day) + interval '1 month')::date;
    part    TEXT := 'external_sales_' || to_char(m_start, 'YYYYMM');
BEGIN
    IF to_regclass(part) IS NULL THEN
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF external_sales
             FOR VALUES FROM (%L) TO (%L)', part, m_start, m_end);
    END IF;
    RETURN part;
END $$;

-- ── ledger: one row per chunk — the resume/idempotency contract ─────────────
CREATE TABLE IF NOT EXISTS ingest_ledger (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     INTEGER     NOT NULL,
    source_name   TEXT        NOT NULL,
    job_id        TEXT        NOT NULL,
    chunk_no      INTEGER     NOT NULL,
    chunk_sha256  TEXT        NOT NULL,
    row_count     INTEGER     NOT NULL DEFAULT 0,
    status        TEXT        NOT NULL DEFAULT 'pending',
    error         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at  TIMESTAMPTZ,
    -- same bytes from the same source can only ever land once
    CONSTRAINT uq_ingest_chunk UNIQUE (tenant_id, source_name, chunk_sha256)
);

DO $$ BEGIN
    ALTER TABLE ingest_ledger
        ADD CONSTRAINT ck_ingest_status
        CHECK (status IN ('pending', 'loaded', 'failed', 'skipped'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE INDEX IF NOT EXISTS idx_ingest_ledger_job ON ingest_ledger (job_id, chunk_no);

-- ── serving: daily rollups — what dashboards read at any raw scale ───────────
CREATE TABLE IF NOT EXISTS sales_rollup_daily (
    tenant_id   INTEGER       NOT NULL,
    store_id    INTEGER       NOT NULL,
    item_id     INTEGER       NOT NULL,
    day         DATE          NOT NULL,
    units       NUMERIC(16,2) NOT NULL DEFAULT 0,
    revenue_aed NUMERIC(18,2) NOT NULL DEFAULT 0,
    txn_count   BIGINT        NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, store_id, item_id, day)
);

CREATE INDEX IF NOT EXISTS idx_rollup_daily_tenant_day
    ON sales_rollup_daily (tenant_id, day);

-- Repair/parity path: recompute a tenant's rollups for a date range straight
-- from staging (normal path is incremental upserts from the ingest service —
-- this is the big hammer for audits and backfills).
CREATE OR REPLACE FUNCTION refresh_sales_rollup_daily(
    p_tenant INTEGER, p_from DATE, p_to DATE)
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    n BIGINT;
BEGIN
    DELETE FROM sales_rollup_daily
     WHERE tenant_id = p_tenant AND day >= p_from AND day <= p_to;
    INSERT INTO sales_rollup_daily
        (tenant_id, store_id, item_id, day, units, revenue_aed, txn_count, updated_at)
    SELECT tenant_id, store_id, item_id, sale_date,
           SUM(units), COALESCE(SUM(revenue_aed), 0), SUM(txn_count), now()
      FROM external_sales
     WHERE tenant_id = p_tenant AND sale_date >= p_from AND sale_date <= p_to
     GROUP BY tenant_id, store_id, item_id, sale_date;
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END $$;

DO $$ BEGIN RAISE NOTICE '056_external_scale applied'; END $$;
