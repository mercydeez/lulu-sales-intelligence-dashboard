-- 025_finding_actions.sql
-- Agentic layer, autonomy level 0 — SUGGEST ONLY (PRODUCT_BUILD_PLAN.md A4).
--
-- Each finding carries a recommended next action and a coarse action_type. The
-- system never acts on its own: an operator accepts (which records the decision)
-- or resolves. This is the deliberately-slow first step toward a system of action;
-- higher autonomy (auto-drafting POs/alerts) builds on this contract later.

ALTER TABLE findings ADD COLUMN IF NOT EXISTS recommended_action TEXT;
-- action_type groups the suggested follow-up: review_pricing | review_supplier |
-- investigate | restock | promote | none. Drives which action a future increment drafts.
ALTER TABLE findings ADD COLUMN IF NOT EXISTS action_type TEXT NOT NULL DEFAULT 'investigate';
-- Who accepted the recommendation, and when (decision audit trail).
ALTER TABLE findings ADD COLUMN IF NOT EXISTS action_accepted_at TIMESTAMPTZ;
ALTER TABLE findings ADD COLUMN IF NOT EXISTS action_accepted_by TEXT;

DO $$ BEGIN RAISE NOTICE 'findings: recommended_action / action_type columns added (A4 suggest-only)'; END $$;
