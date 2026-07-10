-- 063 — E2-4: undo an import.
--
-- The naive design is a nullable `import_job_id` on every canonical table and a
-- `DELETE WHERE import_job_id = :job`. It is wrong here, and quietly so.
--
-- Four of the five import types are pure appends (stores, items, suppliers,
-- sales_historical) — for those, delete-by-job is exactly right. But `inventory`
-- is an UPSERT: `ON CONFLICT (store_id, item_id) DO UPDATE` overwrites the stock
-- level, unit cost and reorder point of rows that already existed. Deleting the
-- rows an import "touched" would destroy inventory records the import never
-- created, and rolling back would silently delete the customer's stock data.
--
-- So an import records what it did, row by row, into an undo ledger:
--
--     op='insert' -> the row did not exist; undo by deleting it.
--     op='update' -> the row existed; undo by restoring `before_image`.
--
-- Rollback replays the ledger in reverse. Anything the ledger cannot express, we
-- refuse to undo rather than approximate.
--
-- `import_job_id` is ALSO added to the append-only tables. Not for the rollback
-- (the ledger drives that) but for provenance: "where did this row come from?"
-- is a question an operator asks long after the undo window has closed.

BEGIN;

-- Provenance on the append-only targets. ON DELETE SET NULL: purging an old job
-- record must never delete the customer's data.
ALTER TABLE stores            ADD COLUMN IF NOT EXISTS import_job_id INTEGER;
ALTER TABLE items             ADD COLUMN IF NOT EXISTS import_job_id INTEGER;
ALTER TABLE suppliers         ADD COLUMN IF NOT EXISTS import_job_id INTEGER;
ALTER TABLE sales_historical  ADD COLUMN IF NOT EXISTS import_job_id INTEGER;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['stores', 'items', 'suppliers', 'sales_historical'] LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
             WHERE conname = format('%s_import_job_fk', t)
        ) THEN
            EXECUTE format(
                'ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (import_job_id) '
                'REFERENCES import_jobs(id) ON DELETE SET NULL', t, t || '_import_job_fk');
        END IF;
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %I (import_job_id) '
            'WHERE import_job_id IS NOT NULL', 'ix_' || t || '_import_job', t);
    END LOOP;
END $$;

-- The undo ledger. One row per canonical row an import created or overwrote.
CREATE TABLE IF NOT EXISTS import_row_undo (
    id             BIGSERIAL PRIMARY KEY,
    tenant_id      INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    import_job_id  INTEGER NOT NULL REFERENCES import_jobs(id) ON DELETE CASCADE,
    table_name     TEXT    NOT NULL,
    op             TEXT    NOT NULL CHECK (op IN ('insert', 'update')),
    row_id         BIGINT  NOT NULL,          -- surrogate PK of the affected row
    before_image   JSONB,                     -- the row as it was; NULL for 'insert'
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- An 'update' entry without a before_image cannot be undone, so it must not exist.
ALTER TABLE import_row_undo DROP CONSTRAINT IF EXISTS import_row_undo_update_has_image;
ALTER TABLE import_row_undo
    ADD CONSTRAINT import_row_undo_update_has_image
    CHECK (op <> 'update' OR before_image IS NOT NULL);

-- An 'insert' entry carries no before_image — a stray one means the writer is confused.
ALTER TABLE import_row_undo DROP CONSTRAINT IF EXISTS import_row_undo_insert_has_no_image;
ALTER TABLE import_row_undo
    ADD CONSTRAINT import_row_undo_insert_has_no_image
    CHECK (op <> 'insert' OR before_image IS NULL);

-- Only ever read as "the whole ledger for one job, newest first".
CREATE INDEX IF NOT EXISTS ix_import_row_undo_job
    ON import_row_undo (import_job_id, id DESC);

ALTER TABLE import_row_undo ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_row_undo FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON import_row_undo;
CREATE POLICY tenant_isolation ON import_row_undo
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

-- Rollback state on the job itself. `reversible` is decided at write time by the
-- importer, not guessed at read time: a job whose ledger is incomplete (e.g. it
-- predates this migration) can never be safely undone.
ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS reversible      BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS rolled_back_at  TIMESTAMPTZ;
ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS rolled_back_by  TEXT;

-- Two new lifecycle states. The job row is now written BEFORE the rows it owns
-- (so they can carry its id), which needs a 'running' state; and a reversed
-- import is neither 'completed' nor 'failed'. The old CHECK admitted neither.
ALTER TABLE import_jobs DROP CONSTRAINT IF EXISTS import_jobs_status_check;
ALTER TABLE import_jobs
    ADD CONSTRAINT import_jobs_status_check
    CHECK (status IN ('running', 'completed', 'partial', 'failed', 'rolled_back'));

-- A 'running' job can only be a crashed import: the row is written and committed
-- in the same transaction as the data, so a successful import never leaves one
-- behind. Surfacing it as its own state beats silently reporting 'failed'.

-- Rolled-back bookkeeping must agree with the status, in both directions.
ALTER TABLE import_jobs DROP CONSTRAINT IF EXISTS import_jobs_rollback_is_consistent;
ALTER TABLE import_jobs
    ADD CONSTRAINT import_jobs_rollback_is_consistent
    CHECK ((status = 'rolled_back') = (rolled_back_at IS NOT NULL));

-- Every job that exists today was written without a ledger. Saying so is the
-- whole point: they are not reversible, and the API will decline rather than
-- delete rows it cannot prove it created.
UPDATE import_jobs SET reversible = FALSE WHERE reversible IS NULL;

COMMIT;

DO $$ BEGIN
    RAISE NOTICE 'imports: undo ledger ready; pre-existing jobs marked non-reversible';
END $$;
