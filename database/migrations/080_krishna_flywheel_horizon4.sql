-- 080 — FLYWHEEL HORIZON 4: expand. The demand context the engine was blind to.
--
-- Horizons 1–3 made the Flywheel provable, operable and sellable. It still decided
-- as if every day were an average day, every customer belonged to one retailer,
-- and every unit of stock lasted forever. In the GCC grocery market none of those
-- is true, and Horizon 4 gives the engine the context it was missing.
--
--   SEASONALITY. Ramadan roughly doubles grocery demand; Eid, back-to-school and
--   summer each reshape it. A retention offer made the week before Ramadan is
--   worth more than the same offer in a flat week, because the customer's forward
--   value is higher. flywheel_seasonality_calendar carries a demand multiplier by
--   date (and optionally category); decisioning scales a customer's monthly value
--   by it before the optimizer ever sees the candidate. Deterministic policy, not
--   a model — the governing rule holds.
--
--   COALITION. GCC loyalty is coalition-shaped: SHARE, ADNOC, e& Smiles link
--   grocery, fuel, hospitality and travel under one earn-and-redeem. A retained
--   customer's value is not the retailer's alone; it is EARNED ACROSS PARTNERS,
--   and multi-party attribution is table stakes here in a way it is not in the US.
--   flywheel_coalition_* records the partners, the cross-partner activity, and the
--   attribution of a retained customer's incremental value across the partners
--   they actually engaged with.
--
--   PERISHABLES. For a grocer, markdown TIMING on short-dated stock can be worth
--   more than retention: a promotion that clears yoghurt three days from expiry
--   recovers margin that would otherwise be written off entirely. flywheel_shelf_
--   life tracks near-expiry batches; the shelf-life service turns "days to expiry"
--   into a markdown urgency the allocator can act on before the write-off.
--
--   OUTCOME PRICING, REVISITED. The plan deferred outcome-based pricing (a share
--   of measured incremental margin) until the holdout readout had run clean for
--   two quarters — because charging on a number we cannot yet measure reliably is
--   how the trust the whole product runs on gets destroyed. flywheel_outcome_
--   pricing records the AGREEMENT, but it is GATED: it becomes chargeable only
--   when the evidence gate is met. Until then it is inert, by design, and the
--   service says so.
--
-- TENANCY. Every table: tenant_id, tenant_isolation policy, FORCE RLS (ruling #2),
-- app_rw grants. REUSE, DON'T FORK: only CREATEs flywheel_ tables; references
-- shared tables (items, stores, flywheel_campaigns, flywheel_customers) by FK.
-- MONEY. NUMERIC throughout, Decimal on the Python side.

BEGIN;

-- ===========================================================================
-- STAGE 01 — SEASONALITY CALENDAR
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_seasonality_calendar (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    name                VARCHAR(60) NOT NULL,      -- 'Ramadan', 'Eid al-Fitr', ...
    kind                VARCHAR(30) NOT NULL DEFAULT 'religious'
                          CHECK (kind IN ('religious', 'national', 'commercial', 'seasonal')),
    starts_on           DATE NOT NULL,
    ends_on             DATE NOT NULL,
    CONSTRAINT ck_season_window CHECK (ends_on >= starts_on),

    -- The demand multiplier applied to a customer's forward value during the
    -- window. 1.0 = a normal week; 2.0 = demand doubles (Ramadan grocery). A
    -- multiplier below 1 models a lull. Bounded so a fat-fingered 20x cannot make
    -- the optimizer hand out the store.
    demand_multiplier   NUMERIC(5,3) NOT NULL DEFAULT 1.000
                          CHECK (demand_multiplier > 0 AND demand_multiplier <= 5),
    -- Optional per-category override; NULL = applies to all categories.
    category            VARCHAR(80),
    note                TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One factor per (name, category). A plain UNIQUE(tenant_id, name, category)
-- would NOT enforce this: Postgres treats two NULL categories as distinct, so
-- duplicate ('Ramadan', NULL) rows would slip through and re-seeding would stack
-- them. COALESCE-ing NULL to '' in a unique INDEX collapses them, so uniqueness
-- actually holds for the common "applies to all categories" case.
CREATE UNIQUE INDEX IF NOT EXISTS uq_flywheel_season
    ON flywheel_seasonality_calendar (tenant_id, name, COALESCE(category, ''));

CREATE INDEX IF NOT EXISTS idx_flywheel_season_window
    ON flywheel_seasonality_calendar (tenant_id, starts_on, ends_on);

-- ===========================================================================
-- STAGE 02 — COALITION LOYALTY
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_coalition_partners (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    partner_name        VARCHAR(120) NOT NULL,
    partner_type        VARCHAR(30) NOT NULL
                          CHECK (partner_type IN ('grocery', 'fuel', 'hospitality',
                                                  'travel', 'retail', 'dining', 'other')),
    external_ref        VARCHAR(80),
    status              VARCHAR(20) NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active', 'inactive')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_coalition_partner UNIQUE (tenant_id, partner_name)
);

-- A customer's earn/redeem activity at a partner. The raw signal attribution is
-- computed from.
CREATE TABLE IF NOT EXISTS flywheel_coalition_activity (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_id         INTEGER NOT NULL REFERENCES flywheel_customers(id) ON DELETE CASCADE,
    partner_id          BIGINT NOT NULL REFERENCES flywheel_coalition_partners(id) ON DELETE CASCADE,
    activity_type       VARCHAR(20) NOT NULL CHECK (activity_type IN ('earn', 'redeem')),
    points              INTEGER NOT NULL DEFAULT 0,
    value_aed           NUMERIC(16,2) NOT NULL DEFAULT 0,
    occurred_at         TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_flywheel_coalition_activity_customer
    ON flywheel_coalition_activity (tenant_id, customer_id, occurred_at DESC);

-- The attribution: how a retained customer's incremental value splits across the
-- partners they engaged with. weight sums to 1 per (campaign, customer) — the DB
-- cannot enforce that sum, so the service asserts it and a test guards it.
CREATE TABLE IF NOT EXISTS flywheel_coalition_attribution (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    campaign_id         INTEGER NOT NULL REFERENCES flywheel_campaigns(id) ON DELETE CASCADE,
    customer_id         INTEGER NOT NULL REFERENCES flywheel_customers(id) ON DELETE CASCADE,
    partner_id          BIGINT NOT NULL REFERENCES flywheel_coalition_partners(id) ON DELETE CASCADE,

    -- Fraction of the customer's incremental value attributed to this partner.
    attribution_weight  NUMERIC(6,5) NOT NULL DEFAULT 0
                          CHECK (attribution_weight >= 0 AND attribution_weight <= 1),
    attributed_margin_aed NUMERIC(16,2) NOT NULL DEFAULT 0,
    model               VARCHAR(30) NOT NULL DEFAULT 'linear'
                          CHECK (model IN ('linear', 'time_decay', 'position')),
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_coalition_attribution UNIQUE (tenant_id, campaign_id, customer_id, partner_id)
);

CREATE INDEX IF NOT EXISTS idx_flywheel_coalition_attr_campaign
    ON flywheel_coalition_attribution (tenant_id, campaign_id, partner_id);

-- ===========================================================================
-- STAGE 03 — PERISHABLES / SHELF-LIFE
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_shelf_life (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    store_id            INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    item_id             INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,

    batch_ref           VARCHAR(80) NOT NULL,
    units               INTEGER NOT NULL DEFAULT 0 CHECK (units >= 0),
    received_on         DATE NOT NULL,
    expires_on          DATE NOT NULL,
    CONSTRAINT ck_shelf_life_window CHECK (expires_on >= received_on),

    -- The cost the business eats if the batch is not sold before expiry. Used to
    -- value a markdown: promoting near-expiry stock recovers margin against THIS.
    unit_cost_aed       NUMERIC(12,4) NOT NULL DEFAULT 0,
    status              VARCHAR(20) NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active', 'sold', 'written_off', 'marked_down')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_shelf_life_batch UNIQUE (tenant_id, store_id, item_id, batch_ref)
);

CREATE INDEX IF NOT EXISTS idx_flywheel_shelf_life_expiry
    ON flywheel_shelf_life (tenant_id, expires_on)
    WHERE status = 'active';

-- ===========================================================================
-- STAGE 04 — OUTCOME-BASED PRICING (GATED)
--
-- The agreement can exist; charging on it is gated on evidence. gate_met stays
-- FALSE until the outcome-pricing service confirms the required number of
-- consecutive significant holdout readouts — the plan's "two clean quarters".
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_outcome_pricing (
    id                  BIGSERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    plan_name           VARCHAR(80) NOT NULL,

    -- The share of MEASURED incremental margin charged, e.g. 0.15 = 15%.
    margin_share_pct    NUMERIC(5,4) NOT NULL
                          CHECK (margin_share_pct > 0 AND margin_share_pct <= 0.5),

    -- THE GATE. How many consecutive significant readouts are required before the
    -- share may be charged, and whether that bar is currently met. The service
    -- recomputes gate_met from flywheel_readouts; it is never set by hand.
    gate_readouts_required INTEGER NOT NULL DEFAULT 2 CHECK (gate_readouts_required >= 1),
    gate_met            BOOLEAN NOT NULL DEFAULT FALSE,
    gate_evidence       JSONB NOT NULL DEFAULT '{}'::jsonb,

    status              VARCHAR(20) NOT NULL DEFAULT 'proposed'
                          CHECK (status IN ('proposed', 'active', 'inactive')),
    activated_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_outcome_pricing UNIQUE (tenant_id, plan_name)
);

-- ===========================================================================
-- TENANCY — policy + FORCE RLS + app_rw grants on every new table (ruling #2).
-- ===========================================================================

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'flywheel_seasonality_calendar', 'flywheel_coalition_partners',
        'flywheel_coalition_activity', 'flywheel_coalition_attribution',
        'flywheel_shelf_life', 'flywheel_outcome_pricing'
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

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
        FOREACH t IN ARRAY ARRAY[
            'flywheel_seasonality_calendar', 'flywheel_coalition_partners',
            'flywheel_coalition_activity', 'flywheel_coalition_attribution',
            'flywheel_shelf_life', 'flywheel_outcome_pricing'
        ]
        LOOP
            EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO app_rw', t);
            EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %I_id_seq TO app_rw', t);
        END LOOP;
    END IF;
END $$;

-- ===========================================================================
-- SEED — a UAE seasonality calendar for the demo tenant, so the factor is real
-- on day one. Guarded on tenant 1 existing (the migration-074 lesson).
-- Dates are the 2026 observances; a real deployment refreshes them yearly.
-- ===========================================================================

INSERT INTO flywheel_seasonality_calendar
    (tenant_id, name, kind, starts_on, ends_on, demand_multiplier, note)
SELECT 1, v.name, v.kind, v.starts_on::date, v.ends_on::date, v.mult, v.note
  FROM (VALUES
    ('Ramadan',        'religious',  '2026-02-18', '2026-03-19', 1.85,
        'Grocery demand rises sharply; iftar/suhoor baskets. Retention is worth more.'),
    ('Eid al-Fitr',    'religious',  '2026-03-20', '2026-03-23', 1.60, 'Gifting and feasting spike.'),
    ('Eid al-Adha',    'religious',  '2026-05-27', '2026-05-30', 1.45, 'Second Eid; meat and gifting.'),
    ('Back to School', 'commercial', '2026-08-20', '2026-09-10', 1.25, 'Household restocking.'),
    ('UAE National Day','national',  '2026-12-01', '2026-12-03', 1.20, 'Long weekend demand.'),
    ('Summer Lull',    'seasonal',   '2026-07-01', '2026-08-15', 0.85, 'Residents travel; footfall dips.')
  ) AS v(name, kind, starts_on, ends_on, mult, note)
 WHERE EXISTS (SELECT 1 FROM tenants WHERE id = 1)
   -- NOT EXISTS rather than ON CONFLICT: the seed is idempotent regardless of the
   -- NULL-category subtlety, so re-running the migration never stacks duplicates.
   AND NOT EXISTS (
        SELECT 1 FROM flywheel_seasonality_calendar
         WHERE tenant_id = 1 AND name = v.name AND category IS NULL);

COMMIT;
