-- 075 — FLYWHEEL HARDENING: tax, liability, claw-back, and global contact governance.
--
-- Three gaps that a real CFO and CMO would refuse to sign off on, each found by
-- running the v1 module end to end against live data.
--
-- 1. TAX (CFO). Every price, discount, margin and budget figure in v1 is
--    silently ambiguous about VAT. In the UAE that is a 5% error on every
--    number, and — worse — the MARGIN FLOOR was being checked on the
--    tax-inclusive amount, so a campaign could pass a 10% margin gate while
--    actually earning ~4.8% once VAT is remitted. Tax is now explicit,
--    configurable per tenant, and margin is checked NET of it.
--
-- 2. BREAKAGE + CLAW-BACK (CFO). v1 treated an issued offer as nothing and a
--    redemption as final. Both are wrong:
--      * an ISSUED offer is a LIABILITY (the customer may redeem it), and the
--        unredeemed remainder at expiry is BREAKAGE — a real, reportable figure
--        that must never be double-counted as either spend or saving;
--      * a redeemed offer whose item is RETURNED must claw back the discount
--        spend AND the credited incremental margin, with compensating ledger
--        entries rather than an edit. A ledger you can edit is not a ledger.
--
-- 3. GLOBAL CONTACT GOVERNANCE (CMO). v1 capped contacts PER CAMPAIGN, so two
--    live campaigns could each contact the same customer at their own cap and
--    the customer received double. Caps are a property of the CUSTOMER, not of
--    a campaign. This adds the priority rules that decide which campaign wins
--    when a customer qualifies for several, and records the ones suppressed.

BEGIN;

-- ===========================================================================
-- 1. TAX
-- ===========================================================================

CREATE TABLE IF NOT EXISTS flywheel_tax_rules (
    id            SERIAL PRIMARY KEY,
    tenant_id     INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name          VARCHAR(80) NOT NULL,
    -- UAE standard VAT is 5%. Stored as a rate, never hardcoded in logic.
    rate_pct      NUMERIC(6,3) NOT NULL CHECK (rate_pct >= 0 AND rate_pct < 100),
    -- Do the prices in `items.unit_price_aed` already INCLUDE this tax?
    -- UAE retail displays tax-inclusive shelf prices, so TRUE is the default —
    -- but it must be stated, because the two conventions differ by the rate on
    -- every single figure downstream.
    prices_include_tax BOOLEAN NOT NULL DEFAULT TRUE,
    category      VARCHAR(50),          -- NULL = applies to all categories
    valid_from    DATE NOT NULL DEFAULT CURRENT_DATE,
    valid_until   DATE,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT flywheel_tax_range_ordered
        CHECK (valid_until IS NULL OR valid_until > valid_from)
);
CREATE INDEX IF NOT EXISTS ix_flywheel_tax_lookup
    ON flywheel_tax_rules (tenant_id, is_active, category);

COMMENT ON TABLE flywheel_tax_rules IS
    'Configurable tax rules. Margin floors are evaluated NET of tax — a floor '
    'checked on a tax-inclusive amount silently overstates margin by the rate.';

-- Decisions and redemptions record the tax they assumed, so a historical
-- decision stays explainable after a rate change (the same reason we snapshot
-- price and cost).
ALTER TABLE flywheel_decisions
    ADD COLUMN IF NOT EXISTS tax_rate_pct   NUMERIC(6,3) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS net_price_aed  NUMERIC(12,4) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS margin_net_pct NUMERIC(7,3);

ALTER TABLE flywheel_redemptions
    ADD COLUMN IF NOT EXISTS tax_rate_pct  NUMERIC(6,3) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tax_amount_aed NUMERIC(14,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS net_of_tax_aed NUMERIC(14,2) NOT NULL DEFAULT 0;

-- ===========================================================================
-- 2. BREAKAGE + CLAW-BACK
-- ===========================================================================

-- An issued offer is a LIABILITY. This records the lifecycle of that liability
-- separately from cash spend, because a CFO needs to see committed-but-unspent
-- exposure without it polluting the spend figure.
ALTER TABLE flywheel_offers
    ADD COLUMN IF NOT EXISTS liability_aed      NUMERIC(14,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS liability_released BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS breakage_aed       NUMERIC(14,2) NOT NULL DEFAULT 0;

-- PROOF CHECK: breakage is only meaningful once the liability is released.
-- A row claiming breakage while still liable is contradictory.
ALTER TABLE flywheel_offers DROP CONSTRAINT IF EXISTS flywheel_offer_breakage_requires_release;
ALTER TABLE flywheel_offers
    ADD CONSTRAINT flywheel_offer_breakage_requires_release
    CHECK (breakage_aed = 0 OR liability_released = TRUE);

CREATE TABLE IF NOT EXISTS flywheel_returns (
    id                BIGSERIAL PRIMARY KEY,
    tenant_id         INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    redemption_id     BIGINT NOT NULL REFERENCES flywheel_redemptions(id) ON DELETE CASCADE,
    campaign_id       INTEGER REFERENCES flywheel_campaigns(id) ON DELETE SET NULL,
    customer_id       INTEGER REFERENCES flywheel_customers(id) ON DELETE SET NULL,
    units_returned    INTEGER NOT NULL CHECK (units_returned > 0),
    -- What we give back to the customer, and what we take back from the
    -- campaign's books. These are DIFFERENT numbers and conflating them is how
    -- a returns process quietly overstates campaign performance.
    refund_aed        NUMERIC(14,2) NOT NULL DEFAULT 0,
    discount_clawed_back_aed NUMERIC(14,2) NOT NULL DEFAULT 0,
    margin_clawed_back_aed   NUMERIC(14,2) NOT NULL DEFAULT 0,
    restocked         BOOLEAN NOT NULL DEFAULT TRUE,
    reason            TEXT,
    idempotency_key   VARCHAR(120) NOT NULL,
    request_id        VARCHAR(64),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Returns are as replayable as redemptions and need the same protection:
    -- a retried return must not claw back twice.
    CONSTRAINT uq_flywheel_return_idem UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_flywheel_returns_campaign
    ON flywheel_returns (tenant_id, campaign_id, created_at DESC);

-- The ledger gains two entry types. They are SEPARATE from RELEASED because
-- they mean different things to finance: RELEASED is unused reservation
-- returning to the pool; CLAWED_BACK is spend being reversed after the fact;
-- BREAKAGE is liability that expired unredeemed.
ALTER TABLE flywheel_budget_ledger DROP CONSTRAINT IF EXISTS flywheel_budget_ledger_entry_type_check;
ALTER TABLE flywheel_budget_ledger
    ADD CONSTRAINT flywheel_budget_ledger_entry_type_check
    CHECK (entry_type IN ('ALLOCATED', 'RESERVED', 'COMMITTED',
                          'SPENT', 'RELEASED', 'CLAWED_BACK', 'BREAKAGE'));

ALTER TABLE flywheel_budgets
    ADD COLUMN IF NOT EXISTS clawed_back_aed NUMERIC(16,2) NOT NULL DEFAULT 0
        CHECK (clawed_back_aed >= 0),
    ADD COLUMN IF NOT EXISTS breakage_aed    NUMERIC(16,2) NOT NULL DEFAULT 0
        CHECK (breakage_aed >= 0);

ALTER TABLE flywheel_campaign_outcomes
    ADD COLUMN IF NOT EXISTS breakage_aed        NUMERIC(16,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS breakage_rate       NUMERIC(6,5) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS clawed_back_aed     NUMERIC(16,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS returned_units      INTEGER NOT NULL DEFAULT 0;

-- ===========================================================================
-- 3. GLOBAL CONTACT GOVERNANCE
-- ===========================================================================

-- Caps belong to the CUSTOMER and span every campaign and channel. v1's
-- per-campaign cap meant N live campaigns could each contact at their own cap.
CREATE TABLE IF NOT EXISTS flywheel_contact_policy (
    id                     SERIAL PRIMARY KEY,
    tenant_id              INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    -- NULL channel = the ALL-CHANNEL ceiling. A customer may tolerate 3 emails
    -- OR 2 SMS but not 3 + 2, so both a per-channel and a total cap are needed.
    channel                VARCHAR(20),
    max_contacts_per_week  INTEGER NOT NULL DEFAULT 3 CHECK (max_contacts_per_week >= 0),
    max_contacts_per_day   INTEGER NOT NULL DEFAULT 1 CHECK (max_contacts_per_day >= 0),
    -- Quiet period after a customer ignores several offers in a row.
    cooldown_days_after_ignores INTEGER NOT NULL DEFAULT 14,
    ignores_before_cooldown     INTEGER NOT NULL DEFAULT 3,
    is_active              BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_flywheel_contact_policy UNIQUE (tenant_id, channel)
);

-- Which campaign wins when a customer qualifies for several. Deterministic, so
-- the same customer in the same state always resolves the same way.
ALTER TABLE flywheel_campaigns
    ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 100,
    -- An exclusive campaign suppresses all others for its audience.
    ADD COLUMN IF NOT EXISTS is_exclusive BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN flywheel_campaigns.priority IS
    'Lower wins. Ties break on higher EIV, then lower campaign id, so the '
    'resolution is total and reproducible rather than dependent on row order.';

-- Every suppressed campaign is RECORDED. Silent suppression is how a marketer
-- loses trust in the system: they need to see that their campaign was eligible
-- and lost, and to what.
CREATE TABLE IF NOT EXISTS flywheel_offer_suppressions (
    id                 BIGSERIAL PRIMARY KEY,
    tenant_id          INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_id        INTEGER NOT NULL REFERENCES flywheel_customers(id) ON DELETE CASCADE,
    suppressed_campaign_id INTEGER NOT NULL REFERENCES flywheel_campaigns(id) ON DELETE CASCADE,
    winning_campaign_id    INTEGER REFERENCES flywheel_campaigns(id) ON DELETE SET NULL,
    reason_code        VARCHAR(40) NOT NULL,
    detail             TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_flywheel_suppressions_customer
    ON flywheel_offer_suppressions (tenant_id, customer_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_flywheel_suppressions_campaign
    ON flywheel_offer_suppressions (tenant_id, suppressed_campaign_id);

-- The contact log needs a fast rolling-window read per customer ACROSS
-- campaigns — that is the whole point of a global cap.
CREATE INDEX IF NOT EXISTS ix_flywheel_contact_global
    ON flywheel_contact_log (tenant_id, customer_id, channel, contacted_at DESC);

-- ===========================================================================
-- RLS on the new tables — same pattern as 074.
-- ===========================================================================

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'flywheel_tax_rules', 'flywheel_returns', 'flywheel_contact_policy',
        'flywheel_offer_suppressions'
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
-- SEED — UAE defaults for the demo tenant.
-- ===========================================================================

INSERT INTO flywheel_tax_rules (tenant_id, name, rate_pct, prices_include_tax, category)
VALUES (1, 'UAE VAT (standard rate)', 5.000, TRUE, NULL)
ON CONFLICT DO NOTHING;

-- A total ceiling plus per-channel caps. The all-channel row (channel NULL) is
-- the one that stops a customer receiving 3 emails AND 2 SMS in a week.
INSERT INTO flywheel_contact_policy
    (tenant_id, channel, max_contacts_per_week, max_contacts_per_day)
VALUES
    (1, NULL,      4, 1),
    (1, 'email',   3, 1),
    (1, 'sms',     2, 1),
    (1, 'push',    3, 1),
    (1, 'app',     5, 2),
    (1, 'in_store',7, 2)
ON CONFLICT (tenant_id, channel) DO NOTHING;

COMMIT;

DO $$ BEGIN
    RAISE NOTICE 'Flywheel hardening ready: VAT-aware margins, breakage + claw-back ledger, global contact governance';
END $$;
