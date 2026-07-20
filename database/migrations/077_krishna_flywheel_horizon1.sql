-- 077 — FLYWHEEL HORIZON 1: prove it.
--
-- WHY THIS EXISTS. Horizon 1 of docs/MASTER_IMPLEMENTATION_PLAN_C_LEVEL.md turns
-- a working engine into a PROVABLE one. Three capabilities need storage:
--
--   1. IMMUTABLE READOUTS. `measure()` already computes treatment-vs-control
--      correctly, but its output was ephemeral — recomputed on request, never
--      kept. You cannot argue from a number that changes every time you look at
--      it. flywheel_readouts is append-only: one row per campaign per window
--      end, forever, with the arithmetic that produced it attached.
--
--   2. ALWAYS-VALID INFERENCE. A marketer WILL refresh the incrementality page
--      and stop when it looks good. Under fixed-horizon statistics that inflates
--      the false-positive rate badly — repeated peeking at a conventional
--      p-value is the most common way honest people report lift that isn't
--      there. We store an ANYTIME-VALID confidence sequence instead, whose
--      coverage guarantee holds no matter how often it is inspected or when the
--      campaign is stopped. Paired with flywheel_preregistrations, which fixes
--      the metric, window and stopping rule BEFORE the campaign runs and cannot
--      be edited afterwards.
--
--      This matters commercially, not just statistically: the owner's ruling of
--      20 Jul 2026 puts supplier-funded trade promotion on the roadmap, which
--      means a counterparty with a contractual incentive to dispute our numbers.
--      A continuously-read fixed-horizon p-value is the first thing a competent
--      auditor attacks.
--
--   3. THE GLOBAL ALLOCATOR. optimizer.select_best() scores ONE customer in
--      isolation, but customers compete for a shared budget and shared stock.
--      Ranking by EIV under a binding budget is the fractional-knapsack error;
--      and with sequential processing, a scarce SKU goes to whoever was scored
--      first rather than whoever earns the most from it — iteration order
--      silently decides allocation. flywheel_allocation_runs/_lines records the
--      portfolio decision and, while the allocator runs in shadow, the measured
--      total-EIV delta against greedy. That delta is the value of the work.
--
-- IMMUTABILITY IS ENFORCED IN THE DATABASE, not by convention: readouts and
-- pre-registrations carry a trigger that refuses UPDATE and DELETE outright.
-- A pre-registration you can edit after seeing the result is not a
-- pre-registration.
--
-- MONEY. NUMERIC throughout; Decimal on the Python side. Probabilities and
-- statistical bounds are DOUBLE PRECISION — they are not money and are never
-- summed into a balance.
--
-- TENANCY. Every table carries tenant_id, the tenant_isolation policy and FORCE
-- RLS, consistent with migrations 012/060/075 and with ruling #2 (RLS mandatory
-- in production, no insecure escape hatch).

BEGIN;

-- ===========================================================================
-- IMMUTABILITY GUARD
--
-- UPDATE is forbidden unconditionally: a measurement you can rewrite after
-- seeing it is not evidence, and there is no legitimate reason to edit a
-- historical readout in place.
--
-- DELETE is forbidden BY DEFAULT but not absolutely, and the distinction is
-- deliberate. A blanket DELETE block looks stricter but is actively wrong:
--
--   * it breaks ON DELETE CASCADE, so deleting a campaign or offboarding a
--     tenant fails with a trigger error from a table nobody was thinking about;
--   * it makes the product non-compliant with the UAE PDPL right to erasure,
--     which this module is squarely in scope for because it profiles people
--     automatically. "We cannot delete your data, our audit table forbids it"
--     is not a defence a regulator accepts.
--
-- So erasure is possible but must be DELIBERATE: the caller sets
-- `flywheel.allow_purge` on the transaction, which no ordinary code path does.
-- Accidental deletion is blocked; lawful erasure and tenant offboarding are
-- not. The setting is transaction-scoped (set_config with is_local = true), so
-- it cannot leak into a later statement on a pooled connection.
-- ===========================================================================

CREATE OR REPLACE FUNCTION flywheel_forbid_mutation() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE'
       AND coalesce(current_setting('flywheel.allow_purge', true), 'off') = 'on' THEN
        -- Deliberate erasure / offboarding. Permitted.
        RETURN OLD;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'flywheel: % is append-only — DELETE is not permitted. Evidence is '
            'not deleted casually. For lawful erasure or tenant offboarding, set '
            'flywheel.allow_purge to ''on'' for the transaction (see '
            'services/flywheel/erasure.py).', TG_TABLE_NAME
            USING ERRCODE = 'restrict_violation';
    END IF;

    RAISE EXCEPTION
        'flywheel: % is append-only — UPDATE is not permitted. A measurement you '
        'can rewrite after seeing it is not evidence.', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

-- ===========================================================================
-- STAGE 01 — PRE-REGISTRATION
-- Fixed BEFORE the campaign runs. Immutable afterwards. This is what converts
-- "we looked at the data and found lift" into "we said what we would measure,
-- then measured it".
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_preregistrations (
    id                   SERIAL PRIMARY KEY,
    tenant_id            INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    campaign_id          INTEGER NOT NULL REFERENCES flywheel_campaigns(id) ON DELETE CASCADE,

    -- WHAT we will measure. Declared once; the readout refuses to score a
    -- different metric against this registration.
    primary_metric       VARCHAR(60) NOT NULL DEFAULT 'incremental_retention'
                           CHECK (primary_metric IN ('incremental_retention',
                                                     'incremental_margin_aed',
                                                     'incremental_margin_per_aed')),
    -- OVER WHAT WINDOW. Half-open [starts_on, starts_on + window_days).
    window_days          INTEGER NOT NULL CHECK (window_days BETWEEN 1 AND 365),

    -- WHEN WE ARE ALLOWED TO STOP. 'anytime' is honest only because the
    -- interval is a confidence SEQUENCE; with a fixed-horizon interval this
    -- would be the peeking bug in policy form.
    stopping_rule        VARCHAR(30) NOT NULL DEFAULT 'anytime'
                           CHECK (stopping_rule IN ('anytime', 'fixed_horizon')),
    alpha                DOUBLE PRECISION NOT NULL DEFAULT 0.05
                           CHECK (alpha > 0 AND alpha < 0.5),
    -- The minimum effect worth acting on. Declared up front so a statistically
    -- significant but commercially trivial lift cannot be spun as a win.
    min_detectable_effect DOUBLE PRECISION NOT NULL DEFAULT 0.02
                           CHECK (min_detectable_effect >= 0),

    -- Planned arm sizes at registration time, for later comparison against what
    -- actually materialised.
    planned_treatment_n  INTEGER NOT NULL DEFAULT 0 CHECK (planned_treatment_n >= 0),
    planned_control_n    INTEGER NOT NULL DEFAULT 0 CHECK (planned_control_n >= 0),
    control_pct          NUMERIC(5,2) NOT NULL DEFAULT 10.00
                           CHECK (control_pct >= 0 AND control_pct <= 50),

    registered_by        INTEGER REFERENCES users(id) ON DELETE SET NULL,
    registered_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes                TEXT,

    -- One live registration per campaign. Re-registering after seeing results
    -- is exactly the abuse this table exists to prevent.
    CONSTRAINT uq_flywheel_prereg_campaign UNIQUE (tenant_id, campaign_id)
);

CREATE INDEX IF NOT EXISTS idx_flywheel_prereg_campaign
    ON flywheel_preregistrations (tenant_id, campaign_id);

DROP TRIGGER IF EXISTS trg_flywheel_prereg_immutable ON flywheel_preregistrations;
CREATE TRIGGER trg_flywheel_prereg_immutable
    BEFORE UPDATE OR DELETE ON flywheel_preregistrations
    FOR EACH ROW EXECUTE FUNCTION flywheel_forbid_mutation();

-- ===========================================================================
-- STAGE 02 — IMMUTABLE READOUTS WITH AN ANYTIME-VALID INTERVAL
--
-- One row per campaign per window-end date. Recomputing the same day is a
-- no-op (ON CONFLICT DO NOTHING), so the table is a clean time series a
-- marketer can watch significance accumulate across — rather than a single
-- number that mutates under them.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_readouts (
    id                      BIGSERIAL PRIMARY KEY,
    tenant_id               INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    campaign_id             INTEGER NOT NULL REFERENCES flywheel_campaigns(id) ON DELETE CASCADE,
    preregistration_id      INTEGER REFERENCES flywheel_preregistrations(id) ON DELETE SET NULL,

    -- The measurement window this row covers. window_end is EXCLUSIVE.
    window_start            DATE NOT NULL,
    window_end              DATE NOT NULL,
    CONSTRAINT ck_flywheel_readout_window CHECK (window_end > window_start),

    -- --- arms -----------------------------------------------------------
    treatment_n             INTEGER NOT NULL CHECK (treatment_n >= 0),
    control_n               INTEGER NOT NULL CHECK (control_n >= 0),
    treatment_converted     INTEGER NOT NULL CHECK (treatment_converted >= 0),
    control_converted       INTEGER NOT NULL CHECK (control_converted >= 0),
    treatment_rate          DOUBLE PRECISION NOT NULL,
    control_rate            DOUBLE PRECISION NOT NULL,

    -- --- the point estimate ---------------------------------------------
    incremental_retention   DOUBLE PRECISION NOT NULL,

    -- --- THE ANYTIME-VALID INTERVAL --------------------------------------
    -- Coverage holds under continuous monitoring and optional stopping. These
    -- are NOT a Wald interval; see services/flywheel/sequential.py.
    ci_lower                DOUBLE PRECISION,
    ci_upper                DOUBLE PRECISION,
    ci_method               VARCHAR(40) NOT NULL DEFAULT 'eb_confseq'
                              CHECK (ci_method IN ('eb_confseq', 'none')),
    alpha                   DOUBLE PRECISION NOT NULL DEFAULT 0.05,
    -- log of the e-process. Evidence accumulates monotonically in expectation
    -- under the alternative; log is stored to avoid overflow at large n.
    log_e_value             DOUBLE PRECISION,
    -- TRUE only when the interval EXCLUDES zero. Deliberately a stored fact
    -- rather than a UI-side comparison, so "was this significant at the time"
    -- survives any later change to how we render it.
    is_significant          BOOLEAN NOT NULL DEFAULT FALSE,
    -- Significant AND at least the pre-registered minimum detectable effect.
    meets_mde               BOOLEAN NOT NULL DEFAULT FALSE,

    -- --- money (net of VAT — see services/flywheel/tax.py) ---------------
    incremental_revenue_aed NUMERIC(16,2) NOT NULL DEFAULT 0,
    incremental_margin_aed  NUMERIC(16,2) NOT NULL DEFAULT 0,
    discount_spend_aed      NUMERIC(16,2) NOT NULL DEFAULT 0,
    procurement_cost_aed    NUMERIC(16,2) NOT NULL DEFAULT 0,
    total_cost_aed          NUMERIC(16,2) NOT NULL DEFAULT 0,
    -- THE HEADLINE NUMBER. Incremental gross margin per AED of promo spend,
    -- net of VAT, against the held-out control. NULL when nothing was spent —
    -- a division-by-zero dressed as infinite ROI is worse than an honest gap.
    margin_per_aed_spent    NUMERIC(12,4),
    campaign_roi            NUMERIC(12,4),

    -- --- honesty ---------------------------------------------------------
    validity_warnings       JSONB NOT NULL DEFAULT '[]'::jsonb,
    uplift_by_segment       JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_synthetic            BOOLEAN NOT NULL DEFAULT TRUE,

    computed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    computed_by             VARCHAR(30) NOT NULL DEFAULT 'scheduler'
                              CHECK (computed_by IN ('scheduler', 'manual', 'api')),

    -- One readout per campaign per window end. Idempotent re-runs.
    CONSTRAINT uq_flywheel_readout_window UNIQUE (tenant_id, campaign_id, window_end)
);

CREATE INDEX IF NOT EXISTS idx_flywheel_readouts_campaign
    ON flywheel_readouts (tenant_id, campaign_id, window_end DESC);
CREATE INDEX IF NOT EXISTS idx_flywheel_readouts_computed
    ON flywheel_readouts (tenant_id, computed_at DESC);

DROP TRIGGER IF EXISTS trg_flywheel_readouts_immutable ON flywheel_readouts;
CREATE TRIGGER trg_flywheel_readouts_immutable
    BEFORE UPDATE OR DELETE ON flywheel_readouts
    FOR EACH ROW EXECUTE FUNCTION flywheel_forbid_mutation();

-- ===========================================================================
-- STAGE 03 — HOLDOUT COVARIATE BALANCE
--
-- If treatment and control drift apart on observable characteristics, the
-- comparison is confounded and the headline number is worthless. NOTHING in
-- the product currently detects that. Standardised mean difference is the
-- conventional diagnostic: |SMD| > 0.10 is the usual "arms are not comparable"
-- threshold.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_holdout_balance (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    campaign_id         INTEGER NOT NULL REFERENCES flywheel_campaigns(id) ON DELETE CASCADE,
    checked_on          DATE NOT NULL DEFAULT CURRENT_DATE,

    covariate           VARCHAR(60) NOT NULL,
    treatment_mean      DOUBLE PRECISION NOT NULL,
    control_mean        DOUBLE PRECISION NOT NULL,
    pooled_sd           DOUBLE PRECISION NOT NULL,
    -- (mean_t - mean_c) / pooled_sd. Sign is meaningful; magnitude is judged.
    smd                 DOUBLE PRECISION NOT NULL,
    -- The conventional threshold, stored per row so a later change of policy
    -- does not silently rewrite the history of what we considered balanced.
    threshold           DOUBLE PRECISION NOT NULL DEFAULT 0.10,
    is_balanced         BOOLEAN NOT NULL DEFAULT TRUE,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_flywheel_balance UNIQUE (tenant_id, campaign_id, checked_on, covariate)
);

CREATE INDEX IF NOT EXISTS idx_flywheel_balance_campaign
    ON flywheel_holdout_balance (tenant_id, campaign_id, checked_on DESC);

-- ===========================================================================
-- STAGE 04 — GLOBAL ALLOCATION RUNS
--
-- A portfolio decision across the whole audience under shared constraints,
-- versus the per-customer greedy path it replaces.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_allocation_runs (
    id                      BIGSERIAL PRIMARY KEY,
    tenant_id               INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    campaign_id             INTEGER NOT NULL REFERENCES flywheel_campaigns(id) ON DELETE CASCADE,

    -- 'greedy'    — legacy per-customer selection, kept for comparison.
    -- 'portfolio' — the global allocator.
    mode                    VARCHAR(20) NOT NULL
                              CHECK (mode IN ('greedy', 'portfolio')),
    -- Shadow runs compute and record but never reserve budget or stock.
    is_shadow               BOOLEAN NOT NULL DEFAULT TRUE,

    -- --- the constraints this run was solved under -----------------------
    budget_limit_aed        NUMERIC(16,2) NOT NULL DEFAULT 0,
    candidates_considered   INTEGER NOT NULL DEFAULT 0,
    customers_considered    INTEGER NOT NULL DEFAULT 0,

    -- --- the result --------------------------------------------------------
    actions_selected        INTEGER NOT NULL DEFAULT 0,
    total_eiv_aed           NUMERIC(16,2) NOT NULL DEFAULT 0,
    total_cost_aed          NUMERIC(16,2) NOT NULL DEFAULT 0,
    -- Which constraint actually bound. If none did, portfolio and greedy MUST
    -- agree — that equivalence is asserted in the test suite.
    binding_constraint      VARCHAR(30)
                              CHECK (binding_constraint IN ('budget', 'stock',
                                                            'contact_cap', 'none')),

    -- --- the value of the work --------------------------------------------
    -- Total EIV of this run minus total EIV of the greedy baseline on the SAME
    -- audience. Positive means the allocator found margin greedy left behind.
    eiv_delta_vs_greedy_aed NUMERIC(16,2),

    -- Deterministic fingerprint of the inputs. Two runs with the same digest
    -- MUST produce the same allocation — that is what makes replay() honest.
    input_digest            VARCHAR(64),
    solver                  VARCHAR(30) NOT NULL DEFAULT 'density_greedy'
                              CHECK (solver IN ('density_greedy', 'lp_relaxation',
                                                'min_cost_flow')),
    runtime_ms              INTEGER,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_flywheel_alloc_runs_campaign
    ON flywheel_allocation_runs (tenant_id, campaign_id, created_at DESC);

CREATE TABLE IF NOT EXISTS flywheel_allocation_lines (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    run_id              BIGINT NOT NULL REFERENCES flywheel_allocation_runs(id) ON DELETE CASCADE,
    customer_id         INTEGER NOT NULL REFERENCES flywheel_customers(id) ON DELETE CASCADE,

    action_type         VARCHAR(30) NOT NULL,
    item_id             INTEGER REFERENCES items(id) ON DELETE SET NULL,
    store_id            INTEGER REFERENCES stores(id) ON DELETE SET NULL,
    discount_pct        NUMERIC(5,2) NOT NULL DEFAULT 0,
    units               INTEGER NOT NULL DEFAULT 1 CHECK (units >= 0),

    eiv_aed             NUMERIC(16,2) NOT NULL DEFAULT 0,
    cost_aed            NUMERIC(16,2) NOT NULL DEFAULT 0,
    -- EIV per AED committed. THE ranking key under a binding budget — ranking
    -- on raw EIV instead is the fractional-knapsack error this table exists to
    -- make visible. NULL for zero-cost actions, which are ranked separately.
    eiv_density         NUMERIC(12,4),

    selected            BOOLEAN NOT NULL DEFAULT FALSE,
    -- Why it lost. 'LOST_TO_HIGHER_DENSITY' is the rejection class that only
    -- exists once allocation is global — under per-customer greedy there was
    -- no competitor to lose to.
    reason_code         VARCHAR(40),
    -- What it lost to, when it lost to a specific rival claim on a resource.
    displaced_by_line   BIGINT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_flywheel_alloc_lines_run
    ON flywheel_allocation_lines (tenant_id, run_id, selected);
CREATE INDEX IF NOT EXISTS idx_flywheel_alloc_lines_customer
    ON flywheel_allocation_lines (tenant_id, customer_id);

-- ===========================================================================
-- STAGE 05 — SHADOW MODE
--
-- Ruling #1 of 20 Jul 2026: the deterministic rule tier is the production
-- decision path; ML runs in shadow and is promoted only when a pre-registered
-- holdout beats rules with a confidence interval excluding zero.
--
-- The models are currently NOT distinguishable from noise (three training runs
-- produced three different winners; Qini swung +1.13 to -3.80 at n=300 with
-- ~16 positives in the test split). This table is what turns that from a hidden
-- liability into a governed, evidenced process.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_shadow_decisions (
    id                      BIGSERIAL PRIMARY KEY,
    tenant_id               INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    campaign_id             INTEGER REFERENCES flywheel_campaigns(id) ON DELETE CASCADE,
    customer_id             INTEGER NOT NULL REFERENCES flywheel_customers(id) ON DELETE CASCADE,
    decision_id             INTEGER REFERENCES flywheel_decisions(id) ON DELETE SET NULL,

    model_version_id        INTEGER REFERENCES flywheel_model_versions(id) ON DELETE SET NULL,
    model_label             VARCHAR(60) NOT NULL,

    -- What SHIPPED (rules) versus what the model WOULD have done.
    rule_action             VARCHAR(30) NOT NULL,
    rule_discount_pct       NUMERIC(5,2) NOT NULL DEFAULT 0,
    rule_eiv_aed            NUMERIC(16,2) NOT NULL DEFAULT 0,
    rule_churn_probability  DOUBLE PRECISION,

    shadow_action           VARCHAR(30) NOT NULL,
    shadow_discount_pct     NUMERIC(5,2) NOT NULL DEFAULT 0,
    shadow_eiv_aed          NUMERIC(16,2) NOT NULL DEFAULT 0,
    shadow_churn_probability DOUBLE PRECISION,

    -- The headline diagnostic. High disagreement is not automatically bad — but
    -- unexplained high disagreement blocks promotion.
    agreed                  BOOLEAN NOT NULL DEFAULT TRUE,
    disagreement_kind       VARCHAR(30)
                              CHECK (disagreement_kind IN ('action', 'magnitude',
                                                           'both', NULL)),

    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_flywheel_shadow UNIQUE (tenant_id, customer_id, campaign_id, model_label)
);

CREATE INDEX IF NOT EXISTS idx_flywheel_shadow_campaign
    ON flywheel_shadow_decisions (tenant_id, campaign_id, agreed);
CREATE INDEX IF NOT EXISTS idx_flywheel_shadow_model
    ON flywheel_shadow_decisions (tenant_id, model_label, created_at DESC);

-- Standing record of whether a model has EARNED promotion. One row per model
-- label; updated as evidence accrues. Mutable by design — this is a scoreboard,
-- not evidence; the evidence is in flywheel_readouts, which is not mutable.
CREATE TABLE IF NOT EXISTS flywheel_promotion_criteria (
    id                      SERIAL PRIMARY KEY,
    tenant_id               INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    model_label             VARCHAR(60) NOT NULL,

    -- The pre-registered bar, fixed before evidence is gathered.
    min_readouts_required   INTEGER NOT NULL DEFAULT 2 CHECK (min_readouts_required >= 1),
    min_ci_lower            DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    max_disagreement_rate   DOUBLE PRECISION NOT NULL DEFAULT 0.35,

    -- Current standing against that bar.
    readouts_passed         INTEGER NOT NULL DEFAULT 0,
    current_disagreement_rate DOUBLE PRECISION,
    eligible_for_promotion  BOOLEAN NOT NULL DEFAULT FALSE,
    blocked_reason          TEXT,

    status                  VARCHAR(20) NOT NULL DEFAULT 'shadow'
                              CHECK (status IN ('shadow', 'candidate', 'promoted', 'retired')),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_flywheel_promotion UNIQUE (tenant_id, model_label)
);

-- ===========================================================================
-- TENANCY — policy + FORCE RLS on every new table (migrations 012/060/075).
-- ===========================================================================

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'flywheel_preregistrations', 'flywheel_readouts', 'flywheel_holdout_balance',
        'flywheel_allocation_runs', 'flywheel_allocation_lines',
        'flywheel_shadow_decisions', 'flywheel_promotion_criteria'
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

-- ===========================================================================
-- SEED — the promotion bar for the models currently in shadow.
--
-- Guarded on tenant 1 existing so a fresh deploy against an empty database does
-- not fail here (the lesson from migration 074's NULL home_store_id).
-- ===========================================================================

INSERT INTO flywheel_promotion_criteria
    (tenant_id, model_label, min_readouts_required, min_ci_lower,
     max_disagreement_rate, status, blocked_reason)
SELECT 1, label, 2, 0.0, 0.35, 'shadow',
       'Awaiting evidence: model ranking is unstable at current data volume '
       '(three training runs produced three different winners; Qini ranged '
       '+1.13 to -3.80 at n=300). Promotion requires 2 consecutive readouts '
       'with a confidence-sequence lower bound above zero.'
  FROM (VALUES ('lightgbm_churn'), ('gru_sequence'), ('ft_transformer')) AS m(label)
 WHERE EXISTS (SELECT 1 FROM tenants WHERE id = 1)
ON CONFLICT (tenant_id, model_label) DO NOTHING;

COMMIT;
