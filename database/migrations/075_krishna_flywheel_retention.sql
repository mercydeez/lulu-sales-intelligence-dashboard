-- 074 — FLYWHEEL AI: the closed-loop retention & commercial orchestration module.
--
-- WHY. Retail IQ can tell you what sold. It cannot tell you which CUSTOMER is
-- about to leave, whether an offer would actually change that, whether the shelf
-- and the budget can carry the offer, who must approve it, or what the campaign
-- truly earned versus a control group. Flywheel ("", the loop) closes that loop.
--
-- THE GOVERNING RULE, ENCODED IN THE SCHEMA: models propose, services dispose.
-- Nothing in here lets a model move money or stock. Scores land in prediction
-- tables; money moves only through flywheel_budget_ledger rows written by a
-- deterministic service inside a row-locked transaction, and stock moves only
-- through allocations/reservations checked against real inventory.
--
-- REUSE, DON'T FORK (see docs/flywheel/00_gap_analysis.md):
--   * inventory / inventory_transactions  — stock truth stays there; we add a
--     soft-allocation + reservation layer ON TOP, never a parallel stock table.
--   * suppliers / product_suppliers / purchase_orders — requisitions aggregate
--     into the EXISTING procurement structures (lead_time_days, moq, unit_cost).
--   * item_costs — effective-dated unit COST is already the source of truth for
--     margin. Flywheel snapshots it per decision so history stays explainable.
--   * items.unit_price_aed — price. VOLUME is units, VALUE is AED, never mixed.
--   * audit_log — every decision/approval/ledger event is written there too.
--
-- MONEY. Every monetary column is NUMERIC (never float/double). The Python side
-- uses Decimal end to end. Quantities are INTEGER units.
--
-- TENANCY. Every table carries tenant_id and gets the same `tenant_isolation`
-- policy + FORCE RLS as migration 012/060, binding to current_tenant_id().
--
-- SYNTHETIC. Customers are generated with a fixed seed and stamped
-- is_synthetic = TRUE, confined to the demo tenant (the E0-8 precedent).

BEGIN;

-- ===========================================================================
-- STAGE 01 — DATA FOUNDATION: customers, consent, events, attributions
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_customers (
    id                SERIAL PRIMARY KEY,
    tenant_id         INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    external_ref      VARCHAR(64) NOT NULL,
    display_name      VARCHAR(120) NOT NULL,
    -- Home store drives store-scope access (region -> store expansion upstream).
    home_store_id     INTEGER NOT NULL REFERENCES stores(id) ON DELETE RESTRICT,
    -- The generator's behavioural archetype. Kept for HONEST evaluation only —
    -- it is deliberately NOT a model feature (that would be label leakage) and
    -- never an offer-decision input.
    archetype         VARCHAR(40) NOT NULL,
    enrolled_on       DATE NOT NULL,
    -- Loyalty tier is behavioural (spend-derived), not demographic.
    loyalty_tier      VARCHAR(20) NOT NULL DEFAULT 'standard'
                        CHECK (loyalty_tier IN ('standard', 'silver', 'gold', 'platinum')),
    status            VARCHAR(20) NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'dormant', 'churned', 'opted_out')),
    -- NO sensitive attributes by design: no gender, ethnicity, religion or
    -- nationality is stored here or used anywhere downstream. See the fairness
    -- note in docs/flywheel/model_card.md.
    is_synthetic      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_flywheel_customer_ref UNIQUE (tenant_id, external_ref)
);
CREATE INDEX IF NOT EXISTS ix_flywheel_customers_tenant ON flywheel_customers (tenant_id);
CREATE INDEX IF NOT EXISTS ix_flywheel_customers_store  ON flywheel_customers (home_store_id);
CREATE INDEX IF NOT EXISTS ix_flywheel_customers_status ON flywheel_customers (tenant_id, status);

COMMENT ON TABLE flywheel_customers IS
    'Synthetic customer identity layer for Flywheel retention. Fixed-seed generated; '
    'never contains real personal data and never stores sensitive attributes.';

-- Consent is a HARD GATE on every promotional contact (§16 of the brief).
CREATE TABLE IF NOT EXISTS flywheel_customer_consents (
    id             SERIAL PRIMARY KEY,
    tenant_id      INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_id    INTEGER NOT NULL REFERENCES flywheel_customers(id) ON DELETE CASCADE,
    channel        VARCHAR(20) NOT NULL
                     CHECK (channel IN ('email', 'sms', 'push', 'in_store', 'app')),
    granted        BOOLEAN NOT NULL DEFAULT TRUE,
    -- Contact-frequency cap: the customer's own limit, independent of campaign caps.
    max_contacts_per_week INTEGER NOT NULL DEFAULT 3 CHECK (max_contacts_per_week >= 0),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_flywheel_consent UNIQUE (tenant_id, customer_id, channel)
);
CREATE INDEX IF NOT EXISTS ix_flywheel_consents_customer ON flywheel_customer_consents (customer_id);

-- Ordered behavioural event log — the SEQUENCE the GRU/Transformer learns from.
-- This is exactly the structure a flattened tabular snapshot throws away.
CREATE TABLE IF NOT EXISTS flywheel_customer_events (
    id             BIGSERIAL PRIMARY KEY,
    tenant_id      INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_id    INTEGER NOT NULL REFERENCES flywheel_customers(id) ON DELETE CASCADE,
    event_type     VARCHAR(30) NOT NULL
                     CHECK (event_type IN ('purchase', 'return', 'visit', 'offer_seen',
                                           'offer_redeemed', 'offer_ignored', 'complaint',
                                           'support_contact')),
    occurred_at    TIMESTAMPTZ NOT NULL,
    store_id       INTEGER REFERENCES stores(id) ON DELETE SET NULL,
    item_id        INTEGER REFERENCES items(id) ON DELETE SET NULL,
    category       VARCHAR(50),
    -- VOLUME in units; VALUE in AED. Never mixed on one axis (project convention).
    quantity_units INTEGER NOT NULL DEFAULT 0,
    value_aed      NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (value_aed >= 0),
    margin_aed     NUMERIC(14,2) NOT NULL DEFAULT 0,
    metadata       JSONB NOT NULL DEFAULT '{}',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- The sequence models read (customer, occurred_at) in order — index accordingly.
CREATE INDEX IF NOT EXISTS ix_flywheel_events_seq
    ON flywheel_customer_events (tenant_id, customer_id, occurred_at);
CREATE INDEX IF NOT EXISTS ix_flywheel_events_type
    ON flywheel_customer_events (tenant_id, event_type, occurred_at);

-- Links a synthetic customer event back to the REAL source sale row it was
-- attributed from, so the customer layer never corrupts existing sales facts —
-- it references them. sale_source distinguishes the two halves of sales_fact_view.
CREATE TABLE IF NOT EXISTS flywheel_purchase_attributions (
    id             BIGSERIAL PRIMARY KEY,
    tenant_id      INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    event_id       BIGINT NOT NULL REFERENCES flywheel_customer_events(id) ON DELETE CASCADE,
    sale_source    VARCHAR(20) NOT NULL CHECK (sale_source IN ('historical', 'stream')),
    sale_id        BIGINT NOT NULL,
    attributed_units INTEGER NOT NULL CHECK (attributed_units > 0),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_flywheel_attr_event ON flywheel_purchase_attributions (event_id);
CREATE INDEX IF NOT EXISTS ix_flywheel_attr_sale
    ON flywheel_purchase_attributions (tenant_id, sale_source, sale_id);

-- ===========================================================================
-- STAGE 02 — INTELLIGENCE: model registry, feature snapshots, predictions
-- ===========================================================================

-- One row per trained (or rule-based) artifact. Predictions reference it so a
-- historical decision stays explainable after the model is retrained.
CREATE TABLE IF NOT EXISTS flywheel_model_versions (
    id                SERIAL PRIMARY KEY,
    tenant_id         INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    model_kind        VARCHAR(30) NOT NULL
                        CHECK (model_kind IN ('churn', 'uplift', 'sequence', 'tabular_dl', 'ensemble')),
    algorithm         VARCHAR(60) NOT NULL,   -- 'rule_based' | 'lightgbm' | 'gru' | 'ft_transformer' | 't_learner'
    version_label     VARCHAR(40) NOT NULL,
    -- Fixed seed + explicit windows: reproducibility and leakage control (§8.4).
    random_seed       INTEGER NOT NULL DEFAULT 42,
    feature_window_days INTEGER NOT NULL,
    outcome_window_days INTEGER NOT NULL,
    feature_list      JSONB NOT NULL DEFAULT '[]',
    metrics           JSONB NOT NULL DEFAULT '{}',  -- pr_auc, roc_auc, brier, qini...
    artifact_path     TEXT,                          -- NULL for rule_based
    trained_at        TIMESTAMPTZ,
    is_active         BOOLEAN NOT NULL DEFAULT FALSE,
    notes             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_flywheel_model_version UNIQUE (tenant_id, model_kind, version_label)
);
CREATE INDEX IF NOT EXISTS ix_flywheel_models_active
    ON flywheel_model_versions (tenant_id, model_kind, is_active);

-- PROOF CHECK: a trained (non-rule-based) artifact must carry its training date.
-- A model claiming to be trained without a timestamp is not auditable.
ALTER TABLE flywheel_model_versions DROP CONSTRAINT IF EXISTS flywheel_model_trained_has_timestamp;
ALTER TABLE flywheel_model_versions
    ADD CONSTRAINT flywheel_model_trained_has_timestamp
    CHECK (algorithm = 'rule_based' OR trained_at IS NOT NULL);

-- Point-in-time engineered features. Snapshotted (not recomputed) so a decision
-- can be replayed exactly. as_of_date is the feature-window cutoff.
CREATE TABLE IF NOT EXISTS flywheel_feature_snapshots (
    id                   BIGSERIAL PRIMARY KEY,
    tenant_id            INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_id          INTEGER NOT NULL REFERENCES flywheel_customers(id) ON DELETE CASCADE,
    as_of_date           DATE NOT NULL,
    recency_days         INTEGER NOT NULL,
    frequency_90d        INTEGER NOT NULL,
    monetary_90d_aed     NUMERIC(14,2) NOT NULL DEFAULT 0,
    avg_basket_aed       NUMERIC(14,2) NOT NULL DEFAULT 0,
    spend_drift_ratio    NUMERIC(8,4) NOT NULL DEFAULT 1,   -- recent/baseline spend
    interpurchase_gap_days NUMERIC(8,2) NOT NULL DEFAULT 0,
    gap_volatility       NUMERIC(8,4) NOT NULL DEFAULT 0,
    category_diversity   INTEGER NOT NULL DEFAULT 0,
    return_ratio         NUMERIC(6,4) NOT NULL DEFAULT 0,
    promo_response_rate  NUMERIC(6,4) NOT NULL DEFAULT 0,
    tenure_days          INTEGER NOT NULL DEFAULT 0,
    events_90d           INTEGER NOT NULL DEFAULT 0,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_flywheel_features UNIQUE (tenant_id, customer_id, as_of_date)
);
CREATE INDEX IF NOT EXISTS ix_flywheel_features_asof
    ON flywheel_feature_snapshots (tenant_id, as_of_date);

CREATE TABLE IF NOT EXISTS flywheel_churn_predictions (
    id                BIGSERIAL PRIMARY KEY,
    tenant_id         INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_id       INTEGER NOT NULL REFERENCES flywheel_customers(id) ON DELETE CASCADE,
    model_version_id  INTEGER NOT NULL REFERENCES flywheel_model_versions(id) ON DELETE RESTRICT,
    as_of_date        DATE NOT NULL,
    churn_probability NUMERIC(6,5) NOT NULL CHECK (churn_probability BETWEEN 0 AND 1),
    risk_band         VARCHAR(10) NOT NULL CHECK (risk_band IN ('low', 'medium', 'high', 'critical')),
    -- Human-readable drivers (SHAP for trees, attention/embedding for sequence).
    reason_codes      JSONB NOT NULL DEFAULT '[]',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_flywheel_churn_pred UNIQUE (tenant_id, customer_id, as_of_date, model_version_id)
);
CREATE INDEX IF NOT EXISTS ix_flywheel_churn_lookup
    ON flywheel_churn_predictions (tenant_id, as_of_date, churn_probability DESC);

-- Uplift is a SEPARATE question from churn: "would an offer change the outcome?"
-- A high churn score alone must never trigger a discount (§5).
CREATE TABLE IF NOT EXISTS flywheel_offer_response_predictions (
    id                 BIGSERIAL PRIMARY KEY,
    tenant_id          INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_id        INTEGER NOT NULL REFERENCES flywheel_customers(id) ON DELETE CASCADE,
    model_version_id   INTEGER NOT NULL REFERENCES flywheel_model_versions(id) ON DELETE RESTRICT,
    action_type        VARCHAR(30) NOT NULL,
    as_of_date         DATE NOT NULL,
    treated_response   NUMERIC(6,5) NOT NULL CHECK (treated_response BETWEEN 0 AND 1),
    control_response   NUMERIC(6,5) NOT NULL CHECK (control_response BETWEEN 0 AND 1),
    -- uplift = treated - control. May legitimately be NEGATIVE (offer backfires).
    uplift             NUMERIC(7,5) NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_flywheel_uplift_pred
        UNIQUE (tenant_id, customer_id, action_type, as_of_date, model_version_id)
);
CREATE INDEX IF NOT EXISTS ix_flywheel_uplift_lookup
    ON flywheel_offer_response_predictions (tenant_id, as_of_date, uplift DESC);

-- ===========================================================================
-- STAGE 03/04 — CAMPAIGNS, the persisted STATE MACHINE, audience & budget
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_campaigns (
    id                   SERIAL PRIMARY KEY,
    tenant_id            INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name                 VARCHAR(200) NOT NULL,
    objective            VARCHAR(40) NOT NULL
                           CHECK (objective IN ('retain_at_risk', 'reactivate_lapsed',
                                                'grow_basket', 'protect_margin')),
    -- The state machine. Transitions are validated in services/flywheel/campaign_state.py;
    -- the CHECK only constrains the VALUE SET, never the legality of a jump.
    status               VARCHAR(30) NOT NULL DEFAULT 'DRAFT'
                           CHECK (status IN ('DRAFT', 'AUDIENCE_READY', 'SIMULATED',
                                             'PENDING_INVENTORY_REVIEW', 'PENDING_PROCUREMENT_REVIEW',
                                             'PENDING_FINANCE_APPROVAL', 'PENDING_MARKETING_APPROVAL',
                                             'APPROVED', 'SCHEDULED', 'ACTIVE', 'PAUSED',
                                             'COMPLETED', 'CANCELLED', 'MEASURED')),
    starts_on            DATE NOT NULL,
    ends_on              DATE NOT NULL,
    channel              VARCHAR(20) NOT NULL DEFAULT 'email'
                           CHECK (channel IN ('email', 'sms', 'push', 'in_store', 'app')),
    -- Policy envelope. The optimizer may never propose outside these bounds.
    max_discount_pct     NUMERIC(5,2) NOT NULL DEFAULT 20 CHECK (max_discount_pct BETWEEN 0 AND 90),
    min_margin_pct       NUMERIC(5,2) NOT NULL DEFAULT 10 CHECK (min_margin_pct BETWEEN 0 AND 100),
    discount_budget_aed  NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (discount_budget_aed >= 0),
    procurement_budget_aed NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (procurement_budget_aed >= 0),
    safety_stock_pct     NUMERIC(5,2) NOT NULL DEFAULT 10 CHECK (safety_stock_pct BETWEEN 0 AND 100),
    control_group_pct    NUMERIC(5,2) NOT NULL DEFAULT 20 CHECK (control_group_pct BETWEEN 0 AND 50),
    contact_cap_per_week INTEGER NOT NULL DEFAULT 2 CHECK (contact_cap_per_week >= 0),
    -- Audience selector (segment rules, candidate items/categories, store scope).
    audience_spec        JSONB NOT NULL DEFAULT '{}',
    -- Which policy revision judged this campaign — pinned for auditability.
    policy_version       VARCHAR(20) NOT NULL DEFAULT 'v1',
    -- Populated by the guardrail engine when it auto-pauses (§22).
    pause_reason         TEXT,
    paused_at            TIMESTAMPTZ,
    created_by           INTEGER REFERENCES users(id) ON DELETE SET NULL,
    activated_at         TIMESTAMPTZ,
    completed_at         TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT flywheel_campaign_dates_ordered CHECK (ends_on >= starts_on)
);
CREATE INDEX IF NOT EXISTS ix_flywheel_campaigns_tenant ON flywheel_campaigns (tenant_id, status);

-- PROOF CHECK: a PAUSED campaign must say WHY it paused. An auto-pause with no
-- recorded reason is not actionable for the operator who has to unpause it.
ALTER TABLE flywheel_campaigns DROP CONSTRAINT IF EXISTS flywheel_campaign_paused_has_reason;
ALTER TABLE flywheel_campaigns
    ADD CONSTRAINT flywheel_campaign_paused_has_reason
    CHECK (status <> 'PAUSED' OR pause_reason IS NOT NULL);

-- PROOF CHECK: ACTIVE claims the campaign went live — it must carry the moment.
ALTER TABLE flywheel_campaigns DROP CONSTRAINT IF EXISTS flywheel_campaign_active_has_timestamp;
ALTER TABLE flywheel_campaigns
    ADD CONSTRAINT flywheel_campaign_active_has_timestamp
    CHECK (status NOT IN ('ACTIVE', 'COMPLETED', 'MEASURED') OR activated_at IS NOT NULL);

-- Every transition, with actor and reason. Append-only history (§7).
CREATE TABLE IF NOT EXISTS flywheel_campaign_transitions (
    id             BIGSERIAL PRIMARY KEY,
    tenant_id      INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    campaign_id    INTEGER NOT NULL REFERENCES flywheel_campaigns(id) ON DELETE CASCADE,
    from_status    VARCHAR(30),
    to_status      VARCHAR(30) NOT NULL,
    actor_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    actor_kind     VARCHAR(20) NOT NULL DEFAULT 'user'
                     CHECK (actor_kind IN ('user', 'system', 'guardrail')),
    reason         TEXT,
    request_id     VARCHAR(64),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_flywheel_transitions_campaign
    ON flywheel_campaign_transitions (campaign_id, created_at);

-- The audience, with treatment/control assignment fixed at build time by a
-- STABLE HASH of (tenant, campaign, customer) — so re-running is idempotent and
-- measurement is causal rather than correlational (§18).
CREATE TABLE IF NOT EXISTS flywheel_campaign_audience (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    campaign_id      INTEGER NOT NULL REFERENCES flywheel_campaigns(id) ON DELETE CASCADE,
    customer_id      INTEGER NOT NULL REFERENCES flywheel_customers(id) ON DELETE CASCADE,
    assignment       VARCHAR(10) NOT NULL CHECK (assignment IN ('treatment', 'control')),
    assignment_hash  BIGINT NOT NULL,
    churn_probability NUMERIC(6,5),
    eligibility_note TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_flywheel_audience UNIQUE (campaign_id, customer_id)
);
CREATE INDEX IF NOT EXISTS ix_flywheel_audience_campaign
    ON flywheel_campaign_audience (tenant_id, campaign_id, assignment);

-- ===========================================================================
-- STAGE 03 — DECISIONS: the next-best-action ledger.
-- Every field the optimizer used is stored, so the selected action is
-- REPRODUCIBLE FROM ITS STORED INPUTS (§10). This is the audit backbone.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_decisions (
    id                      BIGSERIAL PRIMARY KEY,
    tenant_id               INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    campaign_id             INTEGER REFERENCES flywheel_campaigns(id) ON DELETE CASCADE,
    customer_id             INTEGER NOT NULL REFERENCES flywheel_customers(id) ON DELETE CASCADE,
    store_id                INTEGER REFERENCES stores(id) ON DELETE SET NULL,
    item_id                 INTEGER REFERENCES items(id) ON DELETE SET NULL,
    category                VARCHAR(50),
    action_type             VARCHAR(30) NOT NULL
                              CHECK (action_type IN ('NO_ACTION', 'REMINDER', 'LOYALTY_POINTS',
                                                     'FREE_DELIVERY', 'PERCENT_DISCOUNT',
                                                     'FIXED_DISCOUNT', 'PRODUCT_BUNDLE',
                                                     'SUBSTITUTE_PRODUCT', 'ALTERNATIVE_STORE',
                                                     'HUMAN_REVIEW')),
    -- --- model inputs (proposals) -----------------------------------------
    churn_probability       NUMERIC(6,5) NOT NULL DEFAULT 0,
    uplift                  NUMERIC(7,5) NOT NULL DEFAULT 0,
    redemption_probability  NUMERIC(6,5) NOT NULL DEFAULT 0,
    -- --- price/cost snapshot (so history survives a price change, §13) -----
    unit_price_aed          NUMERIC(12,4) NOT NULL DEFAULT 0,
    unit_cost_aed           NUMERIC(12,4) NOT NULL DEFAULT 0,
    discount_pct            NUMERIC(5,2) NOT NULL DEFAULT 0,
    -- --- the EIV terms (§5), each stored separately so the sum is checkable -
    expected_retained_value_aed NUMERIC(14,4) NOT NULL DEFAULT 0,
    expected_margin_aed         NUMERIC(14,4) NOT NULL DEFAULT 0,
    expected_discount_cost_aed  NUMERIC(14,4) NOT NULL DEFAULT 0,
    comms_cost_aed              NUMERIC(14,4) NOT NULL DEFAULT 0,
    fulfilment_cost_aed         NUMERIC(14,4) NOT NULL DEFAULT 0,
    procurement_cost_aed        NUMERIC(14,4) NOT NULL DEFAULT 0,
    stockout_risk_penalty_aed   NUMERIC(14,4) NOT NULL DEFAULT 0,
    eiv_aed                     NUMERIC(14,4) NOT NULL DEFAULT 0,
    -- --- provenance --------------------------------------------------------
    reason_codes            JSONB NOT NULL DEFAULT '[]',
    rejected_actions        JSONB NOT NULL DEFAULT '[]',  -- [{action, reason_code}]
    inventory_snapshot      JSONB NOT NULL DEFAULT '{}',
    budget_snapshot         JSONB NOT NULL DEFAULT '{}',
    churn_model_version_id  INTEGER REFERENCES flywheel_model_versions(id) ON DELETE SET NULL,
    uplift_model_version_id INTEGER REFERENCES flywheel_model_versions(id) ON DELETE SET NULL,
    policy_version          VARCHAR(20) NOT NULL DEFAULT 'v1',
    request_id              VARCHAR(64),
    decided_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_flywheel_decisions_campaign
    ON flywheel_decisions (tenant_id, campaign_id, decided_at DESC);
CREATE INDEX IF NOT EXISTS ix_flywheel_decisions_customer
    ON flywheel_decisions (tenant_id, customer_id, decided_at DESC);

COMMENT ON TABLE flywheel_decisions IS
    'Next-best-action ledger. Stores every optimizer input AND the rejected '
    'alternatives with reason codes, so any decision is reproducible and explainable.';

-- ===========================================================================
-- STAGE 04 — COMMERCIAL: inventory allocation layer over the EXISTING inventory
-- ===========================================================================

-- SOFT allocation reserved during planning; converted to HARD decrement at
-- redemption. Never a parallel stock table — ATP subtracts these from the real
-- `inventory` row.
CREATE TABLE IF NOT EXISTS flywheel_inventory_allocations (
    id             BIGSERIAL PRIMARY KEY,
    tenant_id      INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    campaign_id    INTEGER NOT NULL REFERENCES flywheel_campaigns(id) ON DELETE CASCADE,
    store_id       INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    item_id        INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    allocated_units INTEGER NOT NULL CHECK (allocated_units >= 0),
    consumed_units  INTEGER NOT NULL DEFAULT 0 CHECK (consumed_units >= 0),
    status         VARCHAR(20) NOT NULL DEFAULT 'soft'
                     CHECK (status IN ('soft', 'hard', 'released')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    released_at    TIMESTAMPTZ,
    CONSTRAINT uq_flywheel_allocation UNIQUE (campaign_id, store_id, item_id),
    -- INVARIANT: you can never consume more than you allocated.
    CONSTRAINT flywheel_allocation_not_overconsumed CHECK (consumed_units <= allocated_units)
);
CREATE INDEX IF NOT EXISTS ix_flywheel_alloc_lookup
    ON flywheel_inventory_allocations (tenant_id, store_id, item_id, status);

-- Aggregated shortage -> requisition. NEVER one PO per customer (§12): shortages
-- are grouped by (campaign, store, item, required_by).
CREATE TABLE IF NOT EXISTS flywheel_procurement_requisitions (
    id                 SERIAL PRIMARY KEY,
    tenant_id          INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    campaign_id        INTEGER NOT NULL REFERENCES flywheel_campaigns(id) ON DELETE CASCADE,
    store_id           INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    item_id            INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    supplier_id        INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    shortage_units     INTEGER NOT NULL CHECK (shortage_units > 0),
    order_units        INTEGER NOT NULL CHECK (order_units > 0),   -- MOQ-rounded
    unit_cost_aed      NUMERIC(12,4) NOT NULL DEFAULT 0,
    total_cost_aed     NUMERIC(14,2) NOT NULL DEFAULT 0,
    lead_time_days     INTEGER NOT NULL DEFAULT 0,
    required_by        DATE NOT NULL,
    expected_arrival   DATE,
    status             VARCHAR(25) NOT NULL DEFAULT 'draft'
                         CHECK (status IN ('draft', 'pending_approval', 'approved',
                                           'rejected', 'converted_to_po', 'cancelled')),
    -- Why this requisition is economically justified (or was refused).
    justification      JSONB NOT NULL DEFAULT '{}',
    purchase_order_id  INTEGER REFERENCES purchase_orders(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_flywheel_requisitions_campaign
    ON flywheel_procurement_requisitions (tenant_id, campaign_id, status);

-- PROOF CHECK: a requisition converted to a PO must name the PO it became.
ALTER TABLE flywheel_procurement_requisitions DROP CONSTRAINT IF EXISTS flywheel_req_converted_has_po;
ALTER TABLE flywheel_procurement_requisitions
    ADD CONSTRAINT flywheel_req_converted_has_po
    CHECK (status <> 'converted_to_po' OR purchase_order_id IS NOT NULL);

-- Inter-store transfer recommendation (shortage ladder step c).
CREATE TABLE IF NOT EXISTS flywheel_transfer_recommendations (
    id                SERIAL PRIMARY KEY,
    tenant_id         INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    campaign_id       INTEGER NOT NULL REFERENCES flywheel_campaigns(id) ON DELETE CASCADE,
    from_store_id     INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    to_store_id       INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    item_id           INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    units             INTEGER NOT NULL CHECK (units > 0),
    -- Surplus at source AFTER its own safety stock — never rob Peter to pay Paul.
    source_surplus_units INTEGER NOT NULL DEFAULT 0,
    status            VARCHAR(20) NOT NULL DEFAULT 'recommended'
                        CHECK (status IN ('recommended', 'accepted', 'rejected', 'executed')),
    stock_transfer_id INTEGER REFERENCES stock_transfers(id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT flywheel_transfer_distinct_stores CHECK (from_store_id <> to_store_id)
);
CREATE INDEX IF NOT EXISTS ix_flywheel_transfers_campaign
    ON flywheel_transfer_recommendations (tenant_id, campaign_id, status);

-- ===========================================================================
-- STAGE 04 — BUDGET LEDGER. Postgres is the financial source of truth.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_budgets (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    budget_type     VARCHAR(25) NOT NULL
                      CHECK (budget_type IN ('DISCOUNT', 'MARKETING_MEDIA', 'LOYALTY_REWARD',
                                             'PROCUREMENT', 'LOGISTICS', 'CONTINGENCY')),
    period_start    DATE NOT NULL,
    period_end      DATE NOT NULL,
    currency        VARCHAR(8) NOT NULL DEFAULT 'AED',
    allocated_aed   NUMERIC(16,2) NOT NULL DEFAULT 0 CHECK (allocated_aed >= 0),
    -- Running balances. Maintained ONLY by services/flywheel/budget_service.py
    -- inside a SELECT ... FOR UPDATE transaction. Never written ad hoc.
    reserved_aed    NUMERIC(16,2) NOT NULL DEFAULT 0 CHECK (reserved_aed >= 0),
    committed_aed   NUMERIC(16,2) NOT NULL DEFAULT 0 CHECK (committed_aed >= 0),
    spent_aed       NUMERIC(16,2) NOT NULL DEFAULT 0 CHECK (spent_aed >= 0),
    released_aed    NUMERIC(16,2) NOT NULL DEFAULT 0 CHECK (released_aed >= 0),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_flywheel_budget UNIQUE (tenant_id, budget_type, period_start),
    CONSTRAINT flywheel_budget_period_ordered CHECK (period_end > period_start),
    -- THE CORE FINANCIAL INVARIANT, enforced by the database itself:
    -- outstanding exposure can never exceed what was approved. Even a buggy
    -- service cannot overspend an approved budget.
    CONSTRAINT flywheel_budget_within_allocation
        CHECK (reserved_aed + spent_aed <= allocated_aed)
);
CREATE INDEX IF NOT EXISTS ix_flywheel_budgets_tenant ON flywheel_budgets (tenant_id, budget_type);

-- Append-only ledger. Every mutation records before/after balance + actor.
CREATE TABLE IF NOT EXISTS flywheel_budget_ledger (
    id                BIGSERIAL PRIMARY KEY,
    tenant_id         INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    budget_id         INTEGER NOT NULL REFERENCES flywheel_budgets(id) ON DELETE CASCADE,
    campaign_id       INTEGER REFERENCES flywheel_campaigns(id) ON DELETE SET NULL,
    entry_type        VARCHAR(20) NOT NULL
                        CHECK (entry_type IN ('ALLOCATED', 'RESERVED', 'COMMITTED',
                                              'SPENT', 'RELEASED')),
    amount_aed        NUMERIC(16,2) NOT NULL CHECK (amount_aed >= 0),
    currency          VARCHAR(8) NOT NULL DEFAULT 'AED',
    source_type       VARCHAR(40) NOT NULL,   -- 'campaign_approval' | 'redemption' | ...
    source_id         VARCHAR(64),
    balance_before    NUMERIC(16,2) NOT NULL,
    balance_after     NUMERIC(16,2) NOT NULL,
    actor_user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    request_id        VARCHAR(64),
    idempotency_key   VARCHAR(120),
    reason            TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_flywheel_ledger_budget
    ON flywheel_budget_ledger (tenant_id, budget_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_flywheel_ledger_campaign
    ON flywheel_budget_ledger (tenant_id, campaign_id, entry_type);
-- Idempotent budget mutations: the same key can never double-apply.
CREATE UNIQUE INDEX IF NOT EXISTS uq_flywheel_ledger_idem
    ON flywheel_budget_ledger (tenant_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

-- ===========================================================================
-- STAGE 04 — APPROVAL ENGINE. Policies are CONFIGURATION, not hard-coded emails.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_approval_policies (
    id                    SERIAL PRIMARY KEY,
    tenant_id             INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name                  VARCHAR(120) NOT NULL,
    -- Threshold conditions. A policy applies when ALL its non-null conditions match.
    applies_to            VARCHAR(30) NOT NULL DEFAULT 'campaign'
                            CHECK (applies_to IN ('campaign', 'requisition')),
    min_discount_aed      NUMERIC(14,2) NOT NULL DEFAULT 0,
    min_procurement_aed   NUMERIC(14,2) NOT NULL DEFAULT 0,
    min_store_count       INTEGER NOT NULL DEFAULT 0,
    -- Ordered steps; steps sharing a step_order run in PARALLEL (§15).
    required_role         VARCHAR(40) NOT NULL,
    required_permission   VARCHAR(60),
    step_order            INTEGER NOT NULL DEFAULT 1,
    step_label            VARCHAR(60) NOT NULL,
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_flywheel_policies_tenant
    ON flywheel_approval_policies (tenant_id, applies_to, is_active);

CREATE TABLE IF NOT EXISTS flywheel_approval_requests (
    id                SERIAL PRIMARY KEY,
    tenant_id         INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    campaign_id       INTEGER REFERENCES flywheel_campaigns(id) ON DELETE CASCADE,
    requisition_id    INTEGER REFERENCES flywheel_procurement_requisitions(id) ON DELETE CASCADE,
    request_type      VARCHAR(30) NOT NULL
                        CHECK (request_type IN ('campaign_launch', 'procurement_requisition',
                                                'budget_increase', 'policy_exception')),
    status            VARCHAR(20) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'approved', 'rejected', 'changes_requested',
                                          'cancelled', 'expired')),
    discount_exposure_aed    NUMERIC(14,2) NOT NULL DEFAULT 0,
    procurement_exposure_aed NUMERIC(14,2) NOT NULL DEFAULT 0,
    expected_roi             NUMERIC(10,4),
    summary           JSONB NOT NULL DEFAULT '{}',
    requested_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    expires_at        TIMESTAMPTZ,
    resolved_at       TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- An approval request must target exactly one subject.
    CONSTRAINT flywheel_approval_one_subject
        CHECK ((campaign_id IS NOT NULL)::int + (requisition_id IS NOT NULL)::int = 1)
);
CREATE INDEX IF NOT EXISTS ix_flywheel_approval_requests
    ON flywheel_approval_requests (tenant_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS flywheel_approval_steps (
    id                 SERIAL PRIMARY KEY,
    tenant_id          INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    request_id         INTEGER NOT NULL REFERENCES flywheel_approval_requests(id) ON DELETE CASCADE,
    policy_id          INTEGER REFERENCES flywheel_approval_policies(id) ON DELETE SET NULL,
    step_order         INTEGER NOT NULL,
    step_label         VARCHAR(60) NOT NULL,
    required_role      VARCHAR(40) NOT NULL,
    required_permission VARCHAR(60),
    status             VARCHAR(20) NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending', 'approved', 'rejected', 'changes_requested', 'skipped')),
    decided_by         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    decided_at         TIMESTAMPTZ,
    comment            TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_flywheel_steps_request
    ON flywheel_approval_steps (request_id, step_order);

-- PROOF CHECK: a decided step must record WHO decided and WHEN.
ALTER TABLE flywheel_approval_steps DROP CONSTRAINT IF EXISTS flywheel_step_decided_has_actor;
ALTER TABLE flywheel_approval_steps
    ADD CONSTRAINT flywheel_step_decided_has_actor
    CHECK (status IN ('pending', 'skipped') OR (decided_by IS NOT NULL AND decided_at IS NOT NULL));

-- ===========================================================================
-- STAGE 05 — EXECUTION: offers, idempotent redemption, transactional outbox
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_offers (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    campaign_id     INTEGER NOT NULL REFERENCES flywheel_campaigns(id) ON DELETE CASCADE,
    customer_id     INTEGER NOT NULL REFERENCES flywheel_customers(id) ON DELETE CASCADE,
    decision_id     BIGINT REFERENCES flywheel_decisions(id) ON DELETE SET NULL,
    offer_code      VARCHAR(40) NOT NULL,
    action_type     VARCHAR(30) NOT NULL,
    store_id        INTEGER REFERENCES stores(id) ON DELETE SET NULL,
    item_id         INTEGER REFERENCES items(id) ON DELETE SET NULL,
    discount_pct    NUMERIC(5,2) NOT NULL DEFAULT 0,
    -- Exposure reserved against the discount budget when this offer was issued.
    reserved_aed    NUMERIC(14,2) NOT NULL DEFAULT 0,
    status          VARCHAR(20) NOT NULL DEFAULT 'issued'
                      CHECK (status IN ('issued', 'redeemed', 'expired', 'cancelled')),
    issued_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    redeemed_at     TIMESTAMPTZ,
    CONSTRAINT uq_flywheel_offer_code UNIQUE (tenant_id, offer_code)
);
CREATE INDEX IF NOT EXISTS ix_flywheel_offers_customer
    ON flywheel_offers (tenant_id, customer_id, status);
CREATE INDEX IF NOT EXISTS ix_flywheel_offers_campaign
    ON flywheel_offers (tenant_id, campaign_id, status);

-- PROOF CHECK: a redeemed offer must carry its redemption moment.
ALTER TABLE flywheel_offers DROP CONSTRAINT IF EXISTS flywheel_offer_redeemed_has_timestamp;
ALTER TABLE flywheel_offers
    ADD CONSTRAINT flywheel_offer_redeemed_has_timestamp
    CHECK (status <> 'redeemed' OR redeemed_at IS NOT NULL);

CREATE TABLE IF NOT EXISTS flywheel_redemptions (
    id                BIGSERIAL PRIMARY KEY,
    tenant_id         INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    offer_id          BIGINT NOT NULL REFERENCES flywheel_offers(id) ON DELETE CASCADE,
    campaign_id       INTEGER NOT NULL REFERENCES flywheel_campaigns(id) ON DELETE CASCADE,
    customer_id       INTEGER NOT NULL REFERENCES flywheel_customers(id) ON DELETE CASCADE,
    store_id          INTEGER NOT NULL REFERENCES stores(id) ON DELETE RESTRICT,
    item_id           INTEGER REFERENCES items(id) ON DELETE SET NULL,
    units             INTEGER NOT NULL CHECK (units > 0),
    gross_value_aed   NUMERIC(14,2) NOT NULL DEFAULT 0,
    discount_aed      NUMERIC(14,2) NOT NULL DEFAULT 0,
    net_value_aed     NUMERIC(14,2) NOT NULL DEFAULT 0,
    margin_aed        NUMERIC(14,2) NOT NULL DEFAULT 0,
    -- THE anti-double-spend mechanism. A retry with the same key returns the
    -- ORIGINAL row instead of creating a second one (§17).
    idempotency_key   VARCHAR(120) NOT NULL,
    request_id        VARCHAR(64),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_flywheel_redemption_idem UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_flywheel_redemptions_campaign
    ON flywheel_redemptions (tenant_id, campaign_id, created_at DESC);

-- TRANSACTIONAL OUTBOX. Financial events are committed in the SAME transaction
-- as the money/stock move, then relayed to Redis/SSE by a poller. Redis pub/sub
-- alone is NOT a financial record: a crash between commit and publish would lose
-- the event forever. This table makes delivery recoverable.
CREATE TABLE IF NOT EXISTS flywheel_outbox (
    id             BIGSERIAL PRIMARY KEY,
    tenant_id      INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    channel        VARCHAR(60) NOT NULL,
    event_type     VARCHAR(60) NOT NULL,
    payload        JSONB NOT NULL,
    -- Server-side filtering data so the relay never leaks cross-scope events.
    store_id       INTEGER,
    campaign_id    INTEGER,
    published      BOOLEAN NOT NULL DEFAULT FALSE,
    published_at   TIMESTAMPTZ,
    attempts       INTEGER NOT NULL DEFAULT 0,
    last_error     TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- The relay's hot path: unpublished rows in insertion order.
CREATE INDEX IF NOT EXISTS ix_flywheel_outbox_pending
    ON flywheel_outbox (published, id) WHERE published = FALSE;

-- PROOF CHECK: published means delivered — it must carry the delivery moment.
ALTER TABLE flywheel_outbox DROP CONSTRAINT IF EXISTS flywheel_outbox_published_has_timestamp;
ALTER TABLE flywheel_outbox
    ADD CONSTRAINT flywheel_outbox_published_has_timestamp
    CHECK (published = FALSE OR published_at IS NOT NULL);

-- Contact-frequency ledger — enforces the per-campaign and per-customer caps.
CREATE TABLE IF NOT EXISTS flywheel_contact_log (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_id   INTEGER NOT NULL REFERENCES flywheel_customers(id) ON DELETE CASCADE,
    campaign_id   INTEGER REFERENCES flywheel_campaigns(id) ON DELETE SET NULL,
    channel       VARCHAR(20) NOT NULL,
    contacted_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_flywheel_contact_window
    ON flywheel_contact_log (tenant_id, customer_id, contacted_at DESC);

-- ===========================================================================
-- STAGE 06 — MEASUREMENT: treatment vs control. The loop closes.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_campaign_outcomes (
    id                        SERIAL PRIMARY KEY,
    tenant_id                 INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    campaign_id               INTEGER NOT NULL REFERENCES flywheel_campaigns(id) ON DELETE CASCADE,
    measured_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    treatment_size            INTEGER NOT NULL DEFAULT 0,
    control_size              INTEGER NOT NULL DEFAULT 0,
    treatment_retained        INTEGER NOT NULL DEFAULT 0,
    control_retained          INTEGER NOT NULL DEFAULT 0,
    treatment_retention_rate  NUMERIC(6,5) NOT NULL DEFAULT 0,
    control_retention_rate    NUMERIC(6,5) NOT NULL DEFAULT 0,
    -- CAUSAL: treatment rate - control rate. Never a raw correlation (§18).
    incremental_retention     NUMERIC(7,5) NOT NULL DEFAULT 0,
    incremental_revenue_aed   NUMERIC(16,2) NOT NULL DEFAULT 0,
    incremental_margin_aed    NUMERIC(16,2) NOT NULL DEFAULT 0,
    discount_spend_aed        NUMERIC(16,2) NOT NULL DEFAULT 0,
    procurement_cost_aed      NUMERIC(16,2) NOT NULL DEFAULT 0,
    cost_per_retained_aed     NUMERIC(14,2),
    campaign_roi              NUMERIC(10,4),
    uplift_by_segment         JSONB NOT NULL DEFAULT '{}',
    budget_variance_aed       NUMERIC(16,2) NOT NULL DEFAULT 0,
    stockout_rate             NUMERIC(6,5) NOT NULL DEFAULT 0,
    notes                     TEXT,
    CONSTRAINT uq_flywheel_outcome UNIQUE (campaign_id, measured_at)
);
CREATE INDEX IF NOT EXISTS ix_flywheel_outcomes_campaign
    ON flywheel_campaign_outcomes (tenant_id, campaign_id);

-- ===========================================================================
-- ROW LEVEL SECURITY — identical pattern to migrations 012 / 060.
-- Header tables bind on their own tenant_id; there are no child-through-parent
-- tables here because EVERY Flywheel table carries tenant_id explicitly.
-- ===========================================================================

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'flywheel_customers', 'flywheel_customer_consents', 'flywheel_customer_events',
        'flywheel_purchase_attributions', 'flywheel_model_versions', 'flywheel_feature_snapshots',
        'flywheel_churn_predictions', 'flywheel_offer_response_predictions', 'flywheel_campaigns',
        'flywheel_campaign_transitions', 'flywheel_campaign_audience', 'flywheel_decisions',
        'flywheel_inventory_allocations', 'flywheel_procurement_requisitions',
        'flywheel_transfer_recommendations', 'flywheel_budgets', 'flywheel_budget_ledger',
        'flywheel_approval_policies', 'flywheel_approval_requests', 'flywheel_approval_steps',
        'flywheel_offers', 'flywheel_redemptions', 'flywheel_outbox', 'flywheel_contact_log',
        'flywheel_campaign_outcomes'
    ]
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I '
            'USING (tenant_id = current_tenant_id()) '
            'WITH CHECK (tenant_id = current_tenant_id())', t);
        -- FORCE so even a table-owner-like connection is filtered (E0-8 precedent).
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    END LOOP;
END $$;

-- ===========================================================================
-- SEED — approval policies as CONFIGURATION DATA for the demo tenant.
-- Thresholds are deliberately low so a reviewer can trigger each rung of the
-- ladder during the demo without inventing six-figure campaigns.
-- Note steps 2 and 3 share step_order = 2: they run in PARALLEL.
-- ===========================================================================

INSERT INTO flywheel_approval_policies
    (tenant_id, name, applies_to, min_discount_aed, min_procurement_aed,
     min_store_count, required_role, required_permission, step_order, step_label)
VALUES
    (1, 'Marketing sign-off',    'campaign',    0,     0, 0, 'regional_manager', 'can_manage_promotions', 1, 'Marketing'),
    (1, 'Inventory review',      'campaign',    0,     0, 0, 'regional_manager', 'can_manage_inventory',  2, 'Inventory'),
    (1, 'Procurement review',    'campaign',    0,  1000, 0, 'regional_manager', 'can_manage_inventory',  2, 'Procurement'),
    (1, 'Finance control',       'campaign', 5000,     0, 0, 'super_admin',      'can_view_financials',   3, 'Finance'),
    (1, 'CFO authorisation',     'campaign', 25000,    0, 0, 'super_admin',      'can_view_financials',   4, 'CFO'),
    (1, 'Requisition finance',   'requisition', 0,  1000, 0, 'super_admin',      'can_view_financials',   1, 'Finance')
ON CONFLICT DO NOTHING;

-- Demo discount + procurement budgets for the current quarter, so the ledger has
-- a real allocation to reserve against on first run.
INSERT INTO flywheel_budgets (tenant_id, budget_type, period_start, period_end, allocated_aed)
VALUES
    (1, 'DISCOUNT',    date_trunc('quarter', CURRENT_DATE)::date,
                       (date_trunc('quarter', CURRENT_DATE) + INTERVAL '3 months')::date, 250000.00),
    (1, 'PROCUREMENT', date_trunc('quarter', CURRENT_DATE)::date,
                       (date_trunc('quarter', CURRENT_DATE) + INTERVAL '3 months')::date, 400000.00),
    (1, 'LOYALTY_REWARD', date_trunc('quarter', CURRENT_DATE)::date,
                       (date_trunc('quarter', CURRENT_DATE) + INTERVAL '3 months')::date, 60000.00)
ON CONFLICT (tenant_id, budget_type, period_start) DO NOTHING;

COMMIT;

DO $$ BEGIN
    RAISE NOTICE 'Flywheel schema ready: 25 tenant-scoped tables, FORCE RLS, Decimal money, idempotent ledger + outbox';
END $$;
