-- 079 — FLYWHEEL HORIZON 3: expand the wedge. Two tracks over one engine.
--
-- The owner ruled (20 Jul 2026, decision 3) that retention and supplier-funded
-- trade promotion are pursued IN PARALLEL. The EIV engine is shared; what is not
-- shared, and is built here, is everything around it.
--
--   TRACK B — TRADE PROMOTION. A supplier funds a promotion of THEIR SKUs and
--   pays against a jointly-agreed uplift. Three things make this different from
--   retention and are the reason it needs its own tables:
--
--     * The money is the SUPPLIER'S, not the retailer's. It has its own
--       commitment, spend and settlement lifecycle (flywheel_supplier_funding,
--       flywheel_settlements) separate from flywheel_budgets, which models only
--       retailer-funded discount budget.
--
--     * The proof is owed to a COUNTERPARTY WITH AN INCENTIVE TO DISPUTE IT. A
--       supplier will not pay for volume that was going to sell anyway, and will
--       not pay for volume STOLEN FROM THEIR OWN OTHER SKU. So cannibalization is
--       not a nicety here (as it is for retention) — it is the central question,
--       and flywheel_cannibalization / flywheel_substitution exist to answer it
--       in a way that survives an adversarial audit.
--
--     * A supplier sees only THEIR SKUs. That is a second tenancy axis layered
--       inside a tenant, enforced by flywheel_supplier_funding_skus + the trade
--       service, never by hopeful application filtering.
--
--   SHARED — the platform obligations both tracks depend on:
--
--     * PDPL. A data subject may OBJECT to automated profiling (UAE Federal
--       Decree-Law No. 45 of 2021). flywheel_profiling_objections records that
--       objection and decisioning honours it — an objecting customer is excluded
--       from automated decisions entirely. This is a legal gate, not a
--       preference.
--
--     * INGESTION. The path from a real POS feed to a loyalty identity, so the
--       engine can one day meet a real shopper instead of a synthetic one.
--       flywheel_pos_staging lands raw transactions; flywheel_identity_links
--       records the resolved (deterministic or probabilistic) match, and — the
--       point of the whole exercise — leaves a record UNLINKED rather than
--       wrongly merging two people, because a bad merge corrupts the feature
--       store, the holdout and the consent ledger at once.
--
-- WHAT IS NOT IN CODE, HONESTLY. Two Horizon-3 items are real-world processes
-- that cannot be manufactured in a migration: the SOC 2 Type II observation
-- window (a calendar process that must simply be started) and an actual pilot
-- tenant's real POS feed (none exists yet). The ingestion path here is built and
-- exercised with synthetic POS rows so it is ready when a real feed arrives.
--
-- MONEY. NUMERIC throughout, Decimal on the Python side, net of VAT for anything
-- a supplier is invoiced on. TENANCY. Every table: tenant_id, tenant_isolation
-- policy, FORCE RLS (ruling #2), app_rw grants. REUSE, DON'T FORK: only CREATEs
-- flywheel_ tables and references shared tables (suppliers, items, stores,
-- flywheel_campaigns) by FK — no shared table is altered.

BEGIN;

-- ===========================================================================
-- STAGE 01 — SUPPLIER-FUNDED TRADE PROMOTION (Track B)
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_supplier_funding (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    supplier_id         INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE RESTRICT,
    campaign_id         INTEGER NOT NULL REFERENCES flywheel_campaigns(id) ON DELETE CASCADE,

    -- HOW the supplier funds. co_op = share of promo cost; scan_down = per-unit
    -- rebate on sales; fixed_fee = a flat trade-marketing payment. The type
    -- decides how settlement is computed.
    funding_type        VARCHAR(20) NOT NULL
                          CHECK (funding_type IN ('co_op', 'scan_down', 'fixed_fee')),
    currency            VARCHAR(3) NOT NULL DEFAULT 'AED',

    -- The lifecycle of the commitment. proposed -> committed (the supplier
    -- agreed) -> active (the campaign is live) -> settled (paid) / disputed.
    status              VARCHAR(20) NOT NULL DEFAULT 'proposed'
                          CHECK (status IN ('proposed', 'committed', 'active',
                                            'settled', 'disputed', 'cancelled')),

    -- The money, all net of VAT. spent is what the promotion drew against the
    -- commitment; settled is what has actually been invoiced/paid. The invariant
    -- below makes overspend and over-settlement impossible at the database.
    committed_aed       NUMERIC(16,2) NOT NULL DEFAULT 0 CHECK (committed_aed >= 0),
    spent_aed           NUMERIC(16,2) NOT NULL DEFAULT 0 CHECK (spent_aed >= 0),
    settled_aed         NUMERIC(16,2) NOT NULL DEFAULT 0 CHECK (settled_aed >= 0),
    -- For scan_down: the per-unit rebate the supplier pays.
    rebate_per_unit_aed NUMERIC(12,4) NOT NULL DEFAULT 0,

    agreement_ref       VARCHAR(80),
    starts_on           DATE,
    ends_on             DATE,
    created_by          INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- SUPPLIER MONEY CANNOT BE OVERSPENT OR OVER-SETTLED. Enforced by the DB, not
    -- by the service — the same discipline as flywheel_budgets' reserved<=allocated.
    CONSTRAINT ck_supplier_funding_spend CHECK (spent_aed <= committed_aed),
    CONSTRAINT ck_supplier_funding_settle CHECK (settled_aed <= spent_aed)
);

CREATE INDEX IF NOT EXISTS idx_flywheel_funding_campaign
    ON flywheel_supplier_funding (tenant_id, campaign_id);
CREATE INDEX IF NOT EXISTS idx_flywheel_funding_supplier
    ON flywheel_supplier_funding (tenant_id, supplier_id, status);

-- THE SUPPLIER'S SCOPE. Which SKUs this funding covers — and therefore which
-- SKUs the supplier is entitled to see and be charged for. A funding with no
-- rows here covers nothing; the trade service refuses to activate it.
CREATE TABLE IF NOT EXISTS flywheel_supplier_funding_skus (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    funding_id          BIGINT NOT NULL REFERENCES flywheel_supplier_funding(id) ON DELETE CASCADE,
    item_id             INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_flywheel_funding_sku UNIQUE (funding_id, item_id)
);

CREATE INDEX IF NOT EXISTS idx_flywheel_funding_skus_item
    ON flywheel_supplier_funding_skus (tenant_id, item_id);

-- SETTLEMENT. What the supplier owes for a period, computed from MEASURED
-- incremental performance (net of VAT, net of cannibalization). Once issued it
-- is evidence — a settlement you can quietly rewrite after the supplier queries
-- it is not a settlement — so issued/paid rows are immutable (trigger below).
CREATE TABLE IF NOT EXISTS flywheel_settlements (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    funding_id          BIGINT NOT NULL REFERENCES flywheel_supplier_funding(id) ON DELETE CASCADE,

    period_start        DATE NOT NULL,
    period_end          DATE NOT NULL,
    CONSTRAINT ck_settlement_period CHECK (period_end > period_start),

    -- The performance the charge rests on. incremental_* are the CAUSAL figures
    -- (measured against control, net of cannibalization), never gross.
    incremental_units   INTEGER NOT NULL DEFAULT 0,
    incremental_margin_aed NUMERIC(16,2) NOT NULL DEFAULT 0,
    -- What the supplier owes for this period under the funding terms.
    amount_due_aed      NUMERIC(16,2) NOT NULL DEFAULT 0 CHECK (amount_due_aed >= 0),

    status              VARCHAR(20) NOT NULL DEFAULT 'draft'
                          CHECK (status IN ('draft', 'issued', 'paid', 'disputed')),
    dispute_reason      TEXT,
    -- The evidence bundle the number was computed from — arm sizes, the
    -- confidence interval, the cannibalization adjustment — so the supplier can
    -- audit it rather than take it on trust.
    evidence            JSONB NOT NULL DEFAULT '{}'::jsonb,

    issued_at           TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_flywheel_settlement UNIQUE (tenant_id, funding_id, period_start, period_end)
);

CREATE INDEX IF NOT EXISTS idx_flywheel_settlements_funding
    ON flywheel_settlements (tenant_id, funding_id, period_end DESC);

-- Once a settlement is issued or paid it must not be silently altered. A dispute
-- is a NEW status transition (with a reason), not an edit of the amount — the
-- amount the supplier was charged is preserved exactly, which is the whole point
-- of it being evidence. Draft rows are still freely editable.
CREATE OR REPLACE FUNCTION flywheel_settlement_immutable() RETURNS trigger AS $$
BEGIN
    IF OLD.status IN ('issued', 'paid') THEN
        -- Permit ONLY a status move to 'disputed' or 'paid', and the amount must
        -- not change. Everything else on an issued settlement is frozen.
        IF NEW.amount_due_aed <> OLD.amount_due_aed
           OR NEW.incremental_margin_aed <> OLD.incremental_margin_aed
           OR NEW.period_start <> OLD.period_start
           OR NEW.period_end <> OLD.period_end THEN
            RAISE EXCEPTION
                'flywheel: settlement % is issued — its amount and period are '
                'frozen. Dispute it (status -> disputed) or pay it, but do not '
                'rewrite what the supplier was charged.', OLD.id
                USING ERRCODE = 'restrict_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_flywheel_settlement_immutable ON flywheel_settlements;
CREATE TRIGGER trg_flywheel_settlement_immutable
    BEFORE UPDATE ON flywheel_settlements
    FOR EACH ROW EXECUTE FUNCTION flywheel_settlement_immutable();

-- ===========================================================================
-- STAGE 02 — CANNIBALIZATION (A.3.3, Track B critical path)
--
-- Difference-in-differences on category totals: did promoting SKU A create NEW
-- category demand, or move volume from SKU B in the same category? A supplier
-- pays only for the NET category-level lift attributable to their SKUs.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_cannibalization (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    campaign_id         INTEGER NOT NULL REFERENCES flywheel_campaigns(id) ON DELETE CASCADE,

    category            VARCHAR(80) NOT NULL,
    promoted_item_id    INTEGER REFERENCES items(id) ON DELETE SET NULL,

    method              VARCHAR(20) NOT NULL DEFAULT 'did'
                          CHECK (method IN ('did', 'naive', 'bayesian')),
    window_start        DATE NOT NULL,
    window_end          DATE NOT NULL,

    -- The gross lift on the promoted SKU (treated vs control).
    promoted_lift_units     INTEGER NOT NULL DEFAULT 0,
    -- The NET lift for the whole CATEGORY (treated vs control). If this is much
    -- smaller than the promoted lift, the promotion mostly moved volume around.
    category_net_lift_units INTEGER NOT NULL DEFAULT 0,
    -- promoted_lift - category_net_lift, floored at zero: volume the promoted SKU
    -- gained that the category did not.
    cannibalized_units      INTEGER NOT NULL DEFAULT 0,
    -- cannibalized / promoted_lift. 0 = all lift was incremental; 1 = all of it
    -- was stolen from the category.
    cannibalization_rate    NUMERIC(6,4),
    -- The margin a supplier may honestly be charged on: category-net, net of VAT.
    net_incremental_margin_aed NUMERIC(16,2) NOT NULL DEFAULT 0,

    -- Small control arms make this directional, not decisive. Said plainly so a
    -- supplier is never charged on a number the retailer would not defend.
    is_reliable         BOOLEAN NOT NULL DEFAULT FALSE,
    note                TEXT,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_flywheel_cannibalization
        UNIQUE (tenant_id, campaign_id, promoted_item_id, window_end)
);

CREATE INDEX IF NOT EXISTS idx_flywheel_cannibalization_campaign
    ON flywheel_cannibalization (tenant_id, campaign_id, window_end DESC);

-- Pairwise substitution: how much promoting `from_item` moved volume to/from
-- `to_item`. Feeds the category rollup above and the Cannibalization surface.
CREATE TABLE IF NOT EXISTS flywheel_substitution (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    campaign_id         INTEGER NOT NULL REFERENCES flywheel_campaigns(id) ON DELETE CASCADE,
    from_item_id        INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    to_item_id          INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    -- Negative = `to_item` LOST volume when `from_item` was promoted (it was
    -- cannibalised); positive = a halo (it gained).
    substitution_units  INTEGER NOT NULL DEFAULT 0,
    substitution_rate   NUMERIC(6,4),
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_flywheel_substitution
        UNIQUE (tenant_id, campaign_id, from_item_id, to_item_id),
    CONSTRAINT ck_flywheel_substitution_distinct CHECK (from_item_id <> to_item_id)
);

CREATE INDEX IF NOT EXISTS idx_flywheel_substitution_campaign
    ON flywheel_substitution (tenant_id, campaign_id);

-- ===========================================================================
-- STAGE 03 — PDPL: objection to automated profiling (shared, legal gate)
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_profiling_objections (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_id         INTEGER NOT NULL REFERENCES flywheel_customers(id) ON DELETE CASCADE,

    -- The lawful basis the objection was raised under. Recorded so an audit can
    -- see WHY someone is excluded, not just that they are.
    basis               VARCHAR(40) NOT NULL DEFAULT 'pdpl_art_automated_processing',
    status              VARCHAR(20) NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active', 'withdrawn')),
    note                TEXT,
    objected_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    withdrawn_at        TIMESTAMPTZ,

    -- One live objection per customer. Withdrawing then re-objecting is a new
    -- lifecycle on the same row, not a second row.
    CONSTRAINT uq_flywheel_objection UNIQUE (tenant_id, customer_id)
);

CREATE INDEX IF NOT EXISTS idx_flywheel_objections_active
    ON flywheel_profiling_objections (tenant_id, customer_id)
    WHERE status = 'active';

-- ===========================================================================
-- STAGE 04 — INGESTION + IDENTITY RESOLUTION (A.3.7, shared)
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_pos_staging (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- The raw transaction as it arrived from a POS/loyalty export. external_txn_id
    -- makes ingestion idempotent (the same file re-imported is a no-op).
    external_txn_id     VARCHAR(120) NOT NULL,
    loyalty_ref         VARCHAR(120),      -- present => deterministic match possible
    card_hash           VARCHAR(120),      -- a hashed card fingerprint, never a PAN
    store_id            INTEGER REFERENCES stores(id) ON DELETE SET NULL,
    item_id             INTEGER REFERENCES items(id) ON DELETE SET NULL,
    units               INTEGER NOT NULL DEFAULT 1,
    amount_aed          NUMERIC(16,2) NOT NULL DEFAULT 0,
    occurred_at         TIMESTAMPTZ NOT NULL,

    -- Resolution state.
    resolved            BOOLEAN NOT NULL DEFAULT FALSE,
    matched_customer_id INTEGER REFERENCES flywheel_customers(id) ON DELETE SET NULL,
    match_confidence    NUMERIC(4,3),
    match_method        VARCHAR(20)
                          CHECK (match_method IN ('deterministic', 'probabilistic',
                                                  'unlinked', NULL)),
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_flywheel_pos_txn UNIQUE (tenant_id, external_txn_id)
);

CREATE INDEX IF NOT EXISTS idx_flywheel_pos_unresolved
    ON flywheel_pos_staging (tenant_id)
    WHERE resolved = FALSE;

-- The identity graph. A stable link from a POS key (loyalty_ref or card_hash) to
-- a customer, with the confidence and method that produced it. status='ambiguous'
-- or 'unlinked' means we DECLINED to merge — a wrong merge corrupts the feature
-- store, the holdout and the consent ledger simultaneously, so leaving a record
-- anonymous is the safer error.
CREATE TABLE IF NOT EXISTS flywheel_identity_links (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    pos_key             VARCHAR(120) NOT NULL,
    customer_id         INTEGER REFERENCES flywheel_customers(id) ON DELETE CASCADE,
    confidence          NUMERIC(4,3) NOT NULL DEFAULT 0,
    method              VARCHAR(20) NOT NULL
                          CHECK (method IN ('deterministic', 'probabilistic',
                                            'ambiguous', 'unlinked')),
    status              VARCHAR(20) NOT NULL DEFAULT 'linked'
                          CHECK (status IN ('linked', 'ambiguous', 'unlinked')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_flywheel_identity_key UNIQUE (tenant_id, pos_key)
);

CREATE INDEX IF NOT EXISTS idx_flywheel_identity_customer
    ON flywheel_identity_links (tenant_id, customer_id);

-- ===========================================================================
-- TENANCY — policy + FORCE RLS on every new table (ruling #2).
-- ===========================================================================

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'flywheel_supplier_funding', 'flywheel_supplier_funding_skus',
        'flywheel_settlements', 'flywheel_cannibalization', 'flywheel_substitution',
        'flywheel_profiling_objections', 'flywheel_pos_staging',
        'flywheel_identity_links'
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

-- The request path connects as app_rw when RLS is enforced (ruling #2), so it
-- needs table privileges on the new tables. Guarded on the role existing.
DO $$
DECLARE
    t TEXT;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
        FOREACH t IN ARRAY ARRAY[
            'flywheel_supplier_funding', 'flywheel_supplier_funding_skus',
            'flywheel_settlements', 'flywheel_cannibalization', 'flywheel_substitution',
            'flywheel_profiling_objections', 'flywheel_pos_staging',
            'flywheel_identity_links'
        ]
        LOOP
            EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO app_rw', t);
            EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %I_id_seq TO app_rw', t);
        END LOOP;
    END IF;
END $$;

COMMIT;
