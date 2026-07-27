-- 062 — E8-5: a customer can dispute a confirmed value realization.
--
-- Outcome pricing bills a share of value the customer CONFIRMED we created. The
-- whole model rests on that confirmation being theirs to give — and therefore
-- theirs to take back. Without a dispute state the only way to contest a line on
-- the invoice was to flip it to 'dismissed', which destroyed the confirmed amount
-- and the audit trail of what was originally agreed.
--
-- The new state is 'disputed':
--
--     confirmed  --dispute(reason)-->  disputed
--     disputed   --resolve(accepted)-->  dismissed   (customer was right; not billed)
--     disputed   --resolve(rejected)-->  confirmed   (value stands; billed again)
--
-- BILLING IMPACT: `confirmed_value_total` sums WHERE status = 'confirmed', so a
-- disputed row leaves the billable total the moment it is disputed — we do not
-- invoice contested value while it is contested. `confirmed_value_aed` is kept on
-- the row throughout, so resolving a dispute restores the original figure rather
-- than a re-keyed one.

BEGIN;

ALTER TABLE value_realizations
    ADD COLUMN IF NOT EXISTS dispute_reason TEXT,
    ADD COLUMN IF NOT EXISTS disputed_at    TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS disputed_by    TEXT;

-- Widen the status domain. Migration 049 declared the CHECK inline on the column,
-- so Postgres named it <table>_<column>_check — deterministic, and the same name
-- we re-add below, which keeps this migration re-runnable.
ALTER TABLE value_realizations
    DROP CONSTRAINT IF EXISTS value_realizations_status_check;
ALTER TABLE value_realizations
    ADD CONSTRAINT value_realizations_status_check
    CHECK (status IN ('pending', 'confirmed', 'dismissed', 'disputed'));

-- A dispute without a reason is unactionable — nobody can resolve "no".
ALTER TABLE value_realizations
    DROP CONSTRAINT IF EXISTS value_realizations_dispute_needs_reason;
ALTER TABLE value_realizations
    ADD CONSTRAINT value_realizations_dispute_needs_reason
    CHECK (
        status <> 'disputed'
        OR (dispute_reason IS NOT NULL AND length(btrim(dispute_reason)) > 0)
    );

-- Only ever billed value can be contested, so a disputed row must carry the
-- amount that was billed. This also guarantees resolving a dispute back to
-- 'confirmed' restores a real number instead of a NULL.
ALTER TABLE value_realizations
    DROP CONSTRAINT IF EXISTS value_realizations_dispute_keeps_amount;
ALTER TABLE value_realizations
    ADD CONSTRAINT value_realizations_dispute_keeps_amount
    CHECK (status <> 'disputed' OR confirmed_value_aed IS NOT NULL);

-- The statement query filters on status; disputes are read by tenant + state.
CREATE INDEX IF NOT EXISTS ix_value_realizations_disputed
    ON value_realizations (tenant_id, disputed_at DESC)
    WHERE status = 'disputed';

COMMIT;

DO $$ BEGIN
    RAISE NOTICE 'outcome pricing: disputed state added; disputed value leaves the billable total';
END $$;
