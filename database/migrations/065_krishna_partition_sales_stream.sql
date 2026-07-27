-- 065 — E6-3: partition sales_stream_raw by month, and give it a retention policy.
--
-- The generator appends a row every 5–15s forever. Deleting old rows from a
-- monolithic table is a slow, bloating DELETE; dropping a monthly partition is
-- instant and returns the disk. That is the entire point.
--
-- THE DANGEROUS PART, AND HOW IT IS AVOIDED.
-- Postgres cannot convert a table to a partitioned one in place, so the table
-- must be rebuilt and swapped. `sales_fact_view` reads it, and FOURTEEN objects
-- read that view (metric_sales_fact, metric_margin_fact, sage_sales, three
-- materialised views, and seven metric views built on those). A
-- `DROP VIEW … CASCADE` would take every one of them with it, and rebuilding
-- them from captured DDL would silently lose `security_invoker`, grants, and the
-- matviews' indexes and data.
--
-- Instead: CREATE OR REPLACE VIEW preserves the view's OID. Its SQL text is
-- unchanged — it names `sales_stream_raw`, which after the swap resolves to the
-- partitioned table. Every dependent keeps pointing at the same view OID and
-- never notices. Nothing is dropped except the old table.
--
-- WHAT PARTITIONING COSTS US, STATED PLAINLY.
-- A UNIQUE constraint on a partitioned table must contain the partition key, so
-- `UNIQUE (event_id)` becomes `UNIQUE (event_id, "timestamp")`. Global
-- uniqueness of event_id is therefore no longer enforced by the database. It was
-- never relied upon: every writer generates a fresh uuid4 and nothing does
-- `ON CONFLICT (event_id)` — the constraint was a guard, not an idempotency key.
-- Two rows could now share an event_id at different timestamps. If a future
-- ingest path needs real de-duplication it must use a different mechanism (an
-- ingest ledger keyed on the source's own id), not this constraint.
--
-- SAFETY: a DEFAULT partition exists so that an INSERT can never be rejected for
-- landing outside a declared month — that would kill the live generator at
-- midnight on the 1st if maintenance had failed. Rows in DEFAULT cannot be
-- dropped by pruning, so maintenance creates months ahead and warns loudly if
-- DEFAULT is ever non-empty.

BEGIN;

-- The partition key must be NOT NULL. It is already, in every row.
UPDATE sales_stream_raw
   SET "timestamp" = COALESCE(created_at, now())
 WHERE "timestamp" IS NULL;
ALTER TABLE sales_stream_raw ALTER COLUMN "timestamp" SET NOT NULL;

-- ---------------------------------------------------------------------------
-- 1. The partitioned replacement.
-- ---------------------------------------------------------------------------
CREATE TABLE sales_stream_raw_new (
    id           INTEGER NOT NULL DEFAULT nextval('sales_stream_raw_id_seq'),
    event_id     UUID NOT NULL,
    "timestamp"  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    store_id     INTEGER NOT NULL REFERENCES stores(id),
    item_id      INTEGER NOT NULL REFERENCES items(id),
    sales        INTEGER NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    tenant_id    INTEGER NOT NULL DEFAULT 1,
    is_synthetic BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT sales_stream_raw_new_pkey PRIMARY KEY (id, "timestamp"),
    CONSTRAINT sales_stream_raw_new_event_id_key UNIQUE (event_id, "timestamp")
) PARTITION BY RANGE ("timestamp");

-- ---------------------------------------------------------------------------
-- 2. Partition management. Created before any data moves.
-- ---------------------------------------------------------------------------

-- Create the monthly partition covering `p_month` (any instant inside it).
CREATE OR REPLACE FUNCTION create_sales_stream_partition(p_parent TEXT, p_month DATE)
RETURNS TEXT
LANGUAGE plpgsql AS $$
DECLARE
    v_start DATE := date_trunc('month', p_month)::date;
    v_end   DATE := (date_trunc('month', p_month) + INTERVAL '1 month')::date;
    v_name  TEXT := format('%s_%s', p_parent, to_char(v_start, 'YYYY_MM'));
BEGIN
    IF to_regclass(v_name) IS NOT NULL THEN
        RETURN v_name;
    END IF;
    EXECUTE format(
        'CREATE TABLE %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)',
        v_name, p_parent, v_start, v_end);
    RETURN v_name;
END $$;

-- Ensure every month from the oldest row through `p_months_ahead` exists.
CREATE OR REPLACE FUNCTION ensure_sales_stream_partitions(p_months_ahead INTEGER DEFAULT 3)
RETURNS INTEGER
LANGUAGE plpgsql AS $$
DECLARE
    v_month DATE := date_trunc('month', now())::date;
    v_last  DATE := (date_trunc('month', now()) + make_interval(months => p_months_ahead))::date;
    v_made  INTEGER := 0;
BEGIN
    WHILE v_month <= v_last LOOP
        IF to_regclass(format('sales_stream_raw_%s', to_char(v_month, 'YYYY_MM'))) IS NULL THEN
            PERFORM create_sales_stream_partition('sales_stream_raw', v_month);
            v_made := v_made + 1;
        END IF;
        v_month := (v_month + INTERVAL '1 month')::date;
    END LOOP;
    RETURN v_made;
END $$;

-- Drop whole partitions older than the retention window. Returns the names.
-- Never touches the DEFAULT partition: rows that landed there are outside every
-- declared month, and dropping it would delete unrelated data.
CREATE OR REPLACE FUNCTION prune_sales_stream_partitions(p_retention_months INTEGER)
RETURNS TABLE(dropped TEXT)
LANGUAGE plpgsql AS $$
DECLARE
    v_cutoff DATE;
    v_rec    RECORD;
BEGIN
    IF p_retention_months IS NULL OR p_retention_months < 1 THEN
        RAISE EXCEPTION 'retention must be at least 1 month, got %', p_retention_months;
    END IF;
    v_cutoff := date_trunc('month', now() - make_interval(months => p_retention_months))::date;

    FOR v_rec IN
        SELECT c.relname
          FROM pg_class c
          JOIN pg_inherits i ON i.inhrelid = c.oid
          JOIN pg_class p ON p.oid = i.inhparent
         WHERE p.relname = 'sales_stream_raw'
           AND c.relname ~ '^sales_stream_raw_\d{4}_\d{2}$'
           -- The partition's month, parsed from its name, is strictly older.
           AND to_date(right(c.relname, 7), 'YYYY_MM') < v_cutoff
    LOOP
        EXECUTE format('DROP TABLE %I', v_rec.relname);
        dropped := v_rec.relname;
        RETURN NEXT;
    END LOOP;
END $$;

-- Partitions covering everything we already hold, plus three months of runway.
DO $$
DECLARE
    v_month DATE;
    v_last  DATE := (date_trunc('month', now()) + INTERVAL '3 months')::date;
BEGIN
    SELECT date_trunc('month', COALESCE(MIN("timestamp"), now()))::date
      INTO v_month FROM sales_stream_raw;

    WHILE v_month <= v_last LOOP
        PERFORM create_sales_stream_partition('sales_stream_raw_new', v_month);
        v_month := (v_month + INTERVAL '1 month')::date;
    END LOOP;
END $$;

-- The safety net. An INSERT must never fail for want of a partition.
CREATE TABLE sales_stream_raw_new_default PARTITION OF sales_stream_raw_new DEFAULT;

-- ---------------------------------------------------------------------------
-- 3. Move the data.
-- ---------------------------------------------------------------------------
INSERT INTO sales_stream_raw_new
    (id, event_id, "timestamp", store_id, item_id, sales, created_at, tenant_id, is_synthetic)
SELECT id, event_id, "timestamp", store_id, item_id, sales, created_at, tenant_id, is_synthetic
  FROM sales_stream_raw;

-- ---------------------------------------------------------------------------
-- 4. Indexes, RLS and the synthetic-confinement trigger (E0-8, migration 057).
--    Indexes declared on the parent propagate to every partition, present and
--    future.
-- ---------------------------------------------------------------------------
CREATE INDEX idx_sales_stream_raw_new_tenant     ON sales_stream_raw_new (tenant_id);
CREATE INDEX idx_sales_stream_new_store_item     ON sales_stream_raw_new (store_id, item_id);
CREATE INDEX idx_sales_stream_new_timestamp      ON sales_stream_raw_new ("timestamp");
CREATE INDEX idx_sales_stream_new_synthetic      ON sales_stream_raw_new (tenant_id, "timestamp")
    WHERE is_synthetic;

ALTER TABLE sales_stream_raw_new ENABLE ROW LEVEL SECURITY;
ALTER TABLE sales_stream_raw_new FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON sales_stream_raw_new
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

-- Postgres 13+ allows BEFORE ROW triggers on a partitioned parent; it fires for
-- inserts routed to any partition. Without this, a synthetic row could be
-- written onto a real tenant (E0-8).
CREATE TRIGGER trg_sales_stream_raw_confine_synthetic
    BEFORE INSERT OR UPDATE ON sales_stream_raw_new
    FOR EACH ROW EXECUTE FUNCTION sales_stream_raw_confine_synthetic();

-- ---------------------------------------------------------------------------
-- 5. The swap.
--
-- ORDER MATTERS. Index names are schema-global, so the new table's constraints
-- cannot take the names `sales_stream_raw_pkey` / `..._event_id_key` while the
-- legacy table still owns indexes by those names. Every rename therefore waits
-- until the legacy table is gone — which in turn waits for the view to be
-- rebound off it.
-- ---------------------------------------------------------------------------
-- Detach the sequence, or dropping the legacy table would drop it with it and
-- the new table's DEFAULT would dangle.
ALTER SEQUENCE sales_stream_raw_id_seq OWNED BY NONE;

ALTER TABLE sales_stream_raw     RENAME TO sales_stream_raw_legacy;
ALTER TABLE sales_stream_raw_new RENAME TO sales_stream_raw;

-- ---------------------------------------------------------------------------
-- 6. Rebind the view WITHOUT dropping it. Identical column list and types, so
--    CREATE OR REPLACE keeps the OID and all fourteen dependents intact.
--
--    `WITH (security_invoker = true)` is NOT optional and NOT decoration.
--    CREATE OR REPLACE VIEW resets reloptions to whatever this statement
--    declares; omitting it silently reverts the view to security-definer, so it
--    would read the base tables as its OWNER and quietly bypass the RLS policy
--    that scopes sales_stream_raw and sales_historical to a tenant. This is the
--    exact "silently lose security_invoker" failure the header warns about, and
--    it was caught by diffing the regenerated schema baseline, not by a test.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW sales_fact_view
WITH (security_invoker = true) AS
 SELECT sales_historical.id,
    sales_historical.date,
    sales_historical.store_id,
    sales_historical.item_id,
    sales_historical.sales,
    false AS is_streaming,
    'historical'::text AS source,
    sales_historical.created_at,
    sales_historical.tenant_id
   FROM sales_historical
UNION ALL
 SELECT sales_stream_raw.id + 1000000000 AS id,
    sales_stream_raw."timestamp"::date AS date,
    sales_stream_raw.store_id,
    sales_stream_raw.item_id,
    sales_stream_raw.sales,
    true AS is_streaming,
    'streaming'::text AS source,
    COALESCE(sales_stream_raw.created_at, sales_stream_raw."timestamp") AS created_at,
    sales_stream_raw.tenant_id
   FROM sales_stream_raw;

-- Now nothing references the old table. Dropping it frees its index names.
DROP TABLE sales_stream_raw_legacy;

-- ---------------------------------------------------------------------------
-- 7. Take the canonical names, now that they are free.
-- ---------------------------------------------------------------------------
ALTER TABLE sales_stream_raw RENAME CONSTRAINT sales_stream_raw_new_pkey
    TO sales_stream_raw_pkey;
ALTER TABLE sales_stream_raw RENAME CONSTRAINT sales_stream_raw_new_event_id_key
    TO sales_stream_raw_event_id_key;

ALTER INDEX idx_sales_stream_raw_new_tenant RENAME TO idx_sales_stream_raw_tenant;
ALTER INDEX idx_sales_stream_new_store_item RENAME TO idx_sales_stream_store_item;
ALTER INDEX idx_sales_stream_new_timestamp  RENAME TO idx_sales_stream_timestamp;
ALTER INDEX idx_sales_stream_new_synthetic  RENAME TO idx_sales_stream_synthetic;

ALTER TABLE sales_stream_raw_new_default RENAME TO sales_stream_raw_default;

-- The month partitions were created under the old parent's name; align them, so
-- prune_sales_stream_partitions' `^sales_stream_raw_\d{4}_\d{2}$` matches.
DO $$
DECLARE r RECORD;
BEGIN
    FOR r IN SELECT c.relname FROM pg_class c
               JOIN pg_inherits i ON i.inhrelid = c.oid
               JOIN pg_class p ON p.oid = i.inhparent
              WHERE p.relname = 'sales_stream_raw'
                AND c.relname LIKE 'sales\_stream\_raw\_new\_%'
    LOOP
        EXECUTE format('ALTER TABLE %I RENAME TO %I',
                       r.relname, replace(r.relname, 'sales_stream_raw_new_', 'sales_stream_raw_'));
    END LOOP;
END $$;

ALTER SEQUENCE sales_stream_raw_id_seq OWNED BY sales_stream_raw.id;
SELECT setval('sales_stream_raw_id_seq',
              GREATEST((SELECT COALESCE(MAX(id), 0) FROM sales_stream_raw), 1));

-- Grants the old table carried (worker_rw reads the stream for diagnostics).
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'worker_rw') THEN
        GRANT SELECT ON sales_stream_raw TO worker_rw;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON sales_stream_raw TO app_rw;
    END IF;
END $$;

COMMIT;

DO $$ BEGIN
    RAISE NOTICE 'sales_stream_raw is partitioned by month; prune_sales_stream_partitions(n) drops whole months';
END $$;
