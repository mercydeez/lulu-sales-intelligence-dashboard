-- =============================================================================
-- 081_operations_copilot.sql — Retail IQ Operations Copilot (persistence)
--
-- Extends the existing diagnostics loop (findings -> action_drafts) with the one
-- stage it never had: an AUDITABLE, RESUMABLE run that turns a verified finding
-- into a human-approved action draft, records who approved it, and links the
-- outcome back to the finding's existing measurement columns (migration 034).
--
-- WHY FOUR TABLES AND NOT SEVEN. Approvals and executions are EVENTS, not
-- entities: `operations_events` is append-only and is the audit log, while the
-- decision itself is denormalised onto the proposal row so the queue stays a
-- single indexed read. Measurement reuses findings.metric_before/metric_after —
-- the worker's measure job already closes that loop and forking it would give us
-- two disagreeing definitions of "did it improve".
--
-- WHAT THIS SCHEMA REFUSES TO MODEL: an externally submitted purchase order or a
-- committed warehouse transfer. `executed_ref` points at an INTERNAL draft row
-- (a draft purchase_orders row, a requested stock_transfers row). No connector
-- exists, so no column here may be read as "sent to a supplier".
--
-- Tenancy: every table carries tenant_id + FORCE RLS (ruling #2). Idempotency
-- follows the flywheel precedent: partial unique (tenant_id, idempotency_key).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- operations_runs — one agent run over one finding. `state` IS the checkpoint:
-- the graph is invoked twice (recommend, then execute-after-approval) and never
-- holds a web request open waiting for a human.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operations_runs (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    finding_id      BIGINT REFERENCES findings(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'analyzing'
                    CHECK (status IN ('analyzing', 'awaiting_approval', 'executing',
                                      'measuring', 'completed', 'refused', 'escalated',
                                      'rejected', 'cancelled', 'failed')),
    -- Last graph node reached. Sub-steps (authorize/evidence/diagnose/...) are
    -- events, not statuses — fewer states, same auditability.
    phase           TEXT,
    state           JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Why the copilot declined to propose anything. Populated for refused/escalated.
    refusal_reason  TEXT,
    error           TEXT,
    payload_version TEXT NOT NULL DEFAULT 'v1',
    graph_version   TEXT NOT NULL DEFAULT 'ops-v1',
    prompt_version  TEXT NOT NULL DEFAULT 'ops-recommend-v1',
    created_by      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_operations_runs_tenant_status
    ON operations_runs (tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_operations_runs_finding
    ON operations_runs (tenant_id, finding_id);
-- At most ONE live run per finding: re-triggering returns the existing run
-- instead of racing two graphs over the same problem.
CREATE UNIQUE INDEX IF NOT EXISTS uq_operations_runs_live_finding
    ON operations_runs (tenant_id, finding_id)
    WHERE status IN ('analyzing', 'awaiting_approval', 'executing', 'measuring');

-- ---------------------------------------------------------------------------
-- operations_proposals — the human-approvable artifact. `recommendation` holds
-- the full OperationsRecommendation contract (evidence, measured facts,
-- hypotheses, assumptions, risks, missing data) exactly as validated in Python.
-- `version` is optimistic concurrency: an approval carrying a stale version is
-- rejected rather than silently overwriting a concurrent decision.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operations_proposals (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    run_id              BIGINT NOT NULL REFERENCES operations_runs(id) ON DELETE CASCADE,
    finding_id          BIGINT REFERENCES findings(id) ON DELETE SET NULL,
    action_type         TEXT NOT NULL
                        CHECK (action_type IN ('replenishment_draft',
                                               'stock_transfer_draft',
                                               'investigation_task')),
    status              TEXT NOT NULL DEFAULT 'awaiting_approval'
                        CHECK (status IN ('awaiting_approval', 'approved', 'rejected',
                                          'executing', 'executed', 'execution_failed',
                                          'expired', 'cancelled', 'superseded')),
    title               TEXT NOT NULL,
    recommendation      JSONB NOT NULL DEFAULT '{}'::jsonb,
    calculated_parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Scope, denormalised so an approval can be authorised without parsing JSON.
    target_store_ids    INTEGER[] NOT NULL DEFAULT '{}',
    target_item_ids     INTEGER[] NOT NULL DEFAULT '{}',
    risk_level          TEXT NOT NULL DEFAULT 'medium'
                        CHECK (risk_level IN ('low', 'medium', 'high')),
    required_approval_role TEXT NOT NULL,
    expires_at          TIMESTAMPTZ,
    version             INTEGER NOT NULL DEFAULT 1,
    idempotency_key     TEXT,
    approved_by         TEXT,
    approved_at         TIMESTAMPTZ,
    rejection_reason    TEXT,
    assigned_to         TEXT,
    due_at              TIMESTAMPTZ,
    -- INTERNAL reference only (e.g. 'purchase_order:41', 'stock_transfer:7').
    -- Never an external supplier/ERP identifier — no connector exists.
    executed_ref        TEXT,
    executed_at         TIMESTAMPTZ,
    payload_version     TEXT NOT NULL DEFAULT 'v1',
    created_by          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_operations_proposals_tenant_status
    ON operations_proposals (tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_operations_proposals_run
    ON operations_proposals (run_id);
CREATE INDEX IF NOT EXISTS ix_operations_proposals_finding
    ON operations_proposals (tenant_id, finding_id);
-- Flywheel precedent (075): a retried mutation carrying the same key applies ONCE.
CREATE UNIQUE INDEX IF NOT EXISTS uq_operations_proposals_idem
    ON operations_proposals (tenant_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

-- ---------------------------------------------------------------------------
-- operations_events — APPEND-ONLY audit trail. Every state transition, tool
-- call, approval, rejection, execution and measurement lands here. Corrections
-- append a new event; history is never edited (UPDATE/DELETE revoked below).
-- Stores structured facts only — never model chain-of-thought, never prompts.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operations_events (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    run_id       BIGINT NOT NULL REFERENCES operations_runs(id) ON DELETE CASCADE,
    proposal_id  BIGINT REFERENCES operations_proposals(id) ON DELETE SET NULL,
    event_type   TEXT NOT NULL,          -- run.created | evidence.gathered | proposal.created | approval.granted | ...
    actor        TEXT,                   -- 'system' or the acting user's email
    actor_user_id INTEGER,
    payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
    request_id   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_operations_events_run
    ON operations_events (run_id, created_at);
CREATE INDEX IF NOT EXISTS ix_operations_events_tenant_type
    ON operations_events (tenant_id, event_type, created_at DESC);

-- ---------------------------------------------------------------------------
-- tenant_operations_policies — approval ladder, safety-stock rules, measurement
-- windows and freshness thresholds as CONFIGURATION (flywheel precedent). No
-- customer name, store name, supplier or monetary limit is hard-coded anywhere:
-- code ships DEFAULTS (services/operations/policy.py), a tenant overrides them.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenant_operations_policies (
    id         BIGSERIAL PRIMARY KEY,
    tenant_id  INTEGER NOT NULL UNIQUE REFERENCES tenants(id) ON DELETE CASCADE,
    policy     JSONB NOT NULL DEFAULT '{}'::jsonb,
    version    INTEGER NOT NULL DEFAULT 1,
    updated_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- updated_at triggers (shared function from 001_auth_system.sql).
-- ---------------------------------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at_column') THEN
        FOREACH t IN ARRAY ARRAY['operations_runs', 'operations_proposals',
                                 'tenant_operations_policies']
        LOOP
            EXECUTE format('DROP TRIGGER IF EXISTS update_%s_updated_at ON %I', t, t);
            EXECUTE format(
                'CREATE TRIGGER update_%s_updated_at BEFORE UPDATE ON %I '
                'FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()', t, t);
        END LOOP;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- TENANCY — policy + FORCE RLS + app_rw grants on every new table (ruling #2).
-- ---------------------------------------------------------------------------
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['operations_runs', 'operations_proposals',
                             'operations_events', 'tenant_operations_policies']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I '
            'USING (tenant_id = current_tenant_id()) '
            'WITH CHECK (tenant_id = current_tenant_id())', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    END LOOP;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
        FOREACH t IN ARRAY ARRAY['operations_runs', 'operations_proposals',
                                 'tenant_operations_policies']
        LOOP
            EXECUTE format('GRANT SELECT, INSERT, UPDATE ON %I TO app_rw', t);
            EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %I_id_seq TO app_rw', t);
        END LOOP;
        -- The audit log is APPEND-ONLY at the database level: the request-path
        -- role may write and read history, never rewrite it.
        GRANT SELECT, INSERT ON operations_events TO app_rw;
        GRANT USAGE, SELECT ON SEQUENCE operations_events_id_seq TO app_rw;
        REVOKE UPDATE, DELETE ON operations_events FROM app_rw;
    END IF;
END $$;

DO $$ BEGIN
    RAISE NOTICE 'operations copilot: runs/proposals/events/policies ready (FORCE RLS, append-only audit)';
END $$;
