-- 078 — FLYWHEEL HORIZON 2: make it operable.
--
-- WHY THIS EXISTS. Horizon 1 made the programme PROVABLE. Horizon 2 makes it
-- OPERABLE — able to run under a real load, survive a redeploy, and be audited.
-- Four capabilities need storage; none of them adds a user-facing surface, which
-- is deliberate (see docs/MASTER_IMPLEMENTATION_PLAN_C_LEVEL.md, Horizon 2).
--
--   1. A DURABLE JOB TIER. Today every long-running task — scoring an audience,
--      measuring every campaign, issuing a batch of offers — runs as an asyncio
--      task inside a process. A redeploy mid-run loses it, and there is no way
--      to resume from where it stopped. flywheel_jobs is a Postgres-backed queue
--      claimed with FOR UPDATE SKIP LOCKED, with a LEASE (so a dead worker's job
--      is reclaimed rather than stranded) and a CHECKPOINT (so a resumed job
--      continues from the last completed batch instead of redoing everything).
--
--      This is what Gate 2 tests: kill the worker mid-run and the work still
--      completes correctly, exactly once.
--
--   2. EXACTLY-ONCE DELIVERY. The transactional outbox already guarantees
--      exactly-once WRITE (the event row commits with the money/stock change).
--      It does NOT yet guarantee exactly-once DELIVERY: a relay that publishes an
--      event and then dies before marking it published will republish it, and a
--      downstream consumer that acts on both copies double-sends an offer to a
--      real customer. flywheel_delivery_receipts is the consumer-side idempotency
--      ledger — a consumer records the event key it has acted on, and a redelivery
--      of the same key is a no-op.
--
--   3. A MODEL REGISTRY BOUND TO ITS DATA. Ruling #1 (20 Jul 2026) promotes a
--      model only when a pre-registered holdout beats rules. That criterion is
--      unenforceable unless you can prove WHICH DATA a model was trained on — a
--      model trained on last week's snapshot cannot be judged against this week's
--      holdout. So flywheel_model_versions gains a DATA_SNAPSHOT_HASH (a
--      fingerprint of the exact training rows), a lifecycle status, a rollback
--      pointer, and promotion metadata. Lineage from a live decision back to the
--      artifact already exists (flywheel_decisions.churn_model_version_id).
--
--   4. END-TO-END TRACING. flywheel_decisions already carries request_id (the
--      HTTP request). But a decision's life continues asynchronously — activation,
--      the outbox relay, redemption days later — past the request that started it.
--      A TRACE_ID spans that whole life, so "why did this customer get this offer,
--      and what happened to it" is one query rather than an investigation. This is
--      also a PDPL obligation: a data subject may demand an explanation of an
--      automated decision, and the trace is that explanation.
--
-- TENANCY. Every new table carries tenant_id, the tenant_isolation policy and
-- FORCE RLS (migrations 012/060/075/077, and ruling #2 which made RLS mandatory
-- in production). REUSE, DON'T FORK: this migration only CREATEs flywheel_ tables
-- and ALTERs flywheel_ tables — no shared platform table is touched.

BEGIN;

-- ===========================================================================
-- STAGE 01 — THE DURABLE JOB QUEUE
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_jobs (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- What to run. A small, closed vocabulary — an unknown kind is a bug, not a
    -- free-text instruction, so it is CHECK-constrained.
    kind                VARCHAR(40) NOT NULL
                          CHECK (kind IN ('score_audience', 'measure_campaign',
                                          'measure_all', 'issue_offers',
                                          'shadow_score', 'refresh_readouts',
                                          'train_model')),
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- IDEMPOTENT ENQUEUE. Enqueuing the same logical job twice (a double click, a
    -- retried request, two schedulers) must not create two jobs. The partial
    -- unique index below enforces "at most one live job per key".
    idempotency_key     VARCHAR(160),

    status              VARCHAR(20) NOT NULL DEFAULT 'queued'
                          CHECK (status IN ('queued', 'running', 'succeeded',
                                            'failed', 'dead', 'cancelled')),

    -- LEASE. When a worker claims a job it stamps claimed_by/claimed_at and sets
    -- lease_expires_at. If the worker dies, the lease lapses and a reaper returns
    -- the job to 'queued'. Without a lease a crashed worker strands its job in
    -- 'running' forever — the classic queue failure.
    claimed_by          VARCHAR(80),
    claimed_at          TIMESTAMPTZ,
    lease_expires_at    TIMESTAMPTZ,

    -- CHECKPOINT. Resumable progress: a batch cursor, counts done so far, whatever
    -- the handler needs to continue rather than restart. This is what turns "the
    -- redeploy lost 40 minutes of scoring" into "the redeploy cost one batch".
    checkpoint          JSONB NOT NULL DEFAULT '{}'::jsonb,

    attempts            INTEGER NOT NULL DEFAULT 0,
    max_attempts        INTEGER NOT NULL DEFAULT 5,
    -- Backoff / scheduling. A failed job is retried no earlier than run_after.
    run_after           TIMESTAMPTZ NOT NULL DEFAULT now(),

    last_error          TEXT,
    result              JSONB,

    -- Correlation across the whole decision lifecycle (see STAGE 04).
    trace_id            VARCHAR(48),

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ
);

-- The claim query orders by (run_after, id) over ready rows; this index makes
-- that a range scan rather than a sort of the whole table.
CREATE INDEX IF NOT EXISTS idx_flywheel_jobs_ready
    ON flywheel_jobs (run_after, id)
    WHERE status IN ('queued', 'failed');

-- The reaper scans for expired leases.
CREATE INDEX IF NOT EXISTS idx_flywheel_jobs_running_lease
    ON flywheel_jobs (lease_expires_at)
    WHERE status = 'running';

-- AT MOST ONE LIVE JOB PER IDEMPOTENCY KEY. A finished job (succeeded/dead/
-- cancelled) leaves the key free to be enqueued again — a nightly "measure_all"
-- should run once per night, not be blocked forever by last night's success.
CREATE UNIQUE INDEX IF NOT EXISTS uq_flywheel_jobs_live_key
    ON flywheel_jobs (tenant_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL
      AND status IN ('queued', 'running', 'failed');

-- ===========================================================================
-- STAGE 02 — EXACTLY-ONCE DELIVERY (consumer-side idempotency ledger)
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_delivery_receipts (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- WHO consumed it. The same event may legitimately be delivered to several
    -- consumers (a notifier, an SSE fan-out, an analytics sink); each must act at
    -- most once, so the receipt is per-consumer.
    consumer            VARCHAR(60) NOT NULL,
    -- The event's stable identity. For an outbox event this is its row id; for a
    -- side effect it is the natural key of the action (e.g. 'offer:1234'). Acting
    -- is guarded by INSERT ... ON CONFLICT DO NOTHING on (tenant, consumer, key).
    event_key           VARCHAR(160) NOT NULL,

    outcome             VARCHAR(20) NOT NULL DEFAULT 'processed'
                          CHECK (outcome IN ('processed', 'skipped', 'failed')),
    detail              TEXT,
    processed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_flywheel_receipt UNIQUE (tenant_id, consumer, event_key)
);

CREATE INDEX IF NOT EXISTS idx_flywheel_receipts_consumer
    ON flywheel_delivery_receipts (tenant_id, consumer, processed_at DESC);

-- ===========================================================================
-- STAGE 03 — MODEL REGISTRY: bind a model to the data it was trained on.
--
-- These are ADDITIVE columns on flywheel_model_versions (a flywheel_-owned table
-- from migration 075). Existing rows get NULLs, which the registry service reads
-- as "legacy, pre-registry" — honest, not a silent default.
-- ===========================================================================

ALTER TABLE flywheel_model_versions
    -- THE FINGERPRINT. A hash of the exact training rows (ids + label + as-of
    -- date). Two models with the same hash saw the same data; a promotion claim
    -- of "beat rules on the holdout" is only meaningful relative to this.
    ADD COLUMN IF NOT EXISTS data_snapshot_hash    VARCHAR(64),
    ADD COLUMN IF NOT EXISTS data_snapshot_rows    INTEGER,
    ADD COLUMN IF NOT EXISTS data_snapshot_from    DATE,
    ADD COLUMN IF NOT EXISTS data_snapshot_to      DATE,

    -- LIFECYCLE. Distinct from is_active (which just says "the request path uses
    -- this one"). A model moves shadow -> candidate -> promoted, or -> retired /
    -- rolled_back. Ruling #1 keeps everything in 'shadow' until a holdout earns
    -- promotion.
    ADD COLUMN IF NOT EXISTS lifecycle_status      VARCHAR(20)
                              DEFAULT 'shadow'
                              CHECK (lifecycle_status IN ('shadow', 'candidate',
                                                          'promoted', 'retired',
                                                          'rolled_back')),
    -- ROLLBACK LINEAGE. superseded_by points forward to the version that replaced
    -- this one; rolled_back_to points back to the version restored when a
    -- promotion is reverted. Together they make "what was live on date X, and why
    -- did it change" answerable.
    ADD COLUMN IF NOT EXISTS superseded_by         INTEGER
                              REFERENCES flywheel_model_versions(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS rolled_back_to        INTEGER
                              REFERENCES flywheel_model_versions(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS promoted_at           TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS promoted_by           INTEGER
                              REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS promotion_note        TEXT;

CREATE INDEX IF NOT EXISTS idx_flywheel_model_versions_snapshot
    ON flywheel_model_versions (tenant_id, data_snapshot_hash);
CREATE INDEX IF NOT EXISTS idx_flywheel_model_versions_lifecycle
    ON flywheel_model_versions (tenant_id, lifecycle_status);

-- ===========================================================================
-- STAGE 04 — END-TO-END TRACING
--
-- request_id already ties a decision to the HTTP request that produced it. But a
-- decision's life continues past that request — activation, the outbox relay,
-- redemption days later. trace_id spans the whole lifecycle so the full story is
-- one indexed lookup.
-- ===========================================================================

ALTER TABLE flywheel_decisions
    ADD COLUMN IF NOT EXISTS trace_id VARCHAR(48);

CREATE INDEX IF NOT EXISTS idx_flywheel_decisions_trace
    ON flywheel_decisions (tenant_id, trace_id)
    WHERE trace_id IS NOT NULL;

-- Redemptions and outbox events carry the trace forward, so the async tail of a
-- decision joins back to its origin.
ALTER TABLE flywheel_redemptions
    ADD COLUMN IF NOT EXISTS trace_id VARCHAR(48);
ALTER TABLE flywheel_outbox
    ADD COLUMN IF NOT EXISTS trace_id VARCHAR(48);

-- ===========================================================================
-- TENANCY — policy + FORCE RLS on the two new tables (ruling #2).
-- The ALTERed tables already have their policies from 075.
-- ===========================================================================

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'flywheel_jobs', 'flywheel_delivery_receipts'
    ]
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I '
            'USING (tenant_id = current_tenant_id()) '
            'WITH CHECK (tenant_id = current_tenant_id())', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    END LOOP;
END $$;

-- The job queue and receipts are written by the REQUEST path (which connects as
-- the non-owner app_rw role when RLS is enforced), so app_rw needs table
-- privileges — RLS filters rows, it does not grant access to the table itself.
-- Guarded on the role existing so a dev DB without app_rw does not fail here.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON flywheel_jobs TO app_rw;
        GRANT SELECT, INSERT, UPDATE, DELETE ON flywheel_delivery_receipts TO app_rw;
        GRANT USAGE, SELECT ON SEQUENCE flywheel_jobs_id_seq TO app_rw;
        GRANT USAGE, SELECT ON SEQUENCE flywheel_delivery_receipts_id_seq TO app_rw;
    END IF;
END $$;

COMMIT;
