-- =============================================================================
-- 041_tenant_billing_profile.sql  (UAE SaaS Phase 1 — commercial control plane)
-- Per-tenant UAE legal + billing profile. One row per tenant (tenant_id is the
-- PK and FK), holding the fields a UAE invoice / enterprise-procurement / VAT flow
-- needs: TRN, trade licence, emirate, free-zone vs mainland, VAT-registration,
-- AR legal name, billing/finance contacts, plus AED/Asia-Dubai defaults.
--
-- Purely ADDITIVE: no existing table or flow changes. Tenant-scoped + RLS like the
-- rest of the schema (current_tenant_id() helper from migration 012). Grants for
-- the non-owner app_rw role inherit from the ALTER DEFAULT PRIVILEGES set in 020.
--
-- NOTE (legal): VAT/TRN/trade-licence handling here is data modelling only. It is
-- NOT a compliance guarantee. Any tax/legal use is "Draft — requires review by a
-- qualified UAE legal/tax professional before production/customer use."
-- =============================================================================

CREATE TABLE IF NOT EXISTS tenant_billing_profile (
    tenant_id          INTEGER PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,

    -- Legal identity
    legal_name         TEXT,                         -- registered company name (EN)
    legal_name_ar      TEXT,                         -- registered company name (AR)
    trading_name       TEXT,                         -- "doing business as"
    trn                VARCHAR(15),                  -- UAE Tax Registration Number (15 digits)
    trade_license_no   TEXT,
    emirate            TEXT CHECK (emirate IS NULL OR emirate IN
                         ('abu_dhabi','dubai','sharjah','ajman','umm_al_quwain',
                          'ras_al_khaimah','fujairah')),
    jurisdiction       TEXT CHECK (jurisdiction IS NULL OR jurisdiction IN ('mainland','free_zone')),
    free_zone_name     TEXT,                         -- only meaningful when jurisdiction = free_zone
    vat_registered     BOOLEAN NOT NULL DEFAULT TRUE,

    -- Addresses
    registered_address TEXT,
    billing_address    TEXT,

    -- Locale / money defaults (UAE-first; GCC-expandable later)
    currency           CHAR(3) NOT NULL DEFAULT 'AED' CHECK (currency ~ '^[A-Z]{3}$'),
    timezone           TEXT NOT NULL DEFAULT 'Asia/Dubai',
    preferred_language VARCHAR(2) NOT NULL DEFAULT 'en' CHECK (preferred_language IN ('en','ar')),

    -- Commercial profile (drives plan sizing + sales-assisted onboarding)
    industry_vertical  TEXT,                         -- grocery / pharmacy / fashion / electronics / f&b / ...
    store_count        INTEGER CHECK (store_count IS NULL OR store_count >= 0),
    sku_count          INTEGER CHECK (sku_count IS NULL OR sku_count >= 0),
    procurement_type   TEXT,                         -- self_serve / manual_invoice / purchase_order

    -- Contacts
    billing_contact_name  TEXT,
    billing_contact_email TEXT,
    billing_contact_phone TEXT,
    finance_contact_name  TEXT,
    finance_contact_email TEXT,
    finance_contact_phone TEXT,

    created_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- RLS: a tenant only ever sees/edits its own profile (mirrors migration 039).
ALTER TABLE tenant_billing_profile ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON tenant_billing_profile;
CREATE POLICY tenant_isolation ON tenant_billing_profile
    USING (tenant_id = current_tenant_id())
    WITH CHECK (tenant_id = current_tenant_id());

-- Seed a UAE profile for the demo tenant (id 1 = Meridian) so the settings screen
-- has something real to show. Idempotent; only fills a brand-new row.
INSERT INTO tenant_billing_profile (
    tenant_id, legal_name, legal_name_ar, trading_name, emirate, jurisdiction,
    vat_registered, industry_vertical, store_count, sku_count, procurement_type,
    preferred_language
) VALUES (
    1, 'Meridian Retail LLC', 'ميريديان للتجزئة ش.ذ.م.م', 'Meridian Hypermarket',
    'dubai', 'mainland', TRUE, 'grocery', 10, 50, 'manual_invoice', 'en'
) ON CONFLICT (tenant_id) DO NOTHING;

DO $$ BEGIN RAISE NOTICE 'tenant_billing_profile: UAE legal/billing profile ready (RLS on)'; END $$;
