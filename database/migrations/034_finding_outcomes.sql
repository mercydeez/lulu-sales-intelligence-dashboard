-- 034_finding_outcomes.sql
-- Close the intelligence loop: detect → diagnose → recommend → accept → MEASURE.
--
-- Until now, accepting a recommendation recorded the human decision but nothing
-- checked whether the underlying metric actually recovered. These columns let the
-- worker's `measure` job re-evaluate an accepted finding against the current window
-- and record the outcome: did the problem go away?
--
--   outcome_status  pending  — accepted, not yet measured (default)
--                   improved — the rule no longer fires for this entity → auto-resolved
--                   unchanged — still firing, metric flat or recovering (not yet cleared)
--                   worsened — still firing and the metric moved the wrong way
--   metric_before   the finding's headline metric at detection (captured on first measure)
--   metric_after    the same metric on the most recent measurement (NULL once recovered)
--   measured_at     when the worker last measured this finding
--
-- The worker writes these as `worker_rw`, which already has UPDATE on findings
-- (migration 029); no new grants needed.

ALTER TABLE findings ADD COLUMN IF NOT EXISTS outcome_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (outcome_status IN ('pending', 'improved', 'unchanged', 'worsened'));
ALTER TABLE findings ADD COLUMN IF NOT EXISTS metric_before NUMERIC;
ALTER TABLE findings ADD COLUMN IF NOT EXISTS metric_after  NUMERIC;
ALTER TABLE findings ADD COLUMN IF NOT EXISTS measured_at   TIMESTAMPTZ;

-- The measure job scans for accepted, not-yet-resolved findings; index that access path.
CREATE INDEX IF NOT EXISTS idx_findings_measure
    ON findings (tenant_id, measured_at)
    WHERE action_accepted_at IS NOT NULL AND status <> 'resolved';

DO $$ BEGIN RAISE NOTICE 'findings: outcome_status / metric_before / metric_after / measured_at added (measure loop)'; END $$;
