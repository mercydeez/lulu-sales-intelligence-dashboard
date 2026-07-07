-- =============================================================================
-- 051_yash_user_feedback.sql  (CX feedback loop — Y6, docs/product/CX_LOOPS_PLAN.md)
-- One table for both signals: NPS pulses (kind='nps', score 0–10) and free-form
-- product feedback (kind='feedback', comment). Append-only from the app's
-- perspective; tenant-scoped with the standard RLS policy. Deliberately tiny —
-- funnels/retention analysis live in the telemetry stack, this is the
-- customer's voice with a durable home.
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_feedback (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('nps', 'feedback')),
    score       SMALLINT CHECK (score BETWEEN 0 AND 10),  -- NPS only; NULL for feedback
    comment     TEXT,
    page        TEXT,                                     -- route it was sent from
    created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- NPS needs a score; free-form feedback needs a comment.
ALTER TABLE user_feedback DROP CONSTRAINT IF EXISTS user_feedback_payload_check;
ALTER TABLE user_feedback ADD CONSTRAINT user_feedback_payload_check
    CHECK ((kind = 'nps' AND score IS NOT NULL) OR (kind = 'feedback' AND comment IS NOT NULL));

CREATE INDEX IF NOT EXISTS ix_user_feedback_tenant_time
    ON user_feedback (tenant_id, created_at DESC);

ALTER TABLE user_feedback ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON user_feedback;
CREATE POLICY tenant_isolation ON user_feedback
    USING (tenant_id = current_tenant_id()) WITH CHECK (tenant_id = current_tenant_id());
