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
-- AUDIT INTEGRITY (hardened after Phase-1 review). The audit log is append-only
-- at the DATABASE level, and — critically — cannot be erased by CASCADE either:
--   * app_rw is denied UPDATE and DELETE on operations_events,
--   * app_rw is denied DELETE on runs and proposals (so the request path can
--     never delete a parent to cascade the children away), and
--   * operations_events references its run/proposal with ON DELETE NO ACTION, so
--     even an owner-level DELETE of a run that still has audit events is refused
--     by referential integrity rather than silently cascading.
-- Deleting a finding SET NULLs the run's finding_id — the run and its audit
-- survive the finding that spawned them.
--
-- TENANT-SAFE FKS. Intra-module references are COMPOSITE (tenant_id, id) against
-- a UNIQUE (tenant_id, id) on the parent, so a row in one tenant cannot point at
-- another tenant's run/proposal (an FK check bypasses RLS; a plain id FK would
-- let a crafted insert join across tenants). All four tables carry FORCE RLS.
-- Idempotency follows the flywheel precedent: partial unique (tenant_id, key).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- operations_runs — one agent run over one finding. `state` IS the checkpoint:
-- the graph is invoked twice (recommend, then execute-after-approval) and never
-- holds a web request open waiting for a human.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operations_runs (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    -- Finding deletion preserves the run + its audit trail (SET NULL, not CASCADE).
    finding_id      BIGINT REFERENCES findings(id) ON DELETE SET NULL,
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
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Target for the composite FKs from proposals/events (tenant-safe references).
    CONSTRAINT uq_operations_runs_tenant_id UNIQUE (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS ix_operations_runs_tenant_status
    ON operations_runs (tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_operations_runs_finding
    ON operations_runs (tenant_id, finding_id);
-- At most ONE live run per finding: re-triggering returns the existing run
-- instead of racing two graphs over the same problem. NULLS NOT DISTINCT so a
-- finding-less ad-hoc run cannot spawn unbounded concurrent duplicates either.
CREATE UNIQUE INDEX IF NOT EXISTS uq_operations_runs_live_finding
    ON operations_runs (tenant_id, finding_id)
    WHERE status IN ('analyzing', 'awaiting_approval', 'executing', 'measuring');

-- ---------------------------------------------------------------------------
-- operations_proposals — the human-approvable artifact. `recommendation` holds
-- the full OperationsRecommendation contract (evidence, measured facts,
-- hypotheses, assumptions, risks, missing data) exactly as validated in Python.
-- `version` is optimistic concurrency: an approval carrying a stale version is
-- rejected rather than silently overwriting a concurrent decision. The version
-- is bumped by a trigger (below) so no writer can forget to advance it.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operations_proposals (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    run_id              BIGINT NOT NULL,
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
    -- Recomputed from policy at approval time; the stored value is a record, not
    -- a trusted gate (CHECK keeps a model from persisting a bogus role string).
    required_approval_role TEXT NOT NULL
                        CHECK (required_approval_role IN
                               ('analyst','store_manager','regional_manager','super_admin')),
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
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_operations_proposals_tenant_id UNIQUE (tenant_id, id),
    -- Tenant-safe reference: a proposal cannot point at another tenant's run.
    CONSTRAINT fk_operations_proposals_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES operations_runs (tenant_id, id) ON DELETE CASCADE
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
-- append a new event; history is never edited (UPDATE/DELETE revoked below) and
-- never cascade-deleted (NO ACTION references + no DELETE on the parents).
-- Stores structured facts only — never model chain-of-thought, never prompts.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operations_events (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    run_id       BIGINT NOT NULL,
    proposal_id  BIGINT,
    event_type   TEXT NOT NULL,          -- run.created | evidence.gathered | proposal.created | approval.granted | ...
    actor        TEXT,                   -- 'system' or the acting user's email
    actor_user_id INTEGER,
    payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
    request_id   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- NO ACTION (not CASCADE): a run/proposal that still has audit events cannot
    -- be deleted at all — referential integrity refuses it. This is what makes
    -- the log tamper-evident against the delete-the-parent cascade path.
    CONSTRAINT fk_operations_events_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES operations_runs (tenant_id, id) ON DELETE NO ACTION,
    CONSTRAINT fk_operations_events_proposal
        FOREIGN KEY (tenant_id, proposal_id)
        REFERENCES operations_proposals (tenant_id, id) ON DELETE NO ACTION
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
-- Triggers. runs + policies get the shared updated_at touch. proposals get a
-- dedicated trigger that ALSO advances `version` on every UPDATE, so optimistic
-- concurrency is a database property no application writer can forget.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION operations_proposal_touch() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := now();
    -- Only advance when the caller did not already bump it (lets a compare-and-
    -- swap `SET version = version + 1 WHERE version = :expected` stay exact).
    IF NEW.version = OLD.version THEN
        NEW.version := OLD.version + 1;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE t TEXT;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at_column') THEN
        FOREACH t IN ARRAY ARRAY['operations_runs', 'tenant_operations_policies']
        LOOP
            EXECUTE format('DROP TRIGGER IF EXISTS update_%s_updated_at ON %I', t, t);
            EXECUTE format(
                'CREATE TRIGGER update_%s_updated_at BEFORE UPDATE ON %I '
                'FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()', t, t);
        END LOOP;
    END IF;
    DROP TRIGGER IF EXISTS touch_operations_proposals ON operations_proposals;
    CREATE TRIGGER touch_operations_proposals BEFORE UPDATE ON operations_proposals
        FOR EACH ROW EXECUTE FUNCTION operations_proposal_touch();
END $$;

-- ---------------------------------------------------------------------------
-- TENANCY — policy + FORCE RLS + least-privilege grants (ruling #2). The audit
-- log and the parents are protected against deletion so history cannot be erased
-- by the request-path role.
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
        -- Policies are freely editable configuration.
        GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_operations_policies TO app_rw;
        GRANT USAGE, SELECT ON SEQUENCE tenant_operations_policies_id_seq TO app_rw;
        -- Runs and proposals: writable but NOT deletable by the request path, so
        -- a parent cannot be removed to cascade audit history away.
        GRANT SELECT, INSERT, UPDATE ON operations_runs TO app_rw;
        GRANT SELECT, INSERT, UPDATE ON operations_proposals TO app_rw;
        GRANT USAGE, SELECT ON SEQUENCE operations_runs_id_seq TO app_rw;
        GRANT USAGE, SELECT ON SEQUENCE operations_proposals_id_seq TO app_rw;
        REVOKE DELETE ON operations_runs FROM app_rw;
        REVOKE DELETE ON operations_proposals FROM app_rw;
        -- The audit log is APPEND-ONLY: write and read, never rewrite or delete.
        GRANT SELECT, INSERT ON operations_events TO app_rw;
        GRANT USAGE, SELECT ON SEQUENCE operations_events_id_seq TO app_rw;
        REVOKE UPDATE, DELETE ON operations_events FROM app_rw;
    END IF;
END $$;

DO $$ BEGIN
    RAISE NOTICE 'operations copilot: runs/proposals/events/policies ready (FORCE RLS, tamper-evident audit, tenant-safe FKs)';
END $$;
