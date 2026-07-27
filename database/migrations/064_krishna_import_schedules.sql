-- 064 — E2-2: recurring imports on a schedule.
--
-- SCOPE, STATED HONESTLY. `source_kind` admits exactly the transports this build
-- can actually run. Today that is 'https'. SFTP needs a dependency we do not
-- ship (paramiko) and IMAP needs a credential store and a blocking-IO bridge;
-- neither is here, so neither is a value this column will accept. A schedule you
-- can create but that silently never runs is worse than an API that says no —
-- see docs/api and the 501 in routes/imports.py.
--
-- THE DUPLICATE-IMPORT PROBLEM. `sales_historical` is append-only. A daily job
-- that re-fetches the same unchanged CSV would double the tenant's sales every
-- run, and the number would look plausible. `last_content_hash` is therefore not
-- an optimisation: it is the correctness mechanism. An unchanged payload is
-- skipped, loudly, with last_status = 'skipped_unchanged'.

BEGIN;

CREATE TABLE IF NOT EXISTS import_schedules (
    id                   SERIAL PRIMARY KEY,
    tenant_id            INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name                 TEXT NOT NULL,
    import_type          TEXT NOT NULL
                           CHECK (import_type IN ('stores', 'items', 'suppliers', 'sales', 'inventory')),

    -- Only transports that exist. Extending this list without shipping the
    -- adapter is how a scheduler starts lying about what it runs.
    source_kind          TEXT NOT NULL CHECK (source_kind IN ('https')),
    source_url           TEXT NOT NULL,
    mapping              JSONB NOT NULL DEFAULT '{}',

    -- 15 minutes is the floor: this polls a third party's server, and a tighter
    -- loop is indistinguishable from abuse.
    interval_minutes     INTEGER NOT NULL CHECK (interval_minutes >= 15 AND interval_minutes <= 10080),
    active               BOOLEAN NOT NULL DEFAULT TRUE,

    next_run_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_run_at          TIMESTAMPTZ,
    last_status          TEXT CHECK (last_status IN ('ok', 'failed', 'skipped_unchanged', 'skipped_quota')),
    last_error           TEXT,
    last_job_id          INTEGER REFERENCES import_jobs(id) ON DELETE SET NULL,

    -- sha256 of the last payload we actually imported. See the header.
    last_content_hash    TEXT,

    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    created_by           TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (tenant_id, name)
);

-- A failed schedule must record WHY. A bare 'failed' is not a diagnosis.
ALTER TABLE import_schedules DROP CONSTRAINT IF EXISTS import_schedules_failure_has_reason;
ALTER TABLE import_schedules
    ADD CONSTRAINT import_schedules_failure_has_reason
    CHECK (last_status <> 'failed' OR (last_error IS NOT NULL AND length(btrim(last_error)) > 0));

-- The runner's only query: "which schedules are due?", across all tenants.
CREATE INDEX IF NOT EXISTS ix_import_schedules_due
    ON import_schedules (next_run_at)
    WHERE active;

CREATE INDEX IF NOT EXISTS ix_import_schedules_tenant
    ON import_schedules (tenant_id, active);

ALTER TABLE import_schedules ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_schedules FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON import_schedules;
CREATE POLICY tenant_isolation ON import_schedules
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

COMMIT;

DO $$ BEGIN
    RAISE NOTICE 'imports: recurring https schedules ready (unchanged payloads are skipped, not re-imported)';
END $$;
