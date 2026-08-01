
SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public;

COMMENT ON EXTENSION btree_gist IS 'support for indexing common datatypes in GiST';

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';

CREATE TYPE public.alert_severity AS ENUM (
    'info',
    'warning',
    'critical'
);

CREATE TYPE public.alert_status AS ENUM (
    'active',
    'acknowledged',
    'resolved',
    'snoozed',
    'expired'
);

CREATE TYPE public.alert_type AS ENUM (
    'low_stock',
    'stockout',
    'overstock',
    'sales_anomaly',
    'returns_anomaly',
    'shrinkage_threshold',
    'dead_stock',
    'forecast_deviation',
    'system_health',
    'expiry_risk'
);

CREATE TYPE public.audit_action AS ENUM (
    'login',
    'logout',
    'login_failed',
    'view_dashboard',
    'view_report',
    'export_data',
    'create_record',
    'update_record',
    'delete_record',
    'change_password',
    'update_profile',
    'create_user',
    'update_user',
    'delete_user',
    'create_alert',
    'acknowledge_alert',
    'create_promotion',
    'update_promotion',
    'stock_transfer',
    'inventory_adjustment'
);

CREATE TYPE public.employee_department AS ENUM (
    'management',
    'sales',
    'inventory',
    'customer_service',
    'finance',
    'hr',
    'it',
    'logistics',
    'marketing'
);

CREATE TYPE public.employee_status AS ENUM (
    'active',
    'inactive',
    'terminated',
    'on_leave'
);

CREATE TYPE public.inventory_transaction_type AS ENUM (
    'sale',
    'return',
    'restock',
    'transfer_in',
    'transfer_out',
    'adjustment_positive',
    'adjustment_negative',
    'shrinkage',
    'damage',
    'expired'
);

CREATE TYPE public.notification_channel AS ENUM (
    'in_app',
    'email',
    'sms',
    'slack',
    'teams'
);

CREATE TYPE public.performance_period AS ENUM (
    'daily',
    'weekly',
    'monthly',
    'quarterly',
    'yearly'
);

CREATE TYPE public.promotion_status AS ENUM (
    'draft',
    'scheduled',
    'active',
    'paused',
    'ended',
    'cancelled'
);

CREATE TYPE public.promotion_type AS ENUM (
    'percentage_discount',
    'fixed_discount',
    'buy_one_get_one',
    'buy_x_get_y',
    'bundle_deal',
    'clearance',
    'loyalty_exclusive'
);

CREATE TYPE public.region_code AS ENUM (
    'dubai',
    'abu_dhabi',
    'northern_emirates',
    'all'
);

CREATE TYPE public.report_format AS ENUM (
    'pdf',
    'excel',
    'csv',
    'json'
);

CREATE TYPE public.report_frequency AS ENUM (
    'once',
    'daily',
    'weekly',
    'monthly',
    'quarterly'
);

CREATE TYPE public.report_status AS ENUM (
    'pending',
    'generating',
    'completed',
    'failed'
);

CREATE TYPE public.shrinkage_reason AS ENUM (
    'theft',
    'damage',
    'expired',
    'administrative_error',
    'vendor_fraud',
    'unknown'
);

CREATE TYPE public.transaction_type AS ENUM (
    'sale',
    'return',
    'void',
    'exchange',
    'refund'
);

CREATE TYPE public.transfer_status AS ENUM (
    'pending',
    'approved',
    'in_transit',
    'completed',
    'cancelled'
);

CREATE TYPE public.user_role AS ENUM (
    'super_admin',
    'regional_manager',
    'store_manager',
    'analyst'
);

CREATE TYPE public.user_status AS ENUM (
    'active',
    'inactive',
    'locked',
    'pending'
);

CREATE FUNCTION public.calculate_performance_grade(score numeric) RETURNS character varying
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF score >= 95 THEN RETURN 'A+';
    ELSIF score >= 90 THEN RETURN 'A';
    ELSIF score >= 85 THEN RETURN 'B+';
    ELSIF score >= 80 THEN RETURN 'B';
    ELSIF score >= 70 THEN RETURN 'C';
    ELSIF score >= 60 THEN RETURN 'D';
    ELSE RETURN 'F';
    END IF;
END;
$$;

CREATE FUNCTION public.calculate_performance_score(sales_pct numeric, customer_rating numeric, attendance_pct numeric, return_rate numeric) RETURNS numeric
    LANGUAGE plpgsql
    AS $$
DECLARE
    score DECIMAL;
BEGIN
    -- Weighted scoring: Sales 40%, Customer Rating 25%, Attendance 25%, Low Returns 10%
    score := (
        (LEAST(sales_pct, 150) / 150 * 40) +  -- Cap at 150% for max score
        (customer_rating / 5 * 25) +
        (attendance_pct / 100 * 25) +
        ((100 - LEAST(return_rate, 100)) / 100 * 10)  -- Lower returns = higher score
    );
    RETURN ROUND(score, 2);
END;
$$;

CREATE FUNCTION public.create_sales_stream_partition(p_parent text, p_month date) RETURNS text
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_start DATE := date_trunc('month', p_month)::date;
    v_end   DATE := (date_trunc('month', p_month) + INTERVAL '1 month')::date;
    v_name  TEXT := format('%s_%s', p_parent, to_char(v_start, 'YYYY_MM'));
BEGIN
    IF to_regclass(v_name) IS NOT NULL THEN
        RETURN v_name;
    END IF;
    EXECUTE format(
        'CREATE TABLE %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)',
        v_name, p_parent, v_start, v_end);
    RETURN v_name;
END $$;

CREATE FUNCTION public.current_allowed_store_ids() RETURNS integer[]
    LANGUAGE sql STABLE
    AS $$
    SELECT CASE
        WHEN COALESCE(current_setting('app.allowed_store_ids', true), '') IN ('', '{}')
            THEN NULL
        ELSE string_to_array(
                 trim(both '{}' FROM current_setting('app.allowed_store_ids', true)),
                 ','
             )::int[]
    END;
$$;

CREATE FUNCTION public.current_tenant_id() RETURNS integer
    LANGUAGE sql STABLE
    AS $$
    SELECT COALESCE(NULLIF(current_setting('app.tenant_id', true), '')::int, 1);
$$;

CREATE FUNCTION public.demo_tenant_id() RETURNS integer
    LANGUAGE sql STABLE
    AS $$
    SELECT COALESCE(
        (SELECT id FROM tenants WHERE slug = 'demo' ORDER BY id LIMIT 1),
        1
    );
$$;

CREATE FUNCTION public.deprovision_tenant_schema(p_tenant_id integer, p_force boolean DEFAULT false) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_schema TEXT := format('tenant_%s', p_tenant_id);
BEGIN
    IF to_regclass(format('%I.stores', v_schema)) IS NULL AND NOT p_force THEN
        RETURN FALSE;  -- nothing to drop
    END IF;
    -- CASCADE drops the tenant's isolated tables. Guarded by the caller: only ever
    -- invoked for a tenant explicitly being deprovisioned.
    EXECUTE format('DROP SCHEMA IF EXISTS %I CASCADE', v_schema);
    RETURN TRUE;
END $$;

CREATE FUNCTION public.ensure_external_sales_partition(p_day date) RETURNS text
    LANGUAGE plpgsql
    AS $$
DECLARE
    m_start DATE := date_trunc('month', p_day)::date;
    m_end   DATE := (date_trunc('month', p_day) + interval '1 month')::date;
    part    TEXT := 'external_sales_' || to_char(m_start, 'YYYYMM');
BEGIN
    IF to_regclass(part) IS NULL THEN
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF external_sales
             FOR VALUES FROM (%L) TO (%L)', part, m_start, m_end);
    END IF;
    RETURN part;
END $$;

CREATE FUNCTION public.ensure_sales_stream_partitions(p_months_ahead integer DEFAULT 3) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_month DATE := date_trunc('month', now())::date;
    v_last  DATE := (date_trunc('month', now()) + make_interval(months => p_months_ahead))::date;
    v_made  INTEGER := 0;
BEGIN
    WHILE v_month <= v_last LOOP
        IF to_regclass(format('sales_stream_raw_%s', to_char(v_month, 'YYYY_MM'))) IS NULL THEN
            PERFORM create_sales_stream_partition('sales_stream_raw', v_month);
            v_made := v_made + 1;
        END IF;
        v_month := (v_month + INTERVAL '1 month')::date;
    END LOOP;
    RETURN v_made;
END $$;

CREATE FUNCTION public.flywheel_forbid_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

CREATE FUNCTION public.flywheel_settlement_immutable() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

CREATE FUNCTION public.get_user_accessible_stores(p_user_id integer) RETURNS TABLE(store_id integer)
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_role user_role;
BEGIN
    SELECT role INTO v_role FROM users WHERE id = p_user_id;
    
    -- Super admin gets all stores
    IF v_role = 'super_admin' THEN
        RETURN QUERY SELECT s.id FROM stores s;
        RETURN;
    END IF;
    
    -- Get stores from direct permissions and regional permissions
    RETURN QUERY
    SELECT DISTINCT s.id
    FROM stores s
    LEFT JOIN user_permissions up_store ON up_store.store_id = s.id AND up_store.user_id = p_user_id
    LEFT JOIN user_permissions up_region ON up_region.region_id = s.region_id AND up_region.user_id = p_user_id
    WHERE (up_store.id IS NOT NULL OR up_region.id IS NOT NULL)
    AND (up_store.can_view = TRUE OR up_region.can_view = TRUE);
END;
$$;

CREATE FUNCTION public.item_cost_at(p_tenant_id integer, p_item_id integer, p_date date) RETURNS numeric
    LANGUAGE sql STABLE
    AS $$
    SELECT c.unit_cost_aed
      FROM item_costs c
     WHERE c.tenant_id = p_tenant_id
       AND c.item_id   = p_item_id
       AND p_date     >= c.valid_from
       AND (c.valid_until IS NULL OR p_date < c.valid_until)
     LIMIT 1;
$$;

COMMENT ON FUNCTION public.item_cost_at(p_tenant_id integer, p_item_id integer, p_date date) IS 'The unit cost in effect for this item on this date, or NULL when none covers it. The exclusion constraint guarantees at most one match.';

CREATE FUNCTION public.item_costs_sync_current() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    target_tenant INTEGER := COALESCE(NEW.tenant_id, OLD.tenant_id);
    target_item   INTEGER := COALESCE(NEW.item_id,   OLD.item_id);
BEGIN
    UPDATE items
       SET unit_cost_aed = item_cost_at(target_tenant, target_item, CURRENT_DATE)
     WHERE id = target_item
       AND tenant_id = target_tenant;
    RETURN NULL;  -- AFTER trigger
END;
$$;

CREATE FUNCTION public.operations_proposal_touch() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := now();
    -- Only advance when the caller did not already bump it (lets a compare-and-
    -- swap `SET version = version + 1 WHERE version = :expected` stay exact).
    IF NEW.version = OLD.version THEN
        NEW.version := OLD.version + 1;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.provision_tenant_schema(p_tenant_id integer) RETURNS text
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_schema TEXT := format('tenant_%s', p_tenant_id);
    v_tbl    TEXT;
    -- The tenant's own transactional/PII data. NOT the partitioned synthetic
    -- stream (demo-only) and NOT the shared reference/control tables.
    v_tables TEXT[] := ARRAY[
        'stores', 'items', 'suppliers', 'sales_historical', 'inventory',
        'purchase_orders', 'promotions', 'item_costs'
    ];
BEGIN
    EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I', v_schema);
    FOREACH v_tbl IN ARRAY v_tables LOOP
        -- Only clone tables that actually exist in public (schema evolves).
        IF to_regclass(format('public.%I', v_tbl)) IS NOT NULL
           AND to_regclass(format('%I.%I', v_schema, v_tbl)) IS NULL THEN
            EXECUTE format('CREATE TABLE %I.%I (LIKE public.%I INCLUDING ALL)',
                           v_schema, v_tbl, v_tbl);
        END IF;
    END LOOP;
    RETURN v_schema;
END $$;

CREATE FUNCTION public.prune_sales_stream_partitions(p_retention_months integer) RETURNS TABLE(dropped text)
    LANGUAGE plpgsql
    AS $_$
DECLARE
    v_cutoff DATE;
    v_rec    RECORD;
BEGIN
    IF p_retention_months IS NULL OR p_retention_months < 1 THEN
        RAISE EXCEPTION 'retention must be at least 1 month, got %', p_retention_months;
    END IF;
    v_cutoff := date_trunc('month', now() - make_interval(months => p_retention_months))::date;

    FOR v_rec IN
        SELECT c.relname
          FROM pg_class c
          JOIN pg_inherits i ON i.inhrelid = c.oid
          JOIN pg_class p ON p.oid = i.inhparent
         WHERE p.relname = 'sales_stream_raw'
           AND c.relname ~ '^sales_stream_raw_\d{4}_\d{2}$'
           -- The partition's month, parsed from its name, is strictly older.
           AND to_date(right(c.relname, 7), 'YYYY_MM') < v_cutoff
    LOOP
        EXECUTE format('DROP TABLE %I', v_rec.relname);
        dropped := v_rec.relname;
        RETURN NEXT;
    END LOOP;
END $_$;

CREATE FUNCTION public.refresh_analytics_views() RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_sales_by_store;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_weekly_sales_by_category;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_hourly_sales_pattern;
END;
$$;

CREATE FUNCTION public.refresh_sales_rollup_daily(p_tenant integer, p_from date, p_to date) RETURNS bigint
    LANGUAGE plpgsql
    AS $$
DECLARE
    n BIGINT;
BEGIN
    DELETE FROM sales_rollup_daily
     WHERE tenant_id = p_tenant AND day >= p_from AND day <= p_to;
    INSERT INTO sales_rollup_daily
        (tenant_id, store_id, item_id, day, units, revenue_aed, txn_count, updated_at)
    SELECT tenant_id, store_id, item_id, sale_date,
           SUM(units), COALESCE(SUM(revenue_aed), 0), SUM(txn_count), now()
      FROM external_sales
     WHERE tenant_id = p_tenant AND sale_date >= p_from AND sale_date <= p_to
     GROUP BY tenant_id, store_id, item_id, sale_date;
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END $$;

CREATE FUNCTION public.sage_store_in_scope(p_store_id integer) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    SELECT current_allowed_store_ids() IS NULL
        OR p_store_id = ANY (current_allowed_store_ids());
$$;

CREATE FUNCTION public.sales_stream_raw_confine_synthetic() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    demo_id INTEGER := demo_tenant_id();
BEGIN
    IF NEW.is_synthetic AND NEW.tenant_id IS DISTINCT FROM demo_id THEN
        RAISE EXCEPTION
            'synthetic sale rejected: tenant_id % is not the demo tenant (%)',
            NEW.tenant_id, demo_id
            USING ERRCODE = 'check_violation',
                  HINT = 'Synthetic sales may only be written to the demo tenant. '
                         'See E0-8 / services/data_generator.py.';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.set_item_cost(p_tenant_id integer, p_item_id integer, p_cost numeric, p_from date DEFAULT CURRENT_DATE, p_source character varying DEFAULT 'import'::character varying) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    -- Any period already starting at/after p_from is superseded outright.
    DELETE FROM item_costs
     WHERE tenant_id = p_tenant_id AND item_id = p_item_id
       AND valid_from >= p_from;

    -- Close the period straddling p_from so the new one can start there.
    UPDATE item_costs
       SET valid_until = p_from
     WHERE tenant_id = p_tenant_id AND item_id = p_item_id
       AND valid_from < p_from
       AND (valid_until IS NULL OR valid_until > p_from);

    INSERT INTO item_costs (tenant_id, item_id, unit_cost_aed, valid_from, valid_until, source)
    VALUES (p_tenant_id, p_item_id, p_cost, p_from, NULL, p_source);
END;
$$;

COMMENT ON FUNCTION public.set_item_cost(p_tenant_id integer, p_item_id integer, p_cost numeric, p_from date, p_source character varying) IS 'Record a cost effective from p_from onward: closes the straddling period and supersedes any later ones. The only supported way to write item_costs.';

CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;

CREATE FUNCTION public.user_can_access_store(p_user_id integer, p_store_id integer) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_role user_role;
    v_has_permission BOOLEAN;
BEGIN
    -- Get user role
    SELECT role INTO v_role FROM users WHERE id = p_user_id;
    
    -- Super admin can access everything
    IF v_role = 'super_admin' THEN
        RETURN TRUE;
    END IF;
    
    -- Check direct store permission
    SELECT EXISTS (
        SELECT 1 FROM user_permissions 
        WHERE user_id = p_user_id 
        AND store_id = p_store_id
        AND can_view = TRUE
        AND (valid_until IS NULL OR valid_until >= CURRENT_DATE)
    ) INTO v_has_permission;
    
    IF v_has_permission THEN
        RETURN TRUE;
    END IF;
    
    -- Check regional permission
    SELECT EXISTS (
        SELECT 1 FROM user_permissions up
        JOIN stores s ON s.region_id = up.region_id
        WHERE up.user_id = p_user_id 
        AND s.id = p_store_id
        AND up.can_view = TRUE
        AND (up.valid_until IS NULL OR up.valid_until >= CURRENT_DATE)
    ) INTO v_has_permission;
    
    RETURN v_has_permission;
END;
$$;

SET default_tablespace = '';

SET default_table_access_method = heap;

CREATE TABLE public.action_drafts (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    finding_id integer,
    draft_type text NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    title text NOT NULL,
    summary text,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    source_action_type text,
    created_by text,
    reviewed_by text,
    review_note text,
    reviewed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT action_drafts_draft_type_check CHECK ((draft_type = ANY (ARRAY['supplier_email'::text, 'markdown_proposal'::text, 'promotion_proposal'::text, 'review_task'::text, 'purchase_order'::text]))),
    CONSTRAINT action_drafts_status_check CHECK ((status = ANY (ARRAY['draft'::text, 'approved'::text, 'rejected'::text])))
);

CREATE SEQUENCE public.action_drafts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.action_drafts_id_seq OWNED BY public.action_drafts.id;

CREATE TABLE public.alert_notifications (
    id integer NOT NULL,
    alert_id integer NOT NULL,
    user_id integer NOT NULL,
    channel public.notification_channel NOT NULL,
    sent_at timestamp with time zone,
    delivered_at timestamp with time zone,
    read_at timestamp with time zone,
    failed_at timestamp with time zone,
    failure_reason text,
    retry_count integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE public.alert_notifications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.alert_notifications_id_seq OWNED BY public.alert_notifications.id;

CREATE TABLE public.alert_rules (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    alert_type public.alert_type NOT NULL,
    severity public.alert_severity DEFAULT 'warning'::public.alert_severity NOT NULL,
    store_id integer,
    item_id integer,
    category character varying(50),
    condition character varying(50) NOT NULL,
    threshold_value numeric(12,2) NOT NULL,
    comparison_period character varying(50),
    notify_roles text[],
    notify_users integer[],
    channels public.notification_channel[] DEFAULT ARRAY['in_app'::public.notification_channel],
    check_frequency_minutes integer DEFAULT 60,
    last_checked_at timestamp with time zone,
    is_active boolean DEFAULT true,
    created_by integer,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE public.alert_rules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.alert_rules_id_seq OWNED BY public.alert_rules.id;

CREATE TABLE public.alerts (
    id integer NOT NULL,
    alert_type public.alert_type NOT NULL,
    severity public.alert_severity DEFAULT 'warning'::public.alert_severity NOT NULL,
    status public.alert_status DEFAULT 'active'::public.alert_status NOT NULL,
    store_id integer,
    item_id integer,
    region_id integer,
    title character varying(255) NOT NULL,
    message text NOT NULL,
    details jsonb DEFAULT '{}'::jsonb,
    threshold_value numeric(12,2),
    actual_value numeric(12,2),
    acknowledged_by integer,
    acknowledged_at timestamp with time zone,
    resolved_by integer,
    resolved_at timestamp with time zone,
    resolution_notes text,
    snoozed_until timestamp with time zone,
    snooze_count integer DEFAULT 0,
    escalated boolean DEFAULT false,
    escalated_to integer,
    escalated_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    assigned_to integer,
    assigned_by integer,
    assigned_at timestamp with time zone,
    dedupe_key character varying(255)
);

CREATE SEQUENCE public.alerts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.alerts_id_seq OWNED BY public.alerts.id;

CREATE TABLE public.approval_rules (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    auto_approve_under numeric(14,2) DEFAULT 0 NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE ONLY public.approval_rules FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.approval_rules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.approval_rules_id_seq OWNED BY public.approval_rules.id;

CREATE TABLE public.audit_log (
    id bigint NOT NULL,
    user_id integer,
    user_email character varying(255),
    action character varying(50) NOT NULL,
    resource_type character varying(100),
    resource_id character varying(100),
    description text,
    old_values jsonb,
    new_values jsonb,
    ip_address character varying(45),
    user_agent text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE public.audit_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.audit_log_id_seq OWNED BY public.audit_log.id;

CREATE TABLE public.auth_tokens (
    id bigint NOT NULL,
    token_hash character varying(64) NOT NULL,
    token_type character varying(32) NOT NULL,
    user_id integer,
    tenant_id integer,
    email character varying(255),
    role character varying(50),
    invited_by integer,
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE public.auth_tokens_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.auth_tokens_id_seq OWNED BY public.auth_tokens.id;

CREATE TABLE public.basket_associations (
    id integer NOT NULL,
    item_a_id integer NOT NULL,
    item_b_id integer NOT NULL,
    support numeric(8,6) NOT NULL,
    confidence numeric(8,6) NOT NULL,
    lift numeric(8,4) NOT NULL,
    transactions_both integer NOT NULL,
    transactions_a integer NOT NULL,
    transactions_b integer NOT NULL,
    total_transactions integer NOT NULL,
    analysis_start_date date NOT NULL,
    analysis_end_date date NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT different_items CHECK ((item_a_id < item_b_id))
);

CREATE SEQUENCE public.basket_associations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.basket_associations_id_seq OWNED BY public.basket_associations.id;

CREATE TABLE public.bespoke_requests (
    id integer NOT NULL,
    tenant_id integer,
    title text NOT NULL,
    client_description text NOT NULL,
    status text DEFAULT 'requested'::text NOT NULL,
    priority text DEFAULT 'medium'::text NOT NULL,
    scoping_notes text,
    estimate text,
    ai_suggestion jsonb,
    delivered_at timestamp with time zone,
    created_by text,
    updated_by text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT bespoke_declined_has_reason CHECK (((status <> 'declined'::text) OR (scoping_notes IS NOT NULL))),
    CONSTRAINT bespoke_delivered_has_timestamp CHECK (((status <> 'delivered'::text) OR (delivered_at IS NOT NULL))),
    CONSTRAINT bespoke_requests_priority_check CHECK ((priority = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text, 'vip'::text]))),
    CONSTRAINT bespoke_requests_status_check CHECK ((status = ANY (ARRAY['requested'::text, 'scoped'::text, 'approved'::text, 'building'::text, 'delivered'::text, 'declined'::text])))
);

CREATE SEQUENCE public.bespoke_requests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.bespoke_requests_id_seq OWNED BY public.bespoke_requests.id;

CREATE TABLE public.campaign_allocations (
    id integer NOT NULL,
    tenant_id integer DEFAULT 1 NOT NULL,
    campaign_id integer NOT NULL,
    store_id integer NOT NULL,
    item_id integer NOT NULL,
    allocated_units integer NOT NULL,
    consumed_units integer DEFAULT 0 NOT NULL,
    released_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT campaign_allocations_allocated_units_check CHECK ((allocated_units >= 0)),
    CONSTRAINT ck_alloc_consumed CHECK (((consumed_units >= 0) AND (consumed_units <= allocated_units)))
);

CREATE SEQUENCE public.campaign_allocations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.campaign_allocations_id_seq OWNED BY public.campaign_allocations.id;

CREATE TABLE public.campaign_offers (
    id integer NOT NULL,
    tenant_id integer DEFAULT 1 NOT NULL,
    campaign_id integer NOT NULL,
    customer_id integer NOT NULL,
    store_id integer NOT NULL,
    cohort character varying(10) NOT NULL,
    churn_score numeric(4,3) NOT NULL,
    response_prob numeric(4,3) DEFAULT 0 NOT NULL,
    action character varying(30) DEFAULT 'NO_ACTION'::character varying NOT NULL,
    item_id integer,
    discount_pct numeric(5,2) DEFAULT 0 NOT NULL,
    unit_price_aed numeric(12,2),
    unit_cost_aed numeric(12,4),
    expected_value_aed numeric(12,2) DEFAULT 0 NOT NULL,
    reason_codes jsonb DEFAULT '[]'::jsonb NOT NULL,
    status character varying(20) DEFAULT 'planned'::character varying NOT NULL,
    issued_at timestamp with time zone,
    expires_at timestamp with time zone,
    redeemed_at timestamp with time zone,
    redemption_key character varying(80),
    redemption_amount_aed numeric(12,2),
    CONSTRAINT campaign_offers_cohort_check CHECK (((cohort)::text = ANY ((ARRAY['treatment'::character varying, 'control'::character varying])::text[]))),
    CONSTRAINT campaign_offers_status_check CHECK (((status)::text = ANY ((ARRAY['planned'::character varying, 'issued'::character varying, 'redeemed'::character varying, 'expired'::character varying, 'suppressed'::character varying])::text[])))
);

CREATE SEQUENCE public.campaign_offers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.campaign_offers_id_seq OWNED BY public.campaign_offers.id;

CREATE TABLE public.company_targets (
    id bigint NOT NULL,
    tenant_id integer DEFAULT 1 NOT NULL,
    metric text NOT NULL,
    label text NOT NULL,
    year integer NOT NULL,
    value numeric NOT NULL,
    unit text DEFAULT 'AED'::text NOT NULL,
    source_doc text
);

CREATE SEQUENCE public.company_targets_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.company_targets_id_seq OWNED BY public.company_targets.id;

CREATE TABLE public.competitor_prices (
    id integer NOT NULL,
    item_id integer NOT NULL,
    competitor_name character varying(100) NOT NULL,
    competitor_price numeric(10,2) NOT NULL,
    our_price numeric(10,2),
    price_difference numeric(10,2),
    location character varying(100),
    store_id integer,
    observed_date date DEFAULT CURRENT_DATE NOT NULL,
    valid_until date,
    source character varying(50),
    recorded_by integer,
    notes text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE public.competitor_prices_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.competitor_prices_id_seq OWNED BY public.competitor_prices.id;

CREATE TABLE public.crm_opportunities (
    id bigint NOT NULL,
    tenant_id integer DEFAULT 1 NOT NULL,
    name text NOT NULL,
    zone text NOT NULL,
    stage text NOT NULL,
    expected_revenue numeric DEFAULT 0 NOT NULL,
    distributor_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE public.crm_opportunities_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.crm_opportunities_id_seq OWNED BY public.crm_opportunities.id;

CREATE TABLE public.customer_purchases (
    id bigint NOT NULL,
    tenant_id integer DEFAULT 1 NOT NULL,
    customer_id integer NOT NULL,
    store_id integer NOT NULL,
    item_id integer NOT NULL,
    purchase_date date NOT NULL,
    qty numeric(10,3) DEFAULT 1 NOT NULL,
    amount_aed numeric(12,2) NOT NULL,
    was_promo boolean DEFAULT false NOT NULL,
    is_return boolean DEFAULT false NOT NULL,
    is_synthetic boolean DEFAULT true NOT NULL
);

CREATE SEQUENCE public.customer_purchases_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.customer_purchases_id_seq OWNED BY public.customer_purchases.id;

CREATE TABLE public.customers (
    id integer NOT NULL,
    tenant_id integer DEFAULT 1 NOT NULL,
    customer_ref character varying(40) NOT NULL,
    home_store_id integer NOT NULL,
    archetype character varying(30) NOT NULL,
    consent_marketing boolean DEFAULT true NOT NULL,
    contact_cap_month integer DEFAULT 4 NOT NULL,
    contacts_this_month integer DEFAULT 0 NOT NULL,
    is_synthetic boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE public.customers IS 'Synthetic loyalty layer for the retention module. customer_ref is opaque (never PII); archetype is a behavioural label used for honest demo data, NEVER a decision feature on protected attributes.';

CREATE SEQUENCE public.customers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.customers_id_seq OWNED BY public.customers.id;

CREATE TABLE public.data_requests (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    kind text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    scope text,
    requested_by integer,
    requested_email text,
    reviewed_by integer,
    reason text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT data_requests_kind_check CHECK ((kind = ANY (ARRAY['export'::text, 'delete'::text]))),
    CONSTRAINT data_requests_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'approved'::text, 'completed'::text, 'rejected'::text, 'cancelled'::text])))
);

CREATE SEQUENCE public.data_requests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.data_requests_id_seq OWNED BY public.data_requests.id;

CREATE TABLE public.data_sources (
    id integer NOT NULL,
    name character varying(120) NOT NULL,
    type character varying(20) DEFAULT 'postgres'::character varying NOT NULL,
    connection_enc text,
    mapping jsonb DEFAULT '{}'::jsonb NOT NULL,
    is_active boolean DEFAULT false NOT NULL,
    status character varying(20) DEFAULT 'untested'::character varying NOT NULL,
    last_tested_at timestamp with time zone,
    last_error text,
    created_by integer,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    tenant_id integer DEFAULT 1 NOT NULL
);

ALTER TABLE ONLY public.data_sources FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.data_sources_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.data_sources_id_seq OWNED BY public.data_sources.id;

CREATE TABLE public.distributors (
    id bigint NOT NULL,
    tenant_id integer DEFAULT 1 NOT NULL,
    name text NOT NULL,
    zone text NOT NULL,
    contact text,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE public.distributors_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.distributors_id_seq OWNED BY public.distributors.id;

CREATE TABLE public.documents (
    id bigint NOT NULL,
    tenant_id integer DEFAULT 1 NOT NULL,
    title text NOT NULL,
    chunk_no integer DEFAULT 0 NOT NULL,
    content text NOT NULL,
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, content)) STORED,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    embedding public.vector(384),
    embedding_model text,
    embedded_at timestamp with time zone,
    visibility_roles text[],
    store_scope integer[],
    sensitivity text DEFAULT 'internal'::text NOT NULL,
    parent_ref text,
    corpus text DEFAULT 'docs'::text NOT NULL,
    lang text DEFAULT 'en'::text NOT NULL,
    content_hash text,
    acl_updated_at timestamp with time zone,
    CONSTRAINT documents_sensitivity_chk CHECK ((sensitivity = ANY (ARRAY['public'::text, 'internal'::text, 'restricted'::text])))
);

CREATE SEQUENCE public.documents_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.documents_id_seq OWNED BY public.documents.id;

CREATE TABLE public.einvoice_submissions (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    invoice_id integer NOT NULL,
    provider text NOT NULL,
    environment text NOT NULL,
    status text DEFAULT 'building'::text NOT NULL,
    ubl_xml text,
    invoice_hash text,
    previous_invoice_hash text,
    signature text,
    is_production_signed boolean DEFAULT false NOT NULL,
    clearance_ref text,
    cleared_at timestamp with time zone,
    rejection_reason text,
    poll_attempts integer DEFAULT 0 NOT NULL,
    response_payload jsonb,
    submitted_by text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT einvoice_submissions_cleared_has_proof CHECK (((status <> 'cleared'::text) OR ((clearance_ref IS NOT NULL) AND (invoice_hash IS NOT NULL)))),
    CONSTRAINT einvoice_submissions_environment_check CHECK ((environment = ANY (ARRAY['sandbox'::text, 'production'::text]))),
    CONSTRAINT einvoice_submissions_prod_sig_only_in_prod CHECK (((is_production_signed = false) OR (environment = 'production'::text))),
    CONSTRAINT einvoice_submissions_status_check CHECK ((status = ANY (ARRAY['building'::text, 'submitted'::text, 'cleared'::text, 'rejected'::text, 'error'::text])))
);

ALTER TABLE ONLY public.einvoice_submissions FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.einvoice_submissions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.einvoice_submissions_id_seq OWNED BY public.einvoice_submissions.id;

CREATE TABLE public.employee_attendance (
    id integer NOT NULL,
    employee_id integer NOT NULL,
    attendance_date date NOT NULL,
    check_in_time timestamp with time zone,
    check_out_time timestamp with time zone,
    status character varying(20) DEFAULT 'present'::character varying NOT NULL,
    shift character varying(20) DEFAULT 'morning'::character varying,
    hours_worked numeric(4,2),
    overtime_hours numeric(4,2) DEFAULT 0,
    notes text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE public.employee_attendance_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.employee_attendance_id_seq OWNED BY public.employee_attendance.id;

CREATE TABLE public.employee_certifications (
    id integer NOT NULL,
    employee_id integer NOT NULL,
    certification_name character varying(200) NOT NULL,
    issuing_authority character varying(200),
    issue_date date NOT NULL,
    expiry_date date,
    certificate_url character varying(500),
    status character varying(20) DEFAULT 'active'::character varying,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE public.employee_certifications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.employee_certifications_id_seq OWNED BY public.employee_certifications.id;

CREATE TABLE public.employee_performance (
    id integer NOT NULL,
    employee_id integer NOT NULL,
    period_type public.performance_period DEFAULT 'monthly'::public.performance_period NOT NULL,
    period_start date NOT NULL,
    period_end date NOT NULL,
    sales_target numeric(12,2) DEFAULT 0,
    sales_achieved numeric(12,2) DEFAULT 0,
    sales_achievement_pct numeric(5,2) GENERATED ALWAYS AS (
CASE
    WHEN (sales_target > (0)::numeric) THEN ((sales_achieved / sales_target) * (100)::numeric)
    ELSE (0)::numeric
END) STORED,
    transactions_count integer DEFAULT 0,
    returns_count integer DEFAULT 0,
    voids_count integer DEFAULT 0,
    avg_transaction_value numeric(10,2) DEFAULT 0,
    items_sold integer DEFAULT 0,
    customers_served integer DEFAULT 0,
    customer_rating numeric(3,2) DEFAULT 0,
    complaints_received integer DEFAULT 0,
    compliments_received integer DEFAULT 0,
    days_present integer DEFAULT 0,
    days_absent integer DEFAULT 0,
    days_late integer DEFAULT 0,
    overtime_hours numeric(6,2) DEFAULT 0,
    attendance_percentage numeric(5,2) DEFAULT 100,
    performance_score numeric(5,2) DEFAULT 0,
    performance_grade character varying(2),
    manager_comments text,
    reviewed_by integer,
    reviewed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE public.employee_performance_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.employee_performance_id_seq OWNED BY public.employee_performance.id;

CREATE TABLE public.employee_transactions (
    id integer NOT NULL,
    transaction_code character varying(50) NOT NULL,
    employee_id integer NOT NULL,
    transaction_type public.transaction_type DEFAULT 'sale'::public.transaction_type NOT NULL,
    transaction_date date NOT NULL,
    transaction_time time without time zone NOT NULL,
    gross_amount numeric(12,2) NOT NULL,
    discount_amount numeric(10,2) DEFAULT 0,
    net_amount numeric(12,2) NOT NULL,
    items_count integer DEFAULT 1,
    store_id integer NOT NULL,
    register_id character varying(20),
    customer_id character varying(50),
    payment_method character varying(20),
    is_completed boolean DEFAULT true,
    is_voided boolean DEFAULT false,
    void_reason text,
    voided_by integer,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.employees (
    id integer NOT NULL,
    employee_code character varying(20) NOT NULL,
    first_name character varying(100) NOT NULL,
    last_name character varying(100) NOT NULL,
    email character varying(255) NOT NULL,
    phone character varying(20),
    date_of_birth date,
    gender character varying(10),
    nationality character varying(50),
    date_of_joining date NOT NULL,
    date_of_resignation date,
    date_of_termination date,
    role character varying(50) DEFAULT 'sales_executive'::character varying NOT NULL,
    department public.employee_department DEFAULT 'sales'::public.employee_department NOT NULL,
    designation character varying(100),
    store_id integer,
    region_id integer,
    reports_to integer,
    status public.employee_status DEFAULT 'active'::public.employee_status NOT NULL,
    photo_url character varying(500),
    emergency_contact_name character varying(100),
    emergency_contact_phone character varying(20),
    address text,
    salary_grade character varying(10),
    user_id integer,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.regions (
    id integer NOT NULL,
    code character varying(50) NOT NULL,
    name character varying(100) NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.stores (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    location character varying(100),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    region_id integer,
    square_footage integer DEFAULT 50000,
    opening_date date DEFAULT '2020-01-01'::date,
    tenant_id integer DEFAULT 1 NOT NULL,
    zone text,
    import_job_id integer
);

ALTER TABLE ONLY public.stores FORCE ROW LEVEL SECURITY;

CREATE VIEW public.employee_summary_view AS
 SELECT e.id,
    e.employee_code,
    (((e.first_name)::text || ' '::text) || (e.last_name)::text) AS full_name,
    e.email,
    e.role,
    (e.department)::text AS department,
    e.designation,
    (e.status)::text AS status,
    e.date_of_joining,
    e.date_of_resignation,
    s.name AS store_name,
    r.name AS region_name,
    COALESCE(( SELECT employee_performance.performance_score
           FROM public.employee_performance
          WHERE (employee_performance.employee_id = e.id)
          ORDER BY employee_performance.period_end DESC
         LIMIT 1), (0)::numeric) AS latest_performance_score,
    COALESCE(( SELECT employee_performance.performance_grade
           FROM public.employee_performance
          WHERE (employee_performance.employee_id = e.id)
          ORDER BY employee_performance.period_end DESC
         LIMIT 1), 'N/A'::character varying) AS latest_grade,
    COALESCE(( SELECT sum(employee_transactions.net_amount) AS sum
           FROM public.employee_transactions
          WHERE ((employee_transactions.employee_id = e.id) AND (employee_transactions.transaction_date >= (CURRENT_DATE - '30 days'::interval)))), (0)::numeric) AS sales_last_30_days,
    COALESCE(( SELECT count(*) AS count
           FROM public.employee_transactions
          WHERE ((employee_transactions.employee_id = e.id) AND (employee_transactions.transaction_date >= (CURRENT_DATE - '30 days'::interval)))), (0)::bigint) AS transactions_last_30_days
   FROM ((public.employees e
     LEFT JOIN public.stores s ON ((e.store_id = s.id)))
     LEFT JOIN public.regions r ON ((e.region_id = r.id)));

CREATE SEQUENCE public.employee_transactions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.employee_transactions_id_seq OWNED BY public.employee_transactions.id;

CREATE SEQUENCE public.employees_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.employees_id_seq OWNED BY public.employees.id;

CREATE TABLE public.external_identities (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    user_id integer NOT NULL,
    provider_id integer NOT NULL,
    issuer text NOT NULL,
    subject text NOT NULL,
    email text NOT NULL,
    email_verified boolean DEFAULT false NOT NULL,
    last_login_at timestamp with time zone,
    claims jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE public.external_identities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.external_identities_id_seq OWNED BY public.external_identities.id;

CREATE TABLE public.external_sales (
    tenant_id integer NOT NULL,
    source_name text NOT NULL,
    store_id integer NOT NULL,
    item_id integer NOT NULL,
    sale_date date NOT NULL,
    units numeric(14,2) DEFAULT 0 NOT NULL,
    revenue_aed numeric(16,2),
    txn_count integer DEFAULT 1 NOT NULL,
    ingested_at timestamp with time zone DEFAULT now() NOT NULL
)
PARTITION BY RANGE (sale_date);

CREATE TABLE public.findings (
    id bigint NOT NULL,
    tenant_id integer DEFAULT 1 NOT NULL,
    rule text NOT NULL,
    category text DEFAULT 'general'::text NOT NULL,
    severity text DEFAULT 'medium'::text NOT NULL,
    title text NOT NULL,
    detail text NOT NULL,
    evidence jsonb DEFAULT '{}'::jsonb NOT NULL,
    entity_type text,
    entity_id text,
    entity_name text,
    metric_value numeric,
    status text DEFAULT 'open'::text NOT NULL,
    dedupe_key text NOT NULL,
    detected_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    resolved_at timestamp with time zone,
    resolved_by text,
    recommended_action text,
    action_type text DEFAULT 'investigate'::text NOT NULL,
    action_accepted_at timestamp with time zone,
    action_accepted_by text,
    outcome_status text DEFAULT 'pending'::text NOT NULL,
    metric_before numeric,
    metric_after numeric,
    measured_at timestamp with time zone,
    CONSTRAINT findings_outcome_status_check CHECK ((outcome_status = ANY (ARRAY['pending'::text, 'improved'::text, 'unchanged'::text, 'worsened'::text]))),
    CONSTRAINT findings_severity_check CHECK ((severity = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text, 'critical'::text]))),
    CONSTRAINT findings_status_check CHECK ((status = ANY (ARRAY['open'::text, 'acknowledged'::text, 'resolved'::text])))
);

CREATE SEQUENCE public.findings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.findings_id_seq OWNED BY public.findings.id;

CREATE TABLE public.flywheel_allocation_lines (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    run_id bigint NOT NULL,
    customer_id integer NOT NULL,
    action_type character varying(30) NOT NULL,
    item_id integer,
    store_id integer,
    discount_pct numeric(5,2) DEFAULT 0 NOT NULL,
    units integer DEFAULT 1 NOT NULL,
    eiv_aed numeric(16,2) DEFAULT 0 NOT NULL,
    cost_aed numeric(16,2) DEFAULT 0 NOT NULL,
    eiv_density numeric(12,4),
    selected boolean DEFAULT false NOT NULL,
    reason_code character varying(40),
    displaced_by_line bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_allocation_lines_units_check CHECK ((units >= 0))
);

ALTER TABLE ONLY public.flywheel_allocation_lines FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_allocation_lines_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_allocation_lines_id_seq OWNED BY public.flywheel_allocation_lines.id;

CREATE TABLE public.flywheel_allocation_runs (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    campaign_id integer NOT NULL,
    mode character varying(20) NOT NULL,
    is_shadow boolean DEFAULT true NOT NULL,
    budget_limit_aed numeric(16,2) DEFAULT 0 NOT NULL,
    candidates_considered integer DEFAULT 0 NOT NULL,
    customers_considered integer DEFAULT 0 NOT NULL,
    actions_selected integer DEFAULT 0 NOT NULL,
    total_eiv_aed numeric(16,2) DEFAULT 0 NOT NULL,
    total_cost_aed numeric(16,2) DEFAULT 0 NOT NULL,
    binding_constraint character varying(30),
    eiv_delta_vs_greedy_aed numeric(16,2),
    input_digest character varying(64),
    solver character varying(30) DEFAULT 'density_greedy'::character varying NOT NULL,
    runtime_ms integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_allocation_runs_binding_constraint_check CHECK (((binding_constraint)::text = ANY ((ARRAY['budget'::character varying, 'stock'::character varying, 'contact_cap'::character varying, 'none'::character varying])::text[]))),
    CONSTRAINT flywheel_allocation_runs_mode_check CHECK (((mode)::text = ANY ((ARRAY['greedy'::character varying, 'portfolio'::character varying])::text[]))),
    CONSTRAINT flywheel_allocation_runs_solver_check CHECK (((solver)::text = ANY ((ARRAY['density_greedy'::character varying, 'lp_relaxation'::character varying, 'min_cost_flow'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_allocation_runs FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_allocation_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_allocation_runs_id_seq OWNED BY public.flywheel_allocation_runs.id;

CREATE TABLE public.flywheel_approval_policies (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    name character varying(120) NOT NULL,
    applies_to character varying(30) DEFAULT 'campaign'::character varying NOT NULL,
    min_discount_aed numeric(14,2) DEFAULT 0 NOT NULL,
    min_procurement_aed numeric(14,2) DEFAULT 0 NOT NULL,
    min_store_count integer DEFAULT 0 NOT NULL,
    required_role character varying(40) NOT NULL,
    required_permission character varying(60),
    step_order integer DEFAULT 1 NOT NULL,
    step_label character varying(60) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_approval_policies_applies_to_check CHECK (((applies_to)::text = ANY ((ARRAY['campaign'::character varying, 'requisition'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_approval_policies FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_approval_policies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_approval_policies_id_seq OWNED BY public.flywheel_approval_policies.id;

CREATE TABLE public.flywheel_approval_requests (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    campaign_id integer,
    requisition_id integer,
    request_type character varying(30) NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    discount_exposure_aed numeric(14,2) DEFAULT 0 NOT NULL,
    procurement_exposure_aed numeric(14,2) DEFAULT 0 NOT NULL,
    expected_roi numeric(10,4),
    summary jsonb DEFAULT '{}'::jsonb NOT NULL,
    requested_by integer,
    expires_at timestamp with time zone,
    resolved_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_approval_one_subject CHECK (((((campaign_id IS NOT NULL))::integer + ((requisition_id IS NOT NULL))::integer) = 1)),
    CONSTRAINT flywheel_approval_requests_request_type_check CHECK (((request_type)::text = ANY ((ARRAY['campaign_launch'::character varying, 'procurement_requisition'::character varying, 'budget_increase'::character varying, 'policy_exception'::character varying])::text[]))),
    CONSTRAINT flywheel_approval_requests_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying, 'changes_requested'::character varying, 'cancelled'::character varying, 'expired'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_approval_requests FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_approval_requests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_approval_requests_id_seq OWNED BY public.flywheel_approval_requests.id;

CREATE TABLE public.flywheel_approval_steps (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    request_id integer NOT NULL,
    policy_id integer,
    step_order integer NOT NULL,
    step_label character varying(60) NOT NULL,
    required_role character varying(40) NOT NULL,
    required_permission character varying(60),
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    decided_by integer,
    decided_at timestamp with time zone,
    comment text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_approval_steps_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying, 'changes_requested'::character varying, 'skipped'::character varying])::text[]))),
    CONSTRAINT flywheel_step_decided_has_actor CHECK ((((status)::text = ANY ((ARRAY['pending'::character varying, 'skipped'::character varying])::text[])) OR ((decided_by IS NOT NULL) AND (decided_at IS NOT NULL))))
);

ALTER TABLE ONLY public.flywheel_approval_steps FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_approval_steps_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_approval_steps_id_seq OWNED BY public.flywheel_approval_steps.id;

CREATE TABLE public.flywheel_budget_ledger (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    budget_id integer NOT NULL,
    campaign_id integer,
    entry_type character varying(20) NOT NULL,
    amount_aed numeric(16,2) NOT NULL,
    currency character varying(8) DEFAULT 'AED'::character varying NOT NULL,
    source_type character varying(40) NOT NULL,
    source_id character varying(64),
    balance_before numeric(16,2) NOT NULL,
    balance_after numeric(16,2) NOT NULL,
    actor_user_id integer,
    request_id character varying(64),
    idempotency_key character varying(120),
    reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_budget_ledger_amount_aed_check CHECK ((amount_aed >= (0)::numeric)),
    CONSTRAINT flywheel_budget_ledger_entry_type_check CHECK (((entry_type)::text = ANY ((ARRAY['ALLOCATED'::character varying, 'RESERVED'::character varying, 'COMMITTED'::character varying, 'SPENT'::character varying, 'RELEASED'::character varying, 'CLAWED_BACK'::character varying, 'BREAKAGE'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_budget_ledger FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_budget_ledger_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_budget_ledger_id_seq OWNED BY public.flywheel_budget_ledger.id;

CREATE TABLE public.flywheel_budgets (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    budget_type character varying(25) NOT NULL,
    period_start date NOT NULL,
    period_end date NOT NULL,
    currency character varying(8) DEFAULT 'AED'::character varying NOT NULL,
    allocated_aed numeric(16,2) DEFAULT 0 NOT NULL,
    reserved_aed numeric(16,2) DEFAULT 0 NOT NULL,
    committed_aed numeric(16,2) DEFAULT 0 NOT NULL,
    spent_aed numeric(16,2) DEFAULT 0 NOT NULL,
    released_aed numeric(16,2) DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    clawed_back_aed numeric(16,2) DEFAULT 0 NOT NULL,
    breakage_aed numeric(16,2) DEFAULT 0 NOT NULL,
    CONSTRAINT flywheel_budget_period_ordered CHECK ((period_end > period_start)),
    CONSTRAINT flywheel_budget_within_allocation CHECK (((reserved_aed + spent_aed) <= allocated_aed)),
    CONSTRAINT flywheel_budgets_allocated_aed_check CHECK ((allocated_aed >= (0)::numeric)),
    CONSTRAINT flywheel_budgets_breakage_aed_check CHECK ((breakage_aed >= (0)::numeric)),
    CONSTRAINT flywheel_budgets_budget_type_check CHECK (((budget_type)::text = ANY ((ARRAY['DISCOUNT'::character varying, 'MARKETING_MEDIA'::character varying, 'LOYALTY_REWARD'::character varying, 'PROCUREMENT'::character varying, 'LOGISTICS'::character varying, 'CONTINGENCY'::character varying])::text[]))),
    CONSTRAINT flywheel_budgets_clawed_back_aed_check CHECK ((clawed_back_aed >= (0)::numeric)),
    CONSTRAINT flywheel_budgets_committed_aed_check CHECK ((committed_aed >= (0)::numeric)),
    CONSTRAINT flywheel_budgets_released_aed_check CHECK ((released_aed >= (0)::numeric)),
    CONSTRAINT flywheel_budgets_reserved_aed_check CHECK ((reserved_aed >= (0)::numeric)),
    CONSTRAINT flywheel_budgets_spent_aed_check CHECK ((spent_aed >= (0)::numeric))
);

ALTER TABLE ONLY public.flywheel_budgets FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_budgets_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_budgets_id_seq OWNED BY public.flywheel_budgets.id;

CREATE TABLE public.flywheel_campaign_audience (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    campaign_id integer NOT NULL,
    customer_id integer NOT NULL,
    assignment character varying(10) NOT NULL,
    assignment_hash bigint NOT NULL,
    churn_probability numeric(6,5),
    eligibility_note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_campaign_audience_assignment_check CHECK (((assignment)::text = ANY ((ARRAY['treatment'::character varying, 'control'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_campaign_audience FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_campaign_audience_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_campaign_audience_id_seq OWNED BY public.flywheel_campaign_audience.id;

CREATE TABLE public.flywheel_campaign_outcomes (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    campaign_id integer NOT NULL,
    measured_at timestamp with time zone DEFAULT now() NOT NULL,
    treatment_size integer DEFAULT 0 NOT NULL,
    control_size integer DEFAULT 0 NOT NULL,
    treatment_retained integer DEFAULT 0 NOT NULL,
    control_retained integer DEFAULT 0 NOT NULL,
    treatment_retention_rate numeric(6,5) DEFAULT 0 NOT NULL,
    control_retention_rate numeric(6,5) DEFAULT 0 NOT NULL,
    incremental_retention numeric(7,5) DEFAULT 0 NOT NULL,
    incremental_revenue_aed numeric(16,2) DEFAULT 0 NOT NULL,
    incremental_margin_aed numeric(16,2) DEFAULT 0 NOT NULL,
    discount_spend_aed numeric(16,2) DEFAULT 0 NOT NULL,
    procurement_cost_aed numeric(16,2) DEFAULT 0 NOT NULL,
    cost_per_retained_aed numeric(14,2),
    campaign_roi numeric(10,4),
    uplift_by_segment jsonb DEFAULT '{}'::jsonb NOT NULL,
    budget_variance_aed numeric(16,2) DEFAULT 0 NOT NULL,
    stockout_rate numeric(6,5) DEFAULT 0 NOT NULL,
    notes text,
    breakage_aed numeric(16,2) DEFAULT 0 NOT NULL,
    breakage_rate numeric(6,5) DEFAULT 0 NOT NULL,
    clawed_back_aed numeric(16,2) DEFAULT 0 NOT NULL,
    returned_units integer DEFAULT 0 NOT NULL
);

ALTER TABLE ONLY public.flywheel_campaign_outcomes FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_campaign_outcomes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_campaign_outcomes_id_seq OWNED BY public.flywheel_campaign_outcomes.id;

CREATE TABLE public.flywheel_campaign_transitions (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    campaign_id integer NOT NULL,
    from_status character varying(30),
    to_status character varying(30) NOT NULL,
    actor_user_id integer,
    actor_kind character varying(20) DEFAULT 'user'::character varying NOT NULL,
    reason text,
    request_id character varying(64),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_campaign_transitions_actor_kind_check CHECK (((actor_kind)::text = ANY ((ARRAY['user'::character varying, 'system'::character varying, 'guardrail'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_campaign_transitions FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_campaign_transitions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_campaign_transitions_id_seq OWNED BY public.flywheel_campaign_transitions.id;

CREATE TABLE public.flywheel_campaigns (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    name character varying(200) NOT NULL,
    objective character varying(40) NOT NULL,
    status character varying(30) DEFAULT 'DRAFT'::character varying NOT NULL,
    starts_on date NOT NULL,
    ends_on date NOT NULL,
    channel character varying(20) DEFAULT 'email'::character varying NOT NULL,
    max_discount_pct numeric(5,2) DEFAULT 20 NOT NULL,
    min_margin_pct numeric(5,2) DEFAULT 10 NOT NULL,
    discount_budget_aed numeric(14,2) DEFAULT 0 NOT NULL,
    procurement_budget_aed numeric(14,2) DEFAULT 0 NOT NULL,
    safety_stock_pct numeric(5,2) DEFAULT 10 NOT NULL,
    control_group_pct numeric(5,2) DEFAULT 20 NOT NULL,
    contact_cap_per_week integer DEFAULT 2 NOT NULL,
    audience_spec jsonb DEFAULT '{}'::jsonb NOT NULL,
    policy_version character varying(20) DEFAULT 'v1'::character varying NOT NULL,
    pause_reason text,
    paused_at timestamp with time zone,
    created_by integer,
    activated_at timestamp with time zone,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    priority integer DEFAULT 100 NOT NULL,
    is_exclusive boolean DEFAULT false NOT NULL,
    CONSTRAINT flywheel_campaign_active_has_timestamp CHECK ((((status)::text <> ALL ((ARRAY['ACTIVE'::character varying, 'COMPLETED'::character varying, 'MEASURED'::character varying])::text[])) OR (activated_at IS NOT NULL))),
    CONSTRAINT flywheel_campaign_dates_ordered CHECK ((ends_on >= starts_on)),
    CONSTRAINT flywheel_campaign_paused_has_reason CHECK ((((status)::text <> 'PAUSED'::text) OR (pause_reason IS NOT NULL))),
    CONSTRAINT flywheel_campaigns_channel_check CHECK (((channel)::text = ANY ((ARRAY['email'::character varying, 'sms'::character varying, 'push'::character varying, 'in_store'::character varying, 'app'::character varying])::text[]))),
    CONSTRAINT flywheel_campaigns_contact_cap_per_week_check CHECK ((contact_cap_per_week >= 0)),
    CONSTRAINT flywheel_campaigns_control_group_pct_check CHECK (((control_group_pct >= (0)::numeric) AND (control_group_pct <= (50)::numeric))),
    CONSTRAINT flywheel_campaigns_discount_budget_aed_check CHECK ((discount_budget_aed >= (0)::numeric)),
    CONSTRAINT flywheel_campaigns_max_discount_pct_check CHECK (((max_discount_pct >= (0)::numeric) AND (max_discount_pct <= (90)::numeric))),
    CONSTRAINT flywheel_campaigns_min_margin_pct_check CHECK (((min_margin_pct >= (0)::numeric) AND (min_margin_pct <= (100)::numeric))),
    CONSTRAINT flywheel_campaigns_objective_check CHECK (((objective)::text = ANY ((ARRAY['retain_at_risk'::character varying, 'reactivate_lapsed'::character varying, 'grow_basket'::character varying, 'protect_margin'::character varying])::text[]))),
    CONSTRAINT flywheel_campaigns_procurement_budget_aed_check CHECK ((procurement_budget_aed >= (0)::numeric)),
    CONSTRAINT flywheel_campaigns_safety_stock_pct_check CHECK (((safety_stock_pct >= (0)::numeric) AND (safety_stock_pct <= (100)::numeric))),
    CONSTRAINT flywheel_campaigns_status_check CHECK (((status)::text = ANY ((ARRAY['DRAFT'::character varying, 'AUDIENCE_READY'::character varying, 'SIMULATED'::character varying, 'PENDING_INVENTORY_REVIEW'::character varying, 'PENDING_PROCUREMENT_REVIEW'::character varying, 'PENDING_FINANCE_APPROVAL'::character varying, 'PENDING_MARKETING_APPROVAL'::character varying, 'APPROVED'::character varying, 'SCHEDULED'::character varying, 'ACTIVE'::character varying, 'PAUSED'::character varying, 'COMPLETED'::character varying, 'CANCELLED'::character varying, 'MEASURED'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_campaigns FORCE ROW LEVEL SECURITY;

COMMENT ON COLUMN public.flywheel_campaigns.priority IS 'Lower wins. Ties break on higher EIV, then lower campaign id, so the resolution is total and reproducible rather than dependent on row order.';

CREATE SEQUENCE public.flywheel_campaigns_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_campaigns_id_seq OWNED BY public.flywheel_campaigns.id;

CREATE TABLE public.flywheel_cannibalization (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    campaign_id integer NOT NULL,
    category character varying(80) NOT NULL,
    promoted_item_id integer,
    method character varying(20) DEFAULT 'did'::character varying NOT NULL,
    window_start date NOT NULL,
    window_end date NOT NULL,
    promoted_lift_units integer DEFAULT 0 NOT NULL,
    category_net_lift_units integer DEFAULT 0 NOT NULL,
    cannibalized_units integer DEFAULT 0 NOT NULL,
    cannibalization_rate numeric(6,4),
    net_incremental_margin_aed numeric(16,2) DEFAULT 0 NOT NULL,
    is_reliable boolean DEFAULT false NOT NULL,
    note text,
    computed_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_cannibalization_method_check CHECK (((method)::text = ANY ((ARRAY['did'::character varying, 'naive'::character varying, 'bayesian'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_cannibalization FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_cannibalization_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_cannibalization_id_seq OWNED BY public.flywheel_cannibalization.id;

CREATE TABLE public.flywheel_churn_predictions (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    customer_id integer NOT NULL,
    model_version_id integer NOT NULL,
    as_of_date date NOT NULL,
    churn_probability numeric(6,5) NOT NULL,
    risk_band character varying(10) NOT NULL,
    reason_codes jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_churn_predictions_churn_probability_check CHECK (((churn_probability >= (0)::numeric) AND (churn_probability <= (1)::numeric))),
    CONSTRAINT flywheel_churn_predictions_risk_band_check CHECK (((risk_band)::text = ANY ((ARRAY['low'::character varying, 'medium'::character varying, 'high'::character varying, 'critical'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_churn_predictions FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_churn_predictions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_churn_predictions_id_seq OWNED BY public.flywheel_churn_predictions.id;

CREATE TABLE public.flywheel_coalition_activity (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    customer_id integer NOT NULL,
    partner_id bigint NOT NULL,
    activity_type character varying(20) NOT NULL,
    points integer DEFAULT 0 NOT NULL,
    value_aed numeric(16,2) DEFAULT 0 NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_coalition_activity_activity_type_check CHECK (((activity_type)::text = ANY ((ARRAY['earn'::character varying, 'redeem'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_coalition_activity FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_coalition_activity_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_coalition_activity_id_seq OWNED BY public.flywheel_coalition_activity.id;

CREATE TABLE public.flywheel_coalition_attribution (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    campaign_id integer NOT NULL,
    customer_id integer NOT NULL,
    partner_id bigint NOT NULL,
    attribution_weight numeric(6,5) DEFAULT 0 NOT NULL,
    attributed_margin_aed numeric(16,2) DEFAULT 0 NOT NULL,
    model character varying(30) DEFAULT 'linear'::character varying NOT NULL,
    computed_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_coalition_attribution_attribution_weight_check CHECK (((attribution_weight >= (0)::numeric) AND (attribution_weight <= (1)::numeric))),
    CONSTRAINT flywheel_coalition_attribution_model_check CHECK (((model)::text = ANY ((ARRAY['linear'::character varying, 'time_decay'::character varying, 'position'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_coalition_attribution FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_coalition_attribution_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_coalition_attribution_id_seq OWNED BY public.flywheel_coalition_attribution.id;

CREATE TABLE public.flywheel_coalition_partners (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    partner_name character varying(120) NOT NULL,
    partner_type character varying(30) NOT NULL,
    external_ref character varying(80),
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_coalition_partners_partner_type_check CHECK (((partner_type)::text = ANY ((ARRAY['grocery'::character varying, 'fuel'::character varying, 'hospitality'::character varying, 'travel'::character varying, 'retail'::character varying, 'dining'::character varying, 'other'::character varying])::text[]))),
    CONSTRAINT flywheel_coalition_partners_status_check CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'inactive'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_coalition_partners FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_coalition_partners_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_coalition_partners_id_seq OWNED BY public.flywheel_coalition_partners.id;

CREATE TABLE public.flywheel_contact_log (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    customer_id integer NOT NULL,
    campaign_id integer,
    channel character varying(20) NOT NULL,
    contacted_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.flywheel_contact_log FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_contact_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_contact_log_id_seq OWNED BY public.flywheel_contact_log.id;

CREATE TABLE public.flywheel_contact_policy (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    channel character varying(20),
    max_contacts_per_week integer DEFAULT 3 NOT NULL,
    max_contacts_per_day integer DEFAULT 1 NOT NULL,
    cooldown_days_after_ignores integer DEFAULT 14 NOT NULL,
    ignores_before_cooldown integer DEFAULT 3 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_contact_policy_max_contacts_per_day_check CHECK ((max_contacts_per_day >= 0)),
    CONSTRAINT flywheel_contact_policy_max_contacts_per_week_check CHECK ((max_contacts_per_week >= 0))
);

ALTER TABLE ONLY public.flywheel_contact_policy FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_contact_policy_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_contact_policy_id_seq OWNED BY public.flywheel_contact_policy.id;

CREATE TABLE public.flywheel_customer_consents (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    customer_id integer NOT NULL,
    channel character varying(20) NOT NULL,
    granted boolean DEFAULT true NOT NULL,
    max_contacts_per_week integer DEFAULT 3 NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_customer_consents_channel_check CHECK (((channel)::text = ANY ((ARRAY['email'::character varying, 'sms'::character varying, 'push'::character varying, 'in_store'::character varying, 'app'::character varying])::text[]))),
    CONSTRAINT flywheel_customer_consents_max_contacts_per_week_check CHECK ((max_contacts_per_week >= 0))
);

ALTER TABLE ONLY public.flywheel_customer_consents FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_customer_consents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_customer_consents_id_seq OWNED BY public.flywheel_customer_consents.id;

CREATE TABLE public.flywheel_customer_events (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    customer_id integer NOT NULL,
    event_type character varying(30) NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    store_id integer,
    item_id integer,
    category character varying(50),
    quantity_units integer DEFAULT 0 NOT NULL,
    value_aed numeric(14,2) DEFAULT 0 NOT NULL,
    margin_aed numeric(14,2) DEFAULT 0 NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_customer_events_event_type_check CHECK (((event_type)::text = ANY ((ARRAY['purchase'::character varying, 'return'::character varying, 'visit'::character varying, 'offer_seen'::character varying, 'offer_redeemed'::character varying, 'offer_ignored'::character varying, 'complaint'::character varying, 'support_contact'::character varying])::text[]))),
    CONSTRAINT flywheel_customer_events_value_aed_check CHECK ((value_aed >= (0)::numeric))
);

ALTER TABLE ONLY public.flywheel_customer_events FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_customer_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_customer_events_id_seq OWNED BY public.flywheel_customer_events.id;

CREATE TABLE public.flywheel_customers (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    external_ref character varying(64) NOT NULL,
    display_name character varying(120) NOT NULL,
    home_store_id integer NOT NULL,
    archetype character varying(40) NOT NULL,
    enrolled_on date NOT NULL,
    loyalty_tier character varying(20) DEFAULT 'standard'::character varying NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    is_synthetic boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_customers_loyalty_tier_check CHECK (((loyalty_tier)::text = ANY ((ARRAY['standard'::character varying, 'silver'::character varying, 'gold'::character varying, 'platinum'::character varying])::text[]))),
    CONSTRAINT flywheel_customers_status_check CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'dormant'::character varying, 'churned'::character varying, 'opted_out'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_customers FORCE ROW LEVEL SECURITY;

COMMENT ON TABLE public.flywheel_customers IS 'Synthetic customer identity layer for Flywheel retention. Fixed-seed generated; never contains real personal data and never stores sensitive attributes.';

CREATE SEQUENCE public.flywheel_customers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_customers_id_seq OWNED BY public.flywheel_customers.id;

CREATE TABLE public.flywheel_decisions (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    campaign_id integer,
    customer_id integer NOT NULL,
    store_id integer,
    item_id integer,
    category character varying(50),
    action_type character varying(30) NOT NULL,
    churn_probability numeric(6,5) DEFAULT 0 NOT NULL,
    uplift numeric(7,5) DEFAULT 0 NOT NULL,
    redemption_probability numeric(6,5) DEFAULT 0 NOT NULL,
    unit_price_aed numeric(12,4) DEFAULT 0 NOT NULL,
    unit_cost_aed numeric(12,4) DEFAULT 0 NOT NULL,
    discount_pct numeric(5,2) DEFAULT 0 NOT NULL,
    expected_retained_value_aed numeric(14,4) DEFAULT 0 NOT NULL,
    expected_margin_aed numeric(14,4) DEFAULT 0 NOT NULL,
    expected_discount_cost_aed numeric(14,4) DEFAULT 0 NOT NULL,
    comms_cost_aed numeric(14,4) DEFAULT 0 NOT NULL,
    fulfilment_cost_aed numeric(14,4) DEFAULT 0 NOT NULL,
    procurement_cost_aed numeric(14,4) DEFAULT 0 NOT NULL,
    stockout_risk_penalty_aed numeric(14,4) DEFAULT 0 NOT NULL,
    eiv_aed numeric(14,4) DEFAULT 0 NOT NULL,
    reason_codes jsonb DEFAULT '[]'::jsonb NOT NULL,
    rejected_actions jsonb DEFAULT '[]'::jsonb NOT NULL,
    inventory_snapshot jsonb DEFAULT '{}'::jsonb NOT NULL,
    budget_snapshot jsonb DEFAULT '{}'::jsonb NOT NULL,
    churn_model_version_id integer,
    uplift_model_version_id integer,
    policy_version character varying(20) DEFAULT 'v1'::character varying NOT NULL,
    request_id character varying(64),
    decided_at timestamp with time zone DEFAULT now() NOT NULL,
    tax_rate_pct numeric(6,3) DEFAULT 0 NOT NULL,
    net_price_aed numeric(12,4) DEFAULT 0 NOT NULL,
    margin_net_pct numeric(7,3),
    trace_id character varying(48),
    CONSTRAINT flywheel_decisions_action_type_check CHECK (((action_type)::text = ANY ((ARRAY['NO_ACTION'::character varying, 'REMINDER'::character varying, 'LOYALTY_POINTS'::character varying, 'FREE_DELIVERY'::character varying, 'PERCENT_DISCOUNT'::character varying, 'FIXED_DISCOUNT'::character varying, 'PRODUCT_BUNDLE'::character varying, 'SUBSTITUTE_PRODUCT'::character varying, 'ALTERNATIVE_STORE'::character varying, 'HUMAN_REVIEW'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_decisions FORCE ROW LEVEL SECURITY;

COMMENT ON TABLE public.flywheel_decisions IS 'Next-best-action ledger. Stores every optimizer input AND the rejected alternatives with reason codes, so any decision is reproducible and explainable.';

CREATE SEQUENCE public.flywheel_decisions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_decisions_id_seq OWNED BY public.flywheel_decisions.id;

CREATE TABLE public.flywheel_delivery_receipts (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    consumer character varying(60) NOT NULL,
    event_key character varying(160) NOT NULL,
    outcome character varying(20) DEFAULT 'processed'::character varying NOT NULL,
    detail text,
    processed_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_delivery_receipts_outcome_check CHECK (((outcome)::text = ANY ((ARRAY['processed'::character varying, 'skipped'::character varying, 'failed'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_delivery_receipts FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_delivery_receipts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_delivery_receipts_id_seq OWNED BY public.flywheel_delivery_receipts.id;

CREATE TABLE public.flywheel_feature_snapshots (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    customer_id integer NOT NULL,
    as_of_date date NOT NULL,
    recency_days integer NOT NULL,
    frequency_90d integer NOT NULL,
    monetary_90d_aed numeric(14,2) DEFAULT 0 NOT NULL,
    avg_basket_aed numeric(14,2) DEFAULT 0 NOT NULL,
    spend_drift_ratio numeric(8,4) DEFAULT 1 NOT NULL,
    interpurchase_gap_days numeric(8,2) DEFAULT 0 NOT NULL,
    gap_volatility numeric(8,4) DEFAULT 0 NOT NULL,
    category_diversity integer DEFAULT 0 NOT NULL,
    return_ratio numeric(6,4) DEFAULT 0 NOT NULL,
    promo_response_rate numeric(6,4) DEFAULT 0 NOT NULL,
    tenure_days integer DEFAULT 0 NOT NULL,
    events_90d integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.flywheel_feature_snapshots FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_feature_snapshots_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_feature_snapshots_id_seq OWNED BY public.flywheel_feature_snapshots.id;

CREATE TABLE public.flywheel_holdout_balance (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    campaign_id integer NOT NULL,
    checked_on date DEFAULT CURRENT_DATE NOT NULL,
    covariate character varying(60) NOT NULL,
    treatment_mean double precision NOT NULL,
    control_mean double precision NOT NULL,
    pooled_sd double precision NOT NULL,
    smd double precision NOT NULL,
    threshold double precision DEFAULT 0.10 NOT NULL,
    is_balanced boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.flywheel_holdout_balance FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_holdout_balance_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_holdout_balance_id_seq OWNED BY public.flywheel_holdout_balance.id;

CREATE TABLE public.flywheel_identity_links (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    pos_key character varying(120) NOT NULL,
    customer_id integer,
    confidence numeric(4,3) DEFAULT 0 NOT NULL,
    method character varying(20) NOT NULL,
    status character varying(20) DEFAULT 'linked'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_identity_links_method_check CHECK (((method)::text = ANY ((ARRAY['deterministic'::character varying, 'probabilistic'::character varying, 'ambiguous'::character varying, 'unlinked'::character varying])::text[]))),
    CONSTRAINT flywheel_identity_links_status_check CHECK (((status)::text = ANY ((ARRAY['linked'::character varying, 'ambiguous'::character varying, 'unlinked'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_identity_links FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_identity_links_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_identity_links_id_seq OWNED BY public.flywheel_identity_links.id;

CREATE TABLE public.flywheel_inventory_allocations (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    campaign_id integer NOT NULL,
    store_id integer NOT NULL,
    item_id integer NOT NULL,
    allocated_units integer NOT NULL,
    consumed_units integer DEFAULT 0 NOT NULL,
    status character varying(20) DEFAULT 'soft'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    released_at timestamp with time zone,
    CONSTRAINT flywheel_allocation_not_overconsumed CHECK ((consumed_units <= allocated_units)),
    CONSTRAINT flywheel_inventory_allocations_allocated_units_check CHECK ((allocated_units >= 0)),
    CONSTRAINT flywheel_inventory_allocations_consumed_units_check CHECK ((consumed_units >= 0)),
    CONSTRAINT flywheel_inventory_allocations_status_check CHECK (((status)::text = ANY ((ARRAY['soft'::character varying, 'hard'::character varying, 'released'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_inventory_allocations FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_inventory_allocations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_inventory_allocations_id_seq OWNED BY public.flywheel_inventory_allocations.id;

CREATE TABLE public.flywheel_jobs (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    kind character varying(40) NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    idempotency_key character varying(160),
    status character varying(20) DEFAULT 'queued'::character varying NOT NULL,
    claimed_by character varying(80),
    claimed_at timestamp with time zone,
    lease_expires_at timestamp with time zone,
    checkpoint jsonb DEFAULT '{}'::jsonb NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    max_attempts integer DEFAULT 5 NOT NULL,
    run_after timestamp with time zone DEFAULT now() NOT NULL,
    last_error text,
    result jsonb,
    trace_id character varying(48),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    CONSTRAINT flywheel_jobs_kind_check CHECK (((kind)::text = ANY ((ARRAY['score_audience'::character varying, 'measure_campaign'::character varying, 'measure_all'::character varying, 'issue_offers'::character varying, 'shadow_score'::character varying, 'refresh_readouts'::character varying, 'train_model'::character varying])::text[]))),
    CONSTRAINT flywheel_jobs_status_check CHECK (((status)::text = ANY ((ARRAY['queued'::character varying, 'running'::character varying, 'succeeded'::character varying, 'failed'::character varying, 'dead'::character varying, 'cancelled'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_jobs FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_jobs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_jobs_id_seq OWNED BY public.flywheel_jobs.id;

CREATE TABLE public.flywheel_model_versions (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    model_kind character varying(30) NOT NULL,
    algorithm character varying(60) NOT NULL,
    version_label character varying(40) NOT NULL,
    random_seed integer DEFAULT 42 NOT NULL,
    feature_window_days integer NOT NULL,
    outcome_window_days integer NOT NULL,
    feature_list jsonb DEFAULT '[]'::jsonb NOT NULL,
    metrics jsonb DEFAULT '{}'::jsonb NOT NULL,
    artifact_path text,
    trained_at timestamp with time zone,
    is_active boolean DEFAULT false NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    data_snapshot_hash character varying(64),
    data_snapshot_rows integer,
    data_snapshot_from date,
    data_snapshot_to date,
    lifecycle_status character varying(20) DEFAULT 'shadow'::character varying,
    superseded_by integer,
    rolled_back_to integer,
    promoted_at timestamp with time zone,
    promoted_by integer,
    promotion_note text,
    CONSTRAINT flywheel_model_trained_has_timestamp CHECK ((((algorithm)::text = 'rule_based'::text) OR (trained_at IS NOT NULL))),
    CONSTRAINT flywheel_model_versions_lifecycle_status_check CHECK (((lifecycle_status)::text = ANY ((ARRAY['shadow'::character varying, 'candidate'::character varying, 'promoted'::character varying, 'retired'::character varying, 'rolled_back'::character varying])::text[]))),
    CONSTRAINT flywheel_model_versions_model_kind_check CHECK (((model_kind)::text = ANY ((ARRAY['churn'::character varying, 'uplift'::character varying, 'sequence'::character varying, 'tabular_dl'::character varying, 'ensemble'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_model_versions FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_model_versions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_model_versions_id_seq OWNED BY public.flywheel_model_versions.id;

CREATE TABLE public.flywheel_offer_response_predictions (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    customer_id integer NOT NULL,
    model_version_id integer NOT NULL,
    action_type character varying(30) NOT NULL,
    as_of_date date NOT NULL,
    treated_response numeric(6,5) NOT NULL,
    control_response numeric(6,5) NOT NULL,
    uplift numeric(7,5) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_offer_response_predictions_control_response_check CHECK (((control_response >= (0)::numeric) AND (control_response <= (1)::numeric))),
    CONSTRAINT flywheel_offer_response_predictions_treated_response_check CHECK (((treated_response >= (0)::numeric) AND (treated_response <= (1)::numeric)))
);

ALTER TABLE ONLY public.flywheel_offer_response_predictions FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_offer_response_predictions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_offer_response_predictions_id_seq OWNED BY public.flywheel_offer_response_predictions.id;

CREATE TABLE public.flywheel_offer_suppressions (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    customer_id integer NOT NULL,
    suppressed_campaign_id integer NOT NULL,
    winning_campaign_id integer,
    reason_code character varying(40) NOT NULL,
    detail text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.flywheel_offer_suppressions FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_offer_suppressions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_offer_suppressions_id_seq OWNED BY public.flywheel_offer_suppressions.id;

CREATE TABLE public.flywheel_offers (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    campaign_id integer NOT NULL,
    customer_id integer NOT NULL,
    decision_id bigint,
    offer_code character varying(40) NOT NULL,
    action_type character varying(30) NOT NULL,
    store_id integer,
    item_id integer,
    discount_pct numeric(5,2) DEFAULT 0 NOT NULL,
    reserved_aed numeric(14,2) DEFAULT 0 NOT NULL,
    status character varying(20) DEFAULT 'issued'::character varying NOT NULL,
    issued_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    redeemed_at timestamp with time zone,
    liability_aed numeric(14,2) DEFAULT 0 NOT NULL,
    liability_released boolean DEFAULT false NOT NULL,
    breakage_aed numeric(14,2) DEFAULT 0 NOT NULL,
    CONSTRAINT flywheel_offer_breakage_requires_release CHECK (((breakage_aed = (0)::numeric) OR (liability_released = true))),
    CONSTRAINT flywheel_offer_redeemed_has_timestamp CHECK ((((status)::text <> 'redeemed'::text) OR (redeemed_at IS NOT NULL))),
    CONSTRAINT flywheel_offers_status_check CHECK (((status)::text = ANY ((ARRAY['issued'::character varying, 'redeemed'::character varying, 'expired'::character varying, 'cancelled'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_offers FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_offers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_offers_id_seq OWNED BY public.flywheel_offers.id;

CREATE TABLE public.flywheel_outbox (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    channel character varying(60) NOT NULL,
    event_type character varying(60) NOT NULL,
    payload jsonb NOT NULL,
    store_id integer,
    campaign_id integer,
    published boolean DEFAULT false NOT NULL,
    published_at timestamp with time zone,
    attempts integer DEFAULT 0 NOT NULL,
    last_error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    trace_id character varying(48),
    CONSTRAINT flywheel_outbox_published_has_timestamp CHECK (((published = false) OR (published_at IS NOT NULL)))
);

ALTER TABLE ONLY public.flywheel_outbox FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_outbox_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_outbox_id_seq OWNED BY public.flywheel_outbox.id;

CREATE TABLE public.flywheel_outcome_pricing (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    plan_name character varying(80) NOT NULL,
    margin_share_pct numeric(5,4) NOT NULL,
    gate_readouts_required integer DEFAULT 2 NOT NULL,
    gate_met boolean DEFAULT false NOT NULL,
    gate_evidence jsonb DEFAULT '{}'::jsonb NOT NULL,
    status character varying(20) DEFAULT 'proposed'::character varying NOT NULL,
    activated_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_outcome_pricing_gate_readouts_required_check CHECK ((gate_readouts_required >= 1)),
    CONSTRAINT flywheel_outcome_pricing_margin_share_pct_check CHECK (((margin_share_pct > (0)::numeric) AND (margin_share_pct <= 0.5))),
    CONSTRAINT flywheel_outcome_pricing_status_check CHECK (((status)::text = ANY ((ARRAY['proposed'::character varying, 'active'::character varying, 'inactive'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_outcome_pricing FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_outcome_pricing_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_outcome_pricing_id_seq OWNED BY public.flywheel_outcome_pricing.id;

CREATE TABLE public.flywheel_pos_staging (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    external_txn_id character varying(120) NOT NULL,
    loyalty_ref character varying(120),
    card_hash character varying(120),
    store_id integer,
    item_id integer,
    units integer DEFAULT 1 NOT NULL,
    amount_aed numeric(16,2) DEFAULT 0 NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    resolved boolean DEFAULT false NOT NULL,
    matched_customer_id integer,
    match_confidence numeric(4,3),
    match_method character varying(20),
    ingested_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_pos_staging_match_method_check CHECK (((match_method)::text = ANY ((ARRAY['deterministic'::character varying, 'probabilistic'::character varying, 'unlinked'::character varying, NULL::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_pos_staging FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_pos_staging_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_pos_staging_id_seq OWNED BY public.flywheel_pos_staging.id;

CREATE TABLE public.flywheel_preregistrations (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    campaign_id integer NOT NULL,
    primary_metric character varying(60) DEFAULT 'incremental_retention'::character varying NOT NULL,
    window_days integer NOT NULL,
    stopping_rule character varying(30) DEFAULT 'anytime'::character varying NOT NULL,
    alpha double precision DEFAULT 0.05 NOT NULL,
    min_detectable_effect double precision DEFAULT 0.02 NOT NULL,
    planned_treatment_n integer DEFAULT 0 NOT NULL,
    planned_control_n integer DEFAULT 0 NOT NULL,
    control_pct numeric(5,2) DEFAULT 10.00 NOT NULL,
    registered_by integer,
    registered_at timestamp with time zone DEFAULT now() NOT NULL,
    notes text,
    CONSTRAINT flywheel_preregistrations_alpha_check CHECK (((alpha > (0)::double precision) AND (alpha < (0.5)::double precision))),
    CONSTRAINT flywheel_preregistrations_control_pct_check CHECK (((control_pct >= (0)::numeric) AND (control_pct <= (50)::numeric))),
    CONSTRAINT flywheel_preregistrations_min_detectable_effect_check CHECK ((min_detectable_effect >= (0)::double precision)),
    CONSTRAINT flywheel_preregistrations_planned_control_n_check CHECK ((planned_control_n >= 0)),
    CONSTRAINT flywheel_preregistrations_planned_treatment_n_check CHECK ((planned_treatment_n >= 0)),
    CONSTRAINT flywheel_preregistrations_primary_metric_check CHECK (((primary_metric)::text = ANY ((ARRAY['incremental_retention'::character varying, 'incremental_margin_aed'::character varying, 'incremental_margin_per_aed'::character varying])::text[]))),
    CONSTRAINT flywheel_preregistrations_stopping_rule_check CHECK (((stopping_rule)::text = ANY ((ARRAY['anytime'::character varying, 'fixed_horizon'::character varying])::text[]))),
    CONSTRAINT flywheel_preregistrations_window_days_check CHECK (((window_days >= 1) AND (window_days <= 365)))
);

ALTER TABLE ONLY public.flywheel_preregistrations FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_preregistrations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_preregistrations_id_seq OWNED BY public.flywheel_preregistrations.id;

CREATE TABLE public.flywheel_procurement_requisitions (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    campaign_id integer NOT NULL,
    store_id integer NOT NULL,
    item_id integer NOT NULL,
    supplier_id integer,
    shortage_units integer NOT NULL,
    order_units integer NOT NULL,
    unit_cost_aed numeric(12,4) DEFAULT 0 NOT NULL,
    total_cost_aed numeric(14,2) DEFAULT 0 NOT NULL,
    lead_time_days integer DEFAULT 0 NOT NULL,
    required_by date NOT NULL,
    expected_arrival date,
    status character varying(25) DEFAULT 'draft'::character varying NOT NULL,
    justification jsonb DEFAULT '{}'::jsonb NOT NULL,
    purchase_order_id integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_procurement_requisitions_order_units_check CHECK ((order_units > 0)),
    CONSTRAINT flywheel_procurement_requisitions_shortage_units_check CHECK ((shortage_units > 0)),
    CONSTRAINT flywheel_procurement_requisitions_status_check CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'pending_approval'::character varying, 'approved'::character varying, 'rejected'::character varying, 'converted_to_po'::character varying, 'cancelled'::character varying])::text[]))),
    CONSTRAINT flywheel_req_converted_has_po CHECK ((((status)::text <> 'converted_to_po'::text) OR (purchase_order_id IS NOT NULL)))
);

ALTER TABLE ONLY public.flywheel_procurement_requisitions FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_procurement_requisitions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_procurement_requisitions_id_seq OWNED BY public.flywheel_procurement_requisitions.id;

CREATE TABLE public.flywheel_profiling_objections (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    customer_id integer NOT NULL,
    basis character varying(40) DEFAULT 'pdpl_art_automated_processing'::character varying NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    note text,
    objected_at timestamp with time zone DEFAULT now() NOT NULL,
    withdrawn_at timestamp with time zone,
    CONSTRAINT flywheel_profiling_objections_status_check CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'withdrawn'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_profiling_objections FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_profiling_objections_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_profiling_objections_id_seq OWNED BY public.flywheel_profiling_objections.id;

CREATE TABLE public.flywheel_promotion_criteria (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    model_label character varying(60) NOT NULL,
    min_readouts_required integer DEFAULT 2 NOT NULL,
    min_ci_lower double precision DEFAULT 0.0 NOT NULL,
    max_disagreement_rate double precision DEFAULT 0.35 NOT NULL,
    readouts_passed integer DEFAULT 0 NOT NULL,
    current_disagreement_rate double precision,
    eligible_for_promotion boolean DEFAULT false NOT NULL,
    blocked_reason text,
    status character varying(20) DEFAULT 'shadow'::character varying NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_promotion_criteria_min_readouts_required_check CHECK ((min_readouts_required >= 1)),
    CONSTRAINT flywheel_promotion_criteria_status_check CHECK (((status)::text = ANY ((ARRAY['shadow'::character varying, 'candidate'::character varying, 'promoted'::character varying, 'retired'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_promotion_criteria FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_promotion_criteria_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_promotion_criteria_id_seq OWNED BY public.flywheel_promotion_criteria.id;

CREATE TABLE public.flywheel_purchase_attributions (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    event_id bigint NOT NULL,
    sale_source character varying(20) NOT NULL,
    sale_id bigint NOT NULL,
    attributed_units integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_purchase_attributions_attributed_units_check CHECK ((attributed_units > 0)),
    CONSTRAINT flywheel_purchase_attributions_sale_source_check CHECK (((sale_source)::text = ANY ((ARRAY['historical'::character varying, 'stream'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_purchase_attributions FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_purchase_attributions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_purchase_attributions_id_seq OWNED BY public.flywheel_purchase_attributions.id;

CREATE TABLE public.flywheel_readouts (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    campaign_id integer NOT NULL,
    preregistration_id integer,
    window_start date NOT NULL,
    window_end date NOT NULL,
    treatment_n integer NOT NULL,
    control_n integer NOT NULL,
    treatment_converted integer NOT NULL,
    control_converted integer NOT NULL,
    treatment_rate double precision NOT NULL,
    control_rate double precision NOT NULL,
    incremental_retention double precision NOT NULL,
    ci_lower double precision,
    ci_upper double precision,
    ci_method character varying(40) DEFAULT 'eb_confseq'::character varying NOT NULL,
    alpha double precision DEFAULT 0.05 NOT NULL,
    log_e_value double precision,
    is_significant boolean DEFAULT false NOT NULL,
    meets_mde boolean DEFAULT false NOT NULL,
    incremental_revenue_aed numeric(16,2) DEFAULT 0 NOT NULL,
    incremental_margin_aed numeric(16,2) DEFAULT 0 NOT NULL,
    discount_spend_aed numeric(16,2) DEFAULT 0 NOT NULL,
    procurement_cost_aed numeric(16,2) DEFAULT 0 NOT NULL,
    total_cost_aed numeric(16,2) DEFAULT 0 NOT NULL,
    margin_per_aed_spent numeric(12,4),
    campaign_roi numeric(12,4),
    validity_warnings jsonb DEFAULT '[]'::jsonb NOT NULL,
    uplift_by_segment jsonb DEFAULT '{}'::jsonb NOT NULL,
    is_synthetic boolean DEFAULT true NOT NULL,
    computed_at timestamp with time zone DEFAULT now() NOT NULL,
    computed_by character varying(30) DEFAULT 'scheduler'::character varying NOT NULL,
    CONSTRAINT ck_flywheel_readout_window CHECK ((window_end > window_start)),
    CONSTRAINT flywheel_readouts_ci_method_check CHECK (((ci_method)::text = ANY ((ARRAY['eb_confseq'::character varying, 'none'::character varying])::text[]))),
    CONSTRAINT flywheel_readouts_computed_by_check CHECK (((computed_by)::text = ANY ((ARRAY['scheduler'::character varying, 'manual'::character varying, 'api'::character varying])::text[]))),
    CONSTRAINT flywheel_readouts_control_converted_check CHECK ((control_converted >= 0)),
    CONSTRAINT flywheel_readouts_control_n_check CHECK ((control_n >= 0)),
    CONSTRAINT flywheel_readouts_treatment_converted_check CHECK ((treatment_converted >= 0)),
    CONSTRAINT flywheel_readouts_treatment_n_check CHECK ((treatment_n >= 0))
);

ALTER TABLE ONLY public.flywheel_readouts FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_readouts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_readouts_id_seq OWNED BY public.flywheel_readouts.id;

CREATE TABLE public.flywheel_redemptions (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    offer_id bigint NOT NULL,
    campaign_id integer NOT NULL,
    customer_id integer NOT NULL,
    store_id integer NOT NULL,
    item_id integer,
    units integer NOT NULL,
    gross_value_aed numeric(14,2) DEFAULT 0 NOT NULL,
    discount_aed numeric(14,2) DEFAULT 0 NOT NULL,
    net_value_aed numeric(14,2) DEFAULT 0 NOT NULL,
    margin_aed numeric(14,2) DEFAULT 0 NOT NULL,
    idempotency_key character varying(120) NOT NULL,
    request_id character varying(64),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    tax_rate_pct numeric(6,3) DEFAULT 0 NOT NULL,
    tax_amount_aed numeric(14,2) DEFAULT 0 NOT NULL,
    net_of_tax_aed numeric(14,2) DEFAULT 0 NOT NULL,
    trace_id character varying(48),
    CONSTRAINT flywheel_redemptions_units_check CHECK ((units > 0))
);

ALTER TABLE ONLY public.flywheel_redemptions FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_redemptions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_redemptions_id_seq OWNED BY public.flywheel_redemptions.id;

CREATE TABLE public.flywheel_returns (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    redemption_id bigint NOT NULL,
    campaign_id integer,
    customer_id integer,
    units_returned integer NOT NULL,
    refund_aed numeric(14,2) DEFAULT 0 NOT NULL,
    discount_clawed_back_aed numeric(14,2) DEFAULT 0 NOT NULL,
    margin_clawed_back_aed numeric(14,2) DEFAULT 0 NOT NULL,
    restocked boolean DEFAULT true NOT NULL,
    reason text,
    idempotency_key character varying(120) NOT NULL,
    request_id character varying(64),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_returns_units_returned_check CHECK ((units_returned > 0))
);

ALTER TABLE ONLY public.flywheel_returns FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_returns_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_returns_id_seq OWNED BY public.flywheel_returns.id;

CREATE TABLE public.flywheel_seasonality_calendar (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    name character varying(60) NOT NULL,
    kind character varying(30) DEFAULT 'religious'::character varying NOT NULL,
    starts_on date NOT NULL,
    ends_on date NOT NULL,
    demand_multiplier numeric(5,3) DEFAULT 1.000 NOT NULL,
    category character varying(80),
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_season_window CHECK ((ends_on >= starts_on)),
    CONSTRAINT flywheel_seasonality_calendar_demand_multiplier_check CHECK (((demand_multiplier > (0)::numeric) AND (demand_multiplier <= (5)::numeric))),
    CONSTRAINT flywheel_seasonality_calendar_kind_check CHECK (((kind)::text = ANY ((ARRAY['religious'::character varying, 'national'::character varying, 'commercial'::character varying, 'seasonal'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_seasonality_calendar FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_seasonality_calendar_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_seasonality_calendar_id_seq OWNED BY public.flywheel_seasonality_calendar.id;

CREATE TABLE public.flywheel_settlements (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    funding_id bigint NOT NULL,
    period_start date NOT NULL,
    period_end date NOT NULL,
    incremental_units integer DEFAULT 0 NOT NULL,
    incremental_margin_aed numeric(16,2) DEFAULT 0 NOT NULL,
    amount_due_aed numeric(16,2) DEFAULT 0 NOT NULL,
    status character varying(20) DEFAULT 'draft'::character varying NOT NULL,
    dispute_reason text,
    evidence jsonb DEFAULT '{}'::jsonb NOT NULL,
    issued_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_settlement_period CHECK ((period_end > period_start)),
    CONSTRAINT flywheel_settlements_amount_due_aed_check CHECK ((amount_due_aed >= (0)::numeric)),
    CONSTRAINT flywheel_settlements_status_check CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'issued'::character varying, 'paid'::character varying, 'disputed'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_settlements FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_settlements_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_settlements_id_seq OWNED BY public.flywheel_settlements.id;

CREATE TABLE public.flywheel_shadow_decisions (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    campaign_id integer,
    customer_id integer NOT NULL,
    decision_id integer,
    model_version_id integer,
    model_label character varying(60) NOT NULL,
    rule_action character varying(30) NOT NULL,
    rule_discount_pct numeric(5,2) DEFAULT 0 NOT NULL,
    rule_eiv_aed numeric(16,2) DEFAULT 0 NOT NULL,
    rule_churn_probability double precision,
    shadow_action character varying(30) NOT NULL,
    shadow_discount_pct numeric(5,2) DEFAULT 0 NOT NULL,
    shadow_eiv_aed numeric(16,2) DEFAULT 0 NOT NULL,
    shadow_churn_probability double precision,
    agreed boolean DEFAULT true NOT NULL,
    disagreement_kind character varying(30),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_shadow_decisions_disagreement_kind_check CHECK (((disagreement_kind)::text = ANY ((ARRAY['action'::character varying, 'magnitude'::character varying, 'both'::character varying, NULL::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_shadow_decisions FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_shadow_decisions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_shadow_decisions_id_seq OWNED BY public.flywheel_shadow_decisions.id;

CREATE TABLE public.flywheel_shelf_life (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    store_id integer NOT NULL,
    item_id integer NOT NULL,
    batch_ref character varying(80) NOT NULL,
    units integer DEFAULT 0 NOT NULL,
    received_on date NOT NULL,
    expires_on date NOT NULL,
    unit_cost_aed numeric(12,4) DEFAULT 0 NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_shelf_life_window CHECK ((expires_on >= received_on)),
    CONSTRAINT flywheel_shelf_life_status_check CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'sold'::character varying, 'written_off'::character varying, 'marked_down'::character varying])::text[]))),
    CONSTRAINT flywheel_shelf_life_units_check CHECK ((units >= 0))
);

ALTER TABLE ONLY public.flywheel_shelf_life FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_shelf_life_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_shelf_life_id_seq OWNED BY public.flywheel_shelf_life.id;

CREATE TABLE public.flywheel_substitution (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    campaign_id integer NOT NULL,
    from_item_id integer NOT NULL,
    to_item_id integer NOT NULL,
    substitution_units integer DEFAULT 0 NOT NULL,
    substitution_rate numeric(6,4),
    computed_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_flywheel_substitution_distinct CHECK ((from_item_id <> to_item_id))
);

ALTER TABLE ONLY public.flywheel_substitution FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_substitution_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_substitution_id_seq OWNED BY public.flywheel_substitution.id;

CREATE TABLE public.flywheel_supplier_funding (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    supplier_id integer NOT NULL,
    campaign_id integer NOT NULL,
    funding_type character varying(20) NOT NULL,
    currency character varying(3) DEFAULT 'AED'::character varying NOT NULL,
    status character varying(20) DEFAULT 'proposed'::character varying NOT NULL,
    committed_aed numeric(16,2) DEFAULT 0 NOT NULL,
    spent_aed numeric(16,2) DEFAULT 0 NOT NULL,
    settled_aed numeric(16,2) DEFAULT 0 NOT NULL,
    rebate_per_unit_aed numeric(12,4) DEFAULT 0 NOT NULL,
    agreement_ref character varying(80),
    starts_on date,
    ends_on date,
    created_by integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_supplier_funding_settle CHECK ((settled_aed <= spent_aed)),
    CONSTRAINT ck_supplier_funding_spend CHECK ((spent_aed <= committed_aed)),
    CONSTRAINT flywheel_supplier_funding_committed_aed_check CHECK ((committed_aed >= (0)::numeric)),
    CONSTRAINT flywheel_supplier_funding_funding_type_check CHECK (((funding_type)::text = ANY ((ARRAY['co_op'::character varying, 'scan_down'::character varying, 'fixed_fee'::character varying])::text[]))),
    CONSTRAINT flywheel_supplier_funding_settled_aed_check CHECK ((settled_aed >= (0)::numeric)),
    CONSTRAINT flywheel_supplier_funding_spent_aed_check CHECK ((spent_aed >= (0)::numeric)),
    CONSTRAINT flywheel_supplier_funding_status_check CHECK (((status)::text = ANY ((ARRAY['proposed'::character varying, 'committed'::character varying, 'active'::character varying, 'settled'::character varying, 'disputed'::character varying, 'cancelled'::character varying])::text[])))
);

ALTER TABLE ONLY public.flywheel_supplier_funding FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_supplier_funding_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_supplier_funding_id_seq OWNED BY public.flywheel_supplier_funding.id;

CREATE TABLE public.flywheel_supplier_funding_skus (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    funding_id bigint NOT NULL,
    item_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.flywheel_supplier_funding_skus FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_supplier_funding_skus_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_supplier_funding_skus_id_seq OWNED BY public.flywheel_supplier_funding_skus.id;

CREATE TABLE public.flywheel_tax_rules (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    name character varying(80) NOT NULL,
    rate_pct numeric(6,3) NOT NULL,
    prices_include_tax boolean DEFAULT true NOT NULL,
    category character varying(50),
    valid_from date DEFAULT CURRENT_DATE NOT NULL,
    valid_until date,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_tax_range_ordered CHECK (((valid_until IS NULL) OR (valid_until > valid_from))),
    CONSTRAINT flywheel_tax_rules_rate_pct_check CHECK (((rate_pct >= (0)::numeric) AND (rate_pct < (100)::numeric)))
);

ALTER TABLE ONLY public.flywheel_tax_rules FORCE ROW LEVEL SECURITY;

COMMENT ON TABLE public.flywheel_tax_rules IS 'Configurable tax rules. Margin floors are evaluated NET of tax — a floor checked on a tax-inclusive amount silently overstates margin by the rate.';

CREATE SEQUENCE public.flywheel_tax_rules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_tax_rules_id_seq OWNED BY public.flywheel_tax_rules.id;

CREATE TABLE public.flywheel_transfer_recommendations (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    campaign_id integer NOT NULL,
    from_store_id integer NOT NULL,
    to_store_id integer NOT NULL,
    item_id integer NOT NULL,
    units integer NOT NULL,
    source_surplus_units integer DEFAULT 0 NOT NULL,
    status character varying(20) DEFAULT 'recommended'::character varying NOT NULL,
    stock_transfer_id integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT flywheel_transfer_distinct_stores CHECK ((from_store_id <> to_store_id)),
    CONSTRAINT flywheel_transfer_recommendations_status_check CHECK (((status)::text = ANY ((ARRAY['recommended'::character varying, 'accepted'::character varying, 'rejected'::character varying, 'executed'::character varying])::text[]))),
    CONSTRAINT flywheel_transfer_recommendations_units_check CHECK ((units > 0))
);

ALTER TABLE ONLY public.flywheel_transfer_recommendations FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.flywheel_transfer_recommendations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.flywheel_transfer_recommendations_id_seq OWNED BY public.flywheel_transfer_recommendations.id;

CREATE TABLE public.goods_receipt_lines (
    id integer NOT NULL,
    receipt_id integer NOT NULL,
    po_line_id integer NOT NULL,
    item_id integer NOT NULL,
    received_qty integer NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE ONLY public.goods_receipt_lines FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.goods_receipt_lines_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.goods_receipt_lines_id_seq OWNED BY public.goods_receipt_lines.id;

CREATE TABLE public.goods_receipts (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    po_id integer NOT NULL,
    receipt_number character varying(40) NOT NULL,
    status character varying(20) DEFAULT 'complete'::character varying NOT NULL,
    received_by integer,
    notes text,
    received_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE ONLY public.goods_receipts FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.goods_receipts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.goods_receipts_id_seq OWNED BY public.goods_receipts.id;

CREATE TABLE public.import_jobs (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    import_type text NOT NULL,
    filename text,
    status text DEFAULT 'completed'::text NOT NULL,
    total_rows integer DEFAULT 0 NOT NULL,
    imported_rows integer DEFAULT 0 NOT NULL,
    skipped_rows integer DEFAULT 0 NOT NULL,
    error_rows integer DEFAULT 0 NOT NULL,
    mapping jsonb DEFAULT '{}'::jsonb NOT NULL,
    notes jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_by text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    reversible boolean DEFAULT false NOT NULL,
    rolled_back_at timestamp with time zone,
    rolled_back_by text,
    CONSTRAINT import_jobs_rollback_is_consistent CHECK (((status = 'rolled_back'::text) = (rolled_back_at IS NOT NULL))),
    CONSTRAINT import_jobs_status_check CHECK ((status = ANY (ARRAY['running'::text, 'completed'::text, 'partial'::text, 'failed'::text, 'rolled_back'::text])))
);

CREATE SEQUENCE public.import_jobs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.import_jobs_id_seq OWNED BY public.import_jobs.id;

CREATE TABLE public.import_row_undo (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    import_job_id integer NOT NULL,
    table_name text NOT NULL,
    op text NOT NULL,
    row_id bigint NOT NULL,
    before_image jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT import_row_undo_insert_has_no_image CHECK (((op <> 'insert'::text) OR (before_image IS NULL))),
    CONSTRAINT import_row_undo_op_check CHECK ((op = ANY (ARRAY['insert'::text, 'update'::text]))),
    CONSTRAINT import_row_undo_update_has_image CHECK (((op <> 'update'::text) OR (before_image IS NOT NULL)))
);

ALTER TABLE ONLY public.import_row_undo FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.import_row_undo_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.import_row_undo_id_seq OWNED BY public.import_row_undo.id;

CREATE TABLE public.import_schedules (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    name text NOT NULL,
    import_type text NOT NULL,
    source_kind text NOT NULL,
    source_url text NOT NULL,
    mapping jsonb DEFAULT '{}'::jsonb NOT NULL,
    interval_minutes integer NOT NULL,
    active boolean DEFAULT true NOT NULL,
    next_run_at timestamp with time zone DEFAULT now() NOT NULL,
    last_run_at timestamp with time zone,
    last_status text,
    last_error text,
    last_job_id integer,
    last_content_hash text,
    consecutive_failures integer DEFAULT 0 NOT NULL,
    created_by text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    source_config jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT import_schedules_failure_has_reason CHECK (((last_status <> 'failed'::text) OR ((last_error IS NOT NULL) AND (length(btrim(last_error)) > 0)))),
    CONSTRAINT import_schedules_import_type_check CHECK ((import_type = ANY (ARRAY['stores'::text, 'items'::text, 'suppliers'::text, 'sales'::text, 'inventory'::text]))),
    CONSTRAINT import_schedules_interval_minutes_check CHECK (((interval_minutes >= 15) AND (interval_minutes <= 10080))),
    CONSTRAINT import_schedules_last_status_check CHECK ((last_status = ANY (ARRAY['ok'::text, 'failed'::text, 'skipped_unchanged'::text, 'skipped_quota'::text]))),
    CONSTRAINT import_schedules_source_kind_check CHECK ((source_kind = ANY (ARRAY['https'::text, 'sftp'::text, 'imap'::text]))),
    CONSTRAINT import_schedules_transport_has_config CHECK (((source_kind = 'https'::text) OR ((source_config ? 'host'::text) AND (source_config ? 'username'::text))))
);

ALTER TABLE ONLY public.import_schedules FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.import_schedules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.import_schedules_id_seq OWNED BY public.import_schedules.id;

CREATE TABLE public.ingest_ledger (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    source_name text NOT NULL,
    job_id text NOT NULL,
    chunk_no integer NOT NULL,
    chunk_sha256 text NOT NULL,
    row_count integer DEFAULT 0 NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    CONSTRAINT ck_ingest_status CHECK ((status = ANY (ARRAY['pending'::text, 'loaded'::text, 'failed'::text, 'skipped'::text])))
);

CREATE SEQUENCE public.ingest_ledger_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.ingest_ledger_id_seq OWNED BY public.ingest_ledger.id;

CREATE TABLE public.inventory (
    id integer NOT NULL,
    store_id integer NOT NULL,
    item_id integer NOT NULL,
    current_stock integer DEFAULT 0 NOT NULL,
    reserved_stock integer DEFAULT 0,
    available_stock integer GENERATED ALWAYS AS ((current_stock - COALESCE(reserved_stock, 0))) STORED,
    reorder_point integer DEFAULT 50,
    reorder_quantity integer DEFAULT 100,
    max_stock_level integer DEFAULT 500,
    abc_class character(1) DEFAULT 'C'::bpchar,
    unit_cost numeric(10,2) DEFAULT 0,
    total_value numeric(12,2) GENERATED ALWAYS AS (((current_stock)::numeric * unit_cost)) STORED,
    average_daily_sales numeric(10,2) DEFAULT 0,
    days_of_supply numeric(10,2) GENERATED ALWAYS AS (
CASE
    WHEN (average_daily_sales > (0)::numeric) THEN ((current_stock)::numeric / average_daily_sales)
    ELSE (999)::numeric
END) STORED,
    last_sale_date date,
    last_restock_date date,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT inventory_abc_class_check CHECK ((abc_class = ANY (ARRAY['A'::bpchar, 'B'::bpchar, 'C'::bpchar])))
);

CREATE TABLE public.inventory_batches (
    id integer NOT NULL,
    store_id integer NOT NULL,
    item_id integer NOT NULL,
    batch_number character varying(50) NOT NULL,
    quantity integer NOT NULL,
    initial_quantity integer NOT NULL,
    received_date date DEFAULT CURRENT_DATE NOT NULL,
    expiry_date date,
    unit_cost numeric(10,2) DEFAULT 0,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT inventory_batches_initial_quantity_check CHECK ((initial_quantity >= 0)),
    CONSTRAINT inventory_batches_quantity_check CHECK ((quantity >= 0)),
    CONSTRAINT inventory_batches_status_check CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'expired'::character varying, 'sold_out'::character varying, 'disposed'::character varying])::text[])))
);

CREATE SEQUENCE public.inventory_batches_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.inventory_batches_id_seq OWNED BY public.inventory_batches.id;

CREATE SEQUENCE public.inventory_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.inventory_id_seq OWNED BY public.inventory.id;

CREATE TABLE public.inventory_transactions (
    id bigint NOT NULL,
    inventory_id integer NOT NULL,
    store_id integer NOT NULL,
    item_id integer NOT NULL,
    transaction_type public.inventory_transaction_type NOT NULL,
    quantity integer NOT NULL,
    stock_before integer NOT NULL,
    stock_after integer NOT NULL,
    reference_type character varying(50),
    reference_id character varying(100),
    unit_cost numeric(10,2),
    total_cost numeric(12,2),
    notes text,
    performed_by integer,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE public.inventory_transactions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.inventory_transactions_id_seq OWNED BY public.inventory_transactions.id;

CREATE TABLE public.invoice_lines (
    id integer NOT NULL,
    invoice_id integer NOT NULL,
    description text NOT NULL,
    quantity numeric(12,2) DEFAULT 1 NOT NULL,
    unit_price_aed numeric(14,2) DEFAULT 0 NOT NULL,
    line_subtotal_aed numeric(14,2) DEFAULT 0 NOT NULL,
    vat_rate numeric(5,4) DEFAULT 0.05 NOT NULL,
    vat_amount_aed numeric(14,2) DEFAULT 0 NOT NULL,
    line_total_aed numeric(14,2) DEFAULT 0 NOT NULL
);

CREATE SEQUENCE public.invoice_lines_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.invoice_lines_id_seq OWNED BY public.invoice_lines.id;

CREATE TABLE public.invoices (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    invoice_number text NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    billing_provider text DEFAULT 'manual'::text NOT NULL,
    supplier_legal_name text,
    supplier_trn character varying(15),
    customer_legal_name text,
    customer_trn character varying(15),
    currency character(3) DEFAULT 'AED'::bpchar NOT NULL,
    subtotal_aed numeric(14,2) DEFAULT 0 NOT NULL,
    vat_rate numeric(5,4) DEFAULT 0.05 NOT NULL,
    vat_amount_aed numeric(14,2) DEFAULT 0 NOT NULL,
    total_aed numeric(14,2) DEFAULT 0 NOT NULL,
    period_start date,
    period_end date,
    po_number text,
    payment_terms text,
    payment_instructions text,
    payment_method text,
    issued_at timestamp with time zone,
    due_at timestamp with time zone,
    paid_at timestamp with time zone,
    e_invoice_status text DEFAULT 'not_submitted'::text,
    e_invoice_provider text,
    e_invoice_external_id text,
    e_invoice_payload jsonb,
    e_invoice_submitted_at timestamp with time zone,
    e_invoice_accepted_at timestamp with time zone,
    e_invoice_rejected_reason text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT invoices_e_invoice_status_check CHECK ((e_invoice_status = ANY (ARRAY['not_submitted'::text, 'submitted'::text, 'accepted'::text, 'rejected'::text]))),
    CONSTRAINT invoices_status_check CHECK ((status = ANY (ARRAY['draft'::text, 'issued'::text, 'paid'::text, 'void'::text, 'credited'::text])))
);

CREATE SEQUENCE public.invoices_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.invoices_id_seq OWNED BY public.invoices.id;

CREATE TABLE public.item_costs (
    id integer NOT NULL,
    tenant_id integer DEFAULT 1 NOT NULL,
    item_id integer NOT NULL,
    unit_cost_aed numeric(12,4) NOT NULL,
    valid_from date NOT NULL,
    valid_until date,
    source character varying(40) DEFAULT 'import'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT item_costs_range_ordered CHECK (((valid_until IS NULL) OR (valid_until > valid_from))),
    CONSTRAINT item_costs_unit_cost_aed_check CHECK ((unit_cost_aed >= (0)::numeric))
);

COMMENT ON TABLE public.item_costs IS 'Effective-dated unit cost per (tenant, item). Source of truth for COGS/margin; items.unit_cost_aed is a trigger-maintained denormalisation of the open period.';

COMMENT ON COLUMN public.item_costs.source IS 'Provenance: ''import'' (tenant-supplied), ''backfill_inventory'' (derived from the blended inventory.unit_cost at migration time), ''pos'' (connector). Never guess.';

CREATE SEQUENCE public.item_costs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.item_costs_id_seq OWNED BY public.item_costs.id;

CREATE TABLE public.items (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    category character varying(50),
    unit_price_aed numeric(10,2) DEFAULT 10.00,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    tenant_id integer DEFAULT 1 NOT NULL,
    unit_cost_aed numeric(12,4),
    import_job_id integer
);

ALTER TABLE ONLY public.items FORCE ROW LEVEL SECURITY;

COMMENT ON COLUMN public.items.unit_cost_aed IS 'CURRENT unit cost in AED, denormalised from item_costs by trg_item_costs_sync_current. NULL = cost unknown: readers must return the `needs: cost` state, never a fabricated margin. For point-in-time cost use item_cost_at() / metric_margin_fact.';

CREATE SEQUENCE public.items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.items_id_seq OWNED BY public.items.id;

CREATE TABLE public.sales_historical (
    id integer NOT NULL,
    date date NOT NULL,
    store_id integer NOT NULL,
    item_id integer NOT NULL,
    sales integer NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    tenant_id integer DEFAULT 1 NOT NULL,
    import_job_id integer
);

ALTER TABLE ONLY public.sales_historical FORCE ROW LEVEL SECURITY;

CREATE TABLE public.sales_stream_raw (
    id integer NOT NULL,
    event_id uuid NOT NULL,
    "timestamp" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    store_id integer NOT NULL,
    item_id integer NOT NULL,
    sales integer NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    tenant_id integer DEFAULT 1 NOT NULL,
    is_synthetic boolean DEFAULT false NOT NULL
)
PARTITION BY RANGE ("timestamp");

ALTER TABLE ONLY public.sales_stream_raw FORCE ROW LEVEL SECURITY;

CREATE VIEW public.sales_fact_view WITH (security_invoker='true') AS
 SELECT sales_historical.id,
    sales_historical.date,
    sales_historical.store_id,
    sales_historical.item_id,
    sales_historical.sales,
    false AS is_streaming,
    'historical'::text AS source,
    sales_historical.created_at,
    sales_historical.tenant_id
   FROM public.sales_historical
UNION ALL
 SELECT (sales_stream_raw.id + 1000000000) AS id,
    (sales_stream_raw."timestamp")::date AS date,
    sales_stream_raw.store_id,
    sales_stream_raw.item_id,
    sales_stream_raw.sales,
    true AS is_streaming,
    'streaming'::text AS source,
    COALESCE(sales_stream_raw.created_at, sales_stream_raw."timestamp") AS created_at,
    sales_stream_raw.tenant_id
   FROM public.sales_stream_raw;

CREATE VIEW public.metric_sales_fact WITH (security_invoker='true') AS
 SELECT s.tenant_id,
    s.id,
    s.date,
    s.created_at,
    s.is_streaming,
    s.store_id,
    s.item_id,
    i.category,
    s.sales AS units,
    i.unit_price_aed,
    ((s.sales)::numeric * i.unit_price_aed) AS revenue_aed,
    (s.sales < 0) AS is_return
   FROM (public.sales_fact_view s
     JOIN public.items i ON (((i.id = s.item_id) AND (i.tenant_id = s.tenant_id))));

CREATE VIEW public.metric_category_return_rate WITH (security_invoker='true') AS
 WITH c AS (
         SELECT metric_sales_fact.tenant_id,
            metric_sales_fact.category,
            COALESCE(sum(metric_sales_fact.units) FILTER (WHERE ((metric_sales_fact.units > 0) AND (metric_sales_fact.date >= (CURRENT_DATE - '30 days'::interval)))), (0)::bigint) AS gross_units,
            COALESCE(sum((- metric_sales_fact.units)) FILTER (WHERE ((metric_sales_fact.units < 0) AND (metric_sales_fact.date >= (CURRENT_DATE - '30 days'::interval)))), (0)::bigint) AS return_units
           FROM public.metric_sales_fact
          GROUP BY metric_sales_fact.tenant_id, metric_sales_fact.category
        ), r AS (
         SELECT c.tenant_id,
            c.category,
            c.gross_units,
            c.return_units,
            ((c.return_units)::numeric / (NULLIF(c.gross_units, 0))::numeric) AS rate
           FROM c
        )
 SELECT r.tenant_id,
    r.category,
    r.gross_units,
    r.return_units,
    r.rate,
    avg(r.rate) OVER (PARTITION BY r.tenant_id) AS mean_rate
   FROM r;

CREATE VIEW public.metric_category_share WITH (security_invoker='true') AS
 WITH windows AS (
         SELECT metric_sales_fact.tenant_id,
            metric_sales_fact.category,
            COALESCE(sum(metric_sales_fact.revenue_aed) FILTER (WHERE (metric_sales_fact.date >= (CURRENT_DATE - '7 days'::interval))), (0)::numeric) AS rev_recent,
            COALESCE(sum(metric_sales_fact.revenue_aed) FILTER (WHERE ((metric_sales_fact.date >= (CURRENT_DATE - '14 days'::interval)) AND (metric_sales_fact.date < (CURRENT_DATE - '7 days'::interval)))), (0)::numeric) AS rev_prior
           FROM public.metric_sales_fact
          WHERE ((metric_sales_fact.date >= (CURRENT_DATE - '14 days'::interval)) AND (metric_sales_fact.category IS NOT NULL))
          GROUP BY metric_sales_fact.tenant_id, metric_sales_fact.category
        ), totals AS (
         SELECT windows.tenant_id,
            sum(windows.rev_recent) AS tot_recent,
            sum(windows.rev_prior) AS tot_prior
           FROM windows
          GROUP BY windows.tenant_id
        )
 SELECT w.tenant_id,
    w.category,
    w.rev_recent,
    w.rev_prior,
        CASE
            WHEN (t.tot_recent > (0)::numeric) THEN round((w.rev_recent / t.tot_recent), 4)
            ELSE NULL::numeric
        END AS share_recent,
        CASE
            WHEN (t.tot_prior > (0)::numeric) THEN round((w.rev_prior / t.tot_prior), 4)
            ELSE NULL::numeric
        END AS share_prior,
        CASE
            WHEN ((t.tot_recent > (0)::numeric) AND (t.tot_prior > (0)::numeric)) THEN round((((w.rev_recent / t.tot_recent) - (w.rev_prior / t.tot_prior)) * (100)::numeric), 2)
            ELSE NULL::numeric
        END AS shift_pp
   FROM (windows w
     JOIN totals t ON ((t.tenant_id = w.tenant_id)));

COMMENT ON VIEW public.metric_category_share IS 'E3-5: share of chain revenue, recent 7d vs prior 7d, in percentage POINTS (shift_pp). A category can grow in AED and still lose share.';

CREATE VIEW public.metric_category_wow WITH (security_invoker='true') AS
 WITH per_cat AS (
         SELECT metric_sales_fact.tenant_id,
            metric_sales_fact.category,
            COALESCE(sum(metric_sales_fact.revenue_aed) FILTER (WHERE (metric_sales_fact.date >= (CURRENT_DATE - '7 days'::interval))), (0)::numeric) AS rev_recent,
            COALESCE(sum(metric_sales_fact.revenue_aed) FILTER (WHERE ((metric_sales_fact.date >= (CURRENT_DATE - '14 days'::interval)) AND (metric_sales_fact.date < (CURRENT_DATE - '7 days'::interval)))), (0)::numeric) AS rev_prior
           FROM public.metric_sales_fact
          GROUP BY metric_sales_fact.tenant_id, metric_sales_fact.category
        )
 SELECT per_cat.tenant_id,
    per_cat.category,
    per_cat.rev_recent,
    per_cat.rev_prior,
    ((per_cat.rev_recent - per_cat.rev_prior) / NULLIF(per_cat.rev_prior, (0)::numeric)) AS change
   FROM per_cat;

CREATE VIEW public.metric_inventory_state WITH (security_invoker='true') AS
 SELECT st.tenant_id,
    inv.store_id,
    st.name AS store_name,
    inv.item_id,
    it.name AS item_name,
    it.category,
    inv.current_stock,
    inv.reorder_point,
    inv.average_daily_sales,
    inv.last_sale_date,
    ((inv.current_stock)::numeric * it.unit_price_aed) AS stock_retail_aed,
    (CURRENT_DATE - inv.last_sale_date) AS days_since_last_sale,
    (inv.current_stock <= 0) AS is_out_of_stock,
    ((inv.current_stock > 0) AND (inv.current_stock <= inv.reorder_point)) AS is_below_reorder
   FROM ((public.inventory inv
     JOIN public.stores st ON ((st.id = inv.store_id)))
     JOIN public.items it ON (((it.id = inv.item_id) AND (it.tenant_id = st.tenant_id))));

COMMENT ON VIEW public.metric_inventory_state IS 'E3-5: current stock posture per store-item. There is no stock-level history, so a true stockout-days streak is not derivable — days_since_last_sale is what the data supports.';

CREATE VIEW public.metric_dead_stock_growth WITH (security_invoker='true') AS
 WITH sold AS (
         SELECT metric_sales_fact.tenant_id,
            metric_sales_fact.store_id,
            metric_sales_fact.item_id,
            sum(metric_sales_fact.units) FILTER (WHERE (metric_sales_fact.date >= (CURRENT_DATE - '30 days'::interval))) AS units_recent,
            sum(metric_sales_fact.units) FILTER (WHERE ((metric_sales_fact.date >= (CURRENT_DATE - '60 days'::interval)) AND (metric_sales_fact.date < (CURRENT_DATE - '30 days'::interval)))) AS units_prior
           FROM public.metric_sales_fact
          WHERE (metric_sales_fact.date >= (CURRENT_DATE - '60 days'::interval))
          GROUP BY metric_sales_fact.tenant_id, metric_sales_fact.store_id, metric_sales_fact.item_id
        )
 SELECT s.tenant_id,
    count(*) FILTER (WHERE ((COALESCE(sold.units_recent, (0)::bigint) <= 0) AND (s.current_stock > 0))) AS dead_skus_recent,
    count(*) FILTER (WHERE ((COALESCE(sold.units_prior, (0)::bigint) <= 0) AND (s.current_stock > 0))) AS dead_skus_prior,
    COALESCE(sum(s.stock_retail_aed) FILTER (WHERE ((COALESCE(sold.units_recent, (0)::bigint) <= 0) AND (s.current_stock > 0))), (0)::numeric) AS dead_value_recent_aed,
    COALESCE(sum(s.stock_retail_aed) FILTER (WHERE ((COALESCE(sold.units_prior, (0)::bigint) <= 0) AND (s.current_stock > 0))), (0)::numeric) AS dead_value_prior_aed
   FROM (public.metric_inventory_state s
     LEFT JOIN sold ON (((sold.tenant_id = s.tenant_id) AND (sold.store_id = s.store_id) AND (sold.item_id = s.item_id))))
  GROUP BY s.tenant_id;

CREATE VIEW public.metric_forecast_miss WITH (security_invoker='true') AS
 WITH daily AS (
         SELECT metric_sales_fact.tenant_id,
            metric_sales_fact.store_id,
            metric_sales_fact.date,
            sum(metric_sales_fact.units) AS units
           FROM public.metric_sales_fact
          WHERE (metric_sales_fact.date >= (CURRENT_DATE - '21 days'::interval))
          GROUP BY metric_sales_fact.tenant_id, metric_sales_fact.store_id, metric_sales_fact.date
        ), paired AS (
         SELECT d.tenant_id,
            d.store_id,
            d.date,
            d.units AS actual,
            b.units AS naive
           FROM (daily d
             JOIN daily b ON (((b.tenant_id = d.tenant_id) AND (b.store_id = d.store_id) AND (b.date = (d.date - 7)))))
          WHERE (d.date >= (CURRENT_DATE - '7 days'::interval))
        )
 SELECT p.tenant_id,
    p.store_id,
    st.name AS store_name,
    sum(p.actual) AS actual_units,
    sum(p.naive) AS naive_units,
    sum(abs((p.actual - p.naive))) AS abs_error_units,
        CASE
            WHEN (sum(p.actual) > (0)::numeric) THEN round((sum(abs((p.actual - p.naive))) / sum(p.actual)), 4)
            ELSE NULL::numeric
        END AS wape,
    count(*) AS days_compared
   FROM (paired p
     JOIN public.stores st ON ((st.id = p.store_id)))
  GROUP BY p.tenant_id, p.store_id, st.name;

COMMENT ON VIEW public.metric_forecast_miss IS 'E3-5: WAPE of the last 7 days against the seasonal-naive (t-7) baseline the app publishes. wape is NULL, never 0, when there were no actual units to divide by.';

CREATE VIEW public.metric_margin_fact WITH (security_invoker='true') AS
 SELECT s.tenant_id,
    s.date,
    s.store_id,
    s.item_id,
    i.category,
    s.sales AS units,
    i.unit_price_aed,
    ((s.sales)::numeric * i.unit_price_aed) AS revenue_aed,
    c.unit_cost_aed,
    c.source AS cost_source,
    ((s.sales)::numeric * c.unit_cost_aed) AS cogs_aed,
    ((s.sales)::numeric * (i.unit_price_aed - c.unit_cost_aed)) AS gross_margin_aed
   FROM ((public.sales_fact_view s
     JOIN public.items i ON (((i.id = s.item_id) AND (i.tenant_id = s.tenant_id))))
     LEFT JOIN public.item_costs c ON (((c.tenant_id = s.tenant_id) AND (c.item_id = s.item_id) AND (s.date >= c.valid_from) AND ((c.valid_until IS NULL) OR (s.date < c.valid_until)))));

COMMENT ON VIEW public.metric_margin_fact IS 'E2-3: point-in-time COGS + gross margin. cogs_aed/gross_margin_aed are NULL where no cost period covers the sale date — readers must surface `needs: cost`, not zero.';

CREATE VIEW public.metric_price_anomaly WITH (security_invoker='true') AS
 SELECT m.tenant_id,
    m.item_id,
    i.name AS item_name,
    m.category,
    sum(m.units) AS units_30d,
    round(sum(m.revenue_aed), 2) AS revenue_30d_aed,
    round(sum(m.cogs_aed), 2) AS cogs_30d_aed,
    round(sum(m.gross_margin_aed), 2) AS margin_30d_aed,
        CASE
            WHEN (sum(m.revenue_aed) > (0)::numeric) THEN round((sum(m.gross_margin_aed) / sum(m.revenue_aed)), 4)
            ELSE NULL::numeric
        END AS margin_ratio,
    max(m.unit_price_aed) AS unit_price_aed,
    max(m.unit_cost_aed) AS unit_cost_aed
   FROM (public.metric_margin_fact m
     JOIN public.items i ON (((i.id = m.item_id) AND (i.tenant_id = m.tenant_id))))
  WHERE ((m.date >= (CURRENT_DATE - '30 days'::interval)) AND (m.cogs_aed IS NOT NULL) AND (m.units > 0))
  GROUP BY m.tenant_id, m.item_id, i.name, m.category;

COMMENT ON VIEW public.metric_price_anomaly IS 'E3-5: 30d margin per item, only for items whose sales fall inside a cost period. Items without cost are ABSENT — never assume a missing row means a healthy margin.';

CREATE VIEW public.metric_returns_wow WITH (security_invoker='true') AS
 WITH r AS (
         SELECT sales_fact_view.tenant_id,
            COALESCE(sum(abs(sales_fact_view.sales)) FILTER (WHERE ((sales_fact_view.sales < 0) AND (sales_fact_view.date >= (CURRENT_DATE - '7 days'::interval)))), (0)::bigint) AS returns_recent_units,
            COALESCE(sum(abs(sales_fact_view.sales)) FILTER (WHERE ((sales_fact_view.sales < 0) AND (sales_fact_view.date >= (CURRENT_DATE - '14 days'::interval)) AND (sales_fact_view.date < (CURRENT_DATE - '7 days'::interval)))), (0)::bigint) AS returns_prior_units
           FROM public.sales_fact_view
          GROUP BY sales_fact_view.tenant_id
        )
 SELECT r.tenant_id,
    r.returns_recent_units,
    r.returns_prior_units,
    (((r.returns_recent_units - r.returns_prior_units))::numeric / (NULLIF(r.returns_prior_units, 0))::numeric) AS change
   FROM r;

CREATE VIEW public.metric_store_wow WITH (security_invoker='true') AS
 WITH per_store AS (
         SELECT f.tenant_id,
            f.store_id,
            st.name AS store_name,
            COALESCE(sum(f.revenue_aed) FILTER (WHERE (f.date >= (CURRENT_DATE - '7 days'::interval))), (0)::numeric) AS rev_recent,
            COALESCE(sum(f.revenue_aed) FILTER (WHERE ((f.date >= (CURRENT_DATE - '14 days'::interval)) AND (f.date < (CURRENT_DATE - '7 days'::interval)))), (0)::numeric) AS rev_prior
           FROM (public.metric_sales_fact f
             JOIN public.stores st ON (((st.id = f.store_id) AND (st.tenant_id = f.tenant_id))))
          GROUP BY f.tenant_id, f.store_id, st.name
        )
 SELECT per_store.tenant_id,
    per_store.store_id,
    per_store.store_name,
    per_store.rev_recent,
    per_store.rev_prior,
    ((per_store.rev_recent - per_store.rev_prior) / NULLIF(per_store.rev_prior, (0)::numeric)) AS change,
    avg(((per_store.rev_recent - per_store.rev_prior) / NULLIF(per_store.rev_prior, (0)::numeric))) OVER (PARTITION BY per_store.tenant_id) AS chain_avg_change,
    (avg(((per_store.rev_recent - per_store.rev_prior) / NULLIF(per_store.rev_prior, (0)::numeric))) OVER (PARTITION BY per_store.tenant_id) - ((per_store.rev_recent - per_store.rev_prior) / NULLIF(per_store.rev_prior, (0)::numeric))) AS gap_pp
   FROM per_store;

CREATE TABLE public.purchase_orders (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    supplier_id integer NOT NULL,
    po_number character varying(40) NOT NULL,
    status character varying(20) DEFAULT 'draft'::character varying NOT NULL,
    total_amount numeric(14,2) DEFAULT 0 NOT NULL,
    currency character varying(8) DEFAULT 'AED'::character varying NOT NULL,
    source character varying(30) DEFAULT 'manual'::character varying NOT NULL,
    notes text,
    created_by integer,
    approved_by integer,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    approved_at timestamp with time zone,
    sent_at timestamp with time zone,
    received_at timestamp with time zone
);

ALTER TABLE ONLY public.purchase_orders FORCE ROW LEVEL SECURITY;

CREATE TABLE public.suppliers (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    name character varying(200) NOT NULL,
    contact_email character varying(255),
    contact_phone character varying(40),
    lead_time_days integer DEFAULT 7 NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    import_job_id integer
);

ALTER TABLE ONLY public.suppliers FORCE ROW LEVEL SECURITY;

CREATE VIEW public.metric_supplier_overdue WITH (security_invoker='true') AS
 SELECT po.tenant_id,
    po.supplier_id,
    sp.name AS supplier_name,
    count(*) AS overdue_pos,
    round(sum(po.total_amount), 2) AS overdue_value_aed,
    max((CURRENT_DATE - ((po.sent_at)::date + COALESCE(sp.lead_time_days, 7)))) AS max_days_overdue,
    round(avg((CURRENT_DATE - ((po.sent_at)::date + COALESCE(sp.lead_time_days, 7)))), 1) AS avg_days_overdue
   FROM (public.purchase_orders po
     JOIN public.suppliers sp ON ((sp.id = po.supplier_id)))
  WHERE (((po.status)::text = ANY ((ARRAY['sent'::character varying, 'approved'::character varying])::text[])) AND (po.sent_at IS NOT NULL) AND (((po.sent_at)::date + COALESCE(sp.lead_time_days, 7)) < CURRENT_DATE))
  GROUP BY po.tenant_id, po.supplier_id, sp.name;

CREATE VIEW public.metric_zero_sales_sku WITH (security_invoker='true') AS
 SELECT s.tenant_id,
    s.store_id,
    s.store_name,
    s.item_id,
    s.item_name,
    s.category,
    s.current_stock,
    s.stock_retail_aed,
    s.days_since_last_sale
   FROM public.metric_inventory_state s
  WHERE ((s.current_stock > 0) AND (NOT (EXISTS ( SELECT 1
           FROM public.metric_sales_fact m
          WHERE ((m.tenant_id = s.tenant_id) AND (m.store_id = s.store_id) AND (m.item_id = s.item_id) AND (m.date >= (CURRENT_DATE - '30 days'::interval)) AND (m.units > 0))))));

CREATE MATERIALIZED VIEW public.mv_daily_sales_by_store AS
 SELECT sales_fact_view.date,
    sales_fact_view.store_id,
    count(*) AS transaction_count,
    sum(
        CASE
            WHEN (sales_fact_view.sales > 0) THEN sales_fact_view.sales
            ELSE 0
        END) AS total_sales,
    sum(
        CASE
            WHEN (sales_fact_view.sales < 0) THEN abs(sales_fact_view.sales)
            ELSE 0
        END) AS total_returns,
    sum(sales_fact_view.sales) AS net_sales,
    avg(sales_fact_view.sales) AS avg_sale,
    count(DISTINCT sales_fact_view.item_id) AS unique_items
   FROM public.sales_fact_view
  GROUP BY sales_fact_view.date, sales_fact_view.store_id
  WITH NO DATA;

CREATE MATERIALIZED VIEW public.mv_hourly_sales_pattern AS
 SELECT EXTRACT(dow FROM sales_fact_view.created_at) AS day_of_week,
    EXTRACT(hour FROM sales_fact_view.created_at) AS hour_of_day,
    sales_fact_view.store_id,
    count(*) AS transaction_count,
    sum(sales_fact_view.sales) AS total_sales,
    avg(sales_fact_view.sales) AS avg_sales
   FROM public.sales_fact_view
  WHERE (sales_fact_view.created_at >= (CURRENT_DATE - '90 days'::interval))
  GROUP BY (EXTRACT(dow FROM sales_fact_view.created_at)), (EXTRACT(hour FROM sales_fact_view.created_at)), sales_fact_view.store_id
  WITH NO DATA;

CREATE MATERIALIZED VIEW public.mv_weekly_sales_by_category AS
 SELECT date_trunc('week'::text, (s.date)::timestamp with time zone) AS week_start,
    i.category,
    sum(s.sales) AS total_sales,
    count(*) AS transaction_count,
    count(DISTINCT s.store_id) AS stores_count
   FROM (public.sales_fact_view s
     JOIN public.items i ON ((s.item_id = i.id)))
  GROUP BY (date_trunc('week'::text, (s.date)::timestamp with time zone)), i.category
  WITH NO DATA;

CREATE TABLE public.notification_preferences (
    user_id integer NOT NULL,
    tenant_id integer NOT NULL,
    muted_types jsonb DEFAULT '[]'::jsonb NOT NULL,
    email_enabled boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE public.notifications (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    user_id integer,
    type text NOT NULL,
    title text NOT NULL,
    body text,
    severity text DEFAULT 'info'::text NOT NULL,
    link text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    read_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT notifications_severity_check CHECK ((severity = ANY (ARRAY['critical'::text, 'high'::text, 'medium'::text, 'low'::text, 'info'::text])))
);

CREATE SEQUENCE public.notifications_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.notifications_id_seq OWNED BY public.notifications.id;

CREATE TABLE public.online_prices (
    id bigint NOT NULL,
    tenant_id integer DEFAULT 1 NOT NULL,
    item_id integer NOT NULL,
    channel text DEFAULT 'online'::text NOT NULL,
    price_aed numeric NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE public.online_prices_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.online_prices_id_seq OWNED BY public.online_prices.id;

CREATE TABLE public.operations_events (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    run_id bigint NOT NULL,
    proposal_id bigint,
    event_type text NOT NULL,
    actor text,
    actor_user_id integer,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    request_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.operations_events FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.operations_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.operations_events_id_seq OWNED BY public.operations_events.id;

CREATE TABLE public.operations_proposals (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    run_id bigint NOT NULL,
    finding_id bigint,
    action_type text NOT NULL,
    status text DEFAULT 'awaiting_approval'::text NOT NULL,
    title text NOT NULL,
    recommendation jsonb DEFAULT '{}'::jsonb NOT NULL,
    calculated_parameters jsonb DEFAULT '{}'::jsonb NOT NULL,
    target_store_ids integer[] DEFAULT '{}'::integer[] NOT NULL,
    target_item_ids integer[] DEFAULT '{}'::integer[] NOT NULL,
    risk_level text DEFAULT 'medium'::text NOT NULL,
    required_approval_role text NOT NULL,
    expires_at timestamp with time zone,
    version integer DEFAULT 1 NOT NULL,
    idempotency_key text,
    approved_by text,
    approved_at timestamp with time zone,
    rejection_reason text,
    assigned_to text,
    due_at timestamp with time zone,
    executed_ref text,
    executed_at timestamp with time zone,
    payload_version text DEFAULT 'v1'::text NOT NULL,
    created_by text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT operations_proposals_action_type_check CHECK ((action_type = ANY (ARRAY['replenishment_draft'::text, 'stock_transfer_draft'::text, 'investigation_task'::text]))),
    CONSTRAINT operations_proposals_required_approval_role_check CHECK ((required_approval_role = ANY (ARRAY['analyst'::text, 'store_manager'::text, 'regional_manager'::text, 'super_admin'::text]))),
    CONSTRAINT operations_proposals_risk_level_check CHECK ((risk_level = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text]))),
    CONSTRAINT operations_proposals_status_check CHECK ((status = ANY (ARRAY['awaiting_approval'::text, 'approved'::text, 'rejected'::text, 'executing'::text, 'executed'::text, 'execution_failed'::text, 'expired'::text, 'cancelled'::text, 'superseded'::text])))
);

ALTER TABLE ONLY public.operations_proposals FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.operations_proposals_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.operations_proposals_id_seq OWNED BY public.operations_proposals.id;

CREATE TABLE public.operations_runs (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    finding_id bigint,
    status text DEFAULT 'analyzing'::text NOT NULL,
    phase text,
    state jsonb DEFAULT '{}'::jsonb NOT NULL,
    refusal_reason text,
    error text,
    payload_version text DEFAULT 'v1'::text NOT NULL,
    graph_version text DEFAULT 'ops-v1'::text NOT NULL,
    prompt_version text DEFAULT 'ops-recommend-v1'::text NOT NULL,
    created_by text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT operations_runs_status_check CHECK ((status = ANY (ARRAY['analyzing'::text, 'awaiting_approval'::text, 'executing'::text, 'measuring'::text, 'completed'::text, 'refused'::text, 'escalated'::text, 'rejected'::text, 'cancelled'::text, 'failed'::text])))
);

ALTER TABLE ONLY public.operations_runs FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.operations_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.operations_runs_id_seq OWNED BY public.operations_runs.id;

CREATE TABLE public.outcome_pricing_plans (
    tenant_id integer NOT NULL,
    base_fee_aed numeric(12,2) DEFAULT 0 NOT NULL,
    value_share_pct numeric(5,2) DEFAULT 0 NOT NULL,
    savings_guarantee_multiple numeric(5,2) DEFAULT 0 NOT NULL,
    currency character(3) DEFAULT 'AED'::bpchar NOT NULL,
    active boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE public.password_reset_tokens (
    id integer NOT NULL,
    user_id integer NOT NULL,
    token character varying(255) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE public.password_reset_tokens_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.password_reset_tokens_id_seq OWNED BY public.password_reset_tokens.id;

CREATE TABLE public.payment_intents (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    invoice_id integer,
    provider text NOT NULL,
    amount_aed numeric(12,2) NOT NULL,
    currency text DEFAULT 'AED'::text NOT NULL,
    status text DEFAULT 'created'::text NOT NULL,
    external_ref text,
    checkout_url text,
    settled_by_event_id integer,
    failure_reason text,
    created_by text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT payment_intents_amount_aed_check CHECK ((amount_aed >= (0)::numeric)),
    CONSTRAINT payment_intents_paid_has_event CHECK (((status <> 'paid'::text) OR (settled_by_event_id IS NOT NULL))),
    CONSTRAINT payment_intents_status_check CHECK ((status = ANY (ARRAY['created'::text, 'pending'::text, 'paid'::text, 'failed'::text, 'cancelled'::text, 'expired'::text])))
);

ALTER TABLE ONLY public.payment_intents FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.payment_intents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.payment_intents_id_seq OWNED BY public.payment_intents.id;

CREATE TABLE public.payment_webhook_events (
    id integer NOT NULL,
    provider text NOT NULL,
    event_ref text,
    signature_verified boolean DEFAULT false NOT NULL,
    intent_id integer,
    result text,
    payload jsonb,
    processed boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE public.payment_webhook_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.payment_webhook_events_id_seq OWNED BY public.payment_webhook_events.id;

CREATE TABLE public.pos_connections (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    vendor text NOT NULL,
    status text DEFAULT 'disconnected'::text NOT NULL,
    external_account_ref text,
    credential_env text,
    scopes text,
    sync_cursor text,
    connected_at timestamp with time zone,
    last_sync_at timestamp with time zone,
    last_sync_status text,
    last_sync_error text,
    created_by text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT pos_connections_connected_has_account CHECK (((status <> 'connected'::text) OR (external_account_ref IS NOT NULL))),
    CONSTRAINT pos_connections_status_check CHECK ((status = ANY (ARRAY['disconnected'::text, 'connecting'::text, 'connected'::text, 'error'::text])))
);

ALTER TABLE ONLY public.pos_connections FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.pos_connections_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.pos_connections_id_seq OWNED BY public.pos_connections.id;

CREATE TABLE public.pos_sync_runs (
    id bigint NOT NULL,
    connection_id integer NOT NULL,
    tenant_id integer NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    status text DEFAULT 'running'::text NOT NULL,
    window_start date,
    window_end date,
    receipts_ingested integer DEFAULT 0 NOT NULL,
    lines_ingested integer DEFAULT 0 NOT NULL,
    aggregates_computed integer DEFAULT 0 NOT NULL,
    error text,
    CONSTRAINT pos_sync_runs_status_check CHECK ((status = ANY (ARRAY['running'::text, 'ok'::text, 'error'::text])))
);

ALTER TABLE ONLY public.pos_sync_runs FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.pos_sync_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.pos_sync_runs_id_seq OWNED BY public.pos_sync_runs.id;

CREATE TABLE public.predictions (
    id integer NOT NULL,
    store_id integer NOT NULL,
    item_id integer NOT NULL,
    prediction_date date NOT NULL,
    predicted_sales double precision NOT NULL,
    confidence_lower double precision,
    confidence_upper double precision,
    model_version character varying(50),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE public.predictions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.predictions_id_seq OWNED BY public.predictions.id;

CREATE TABLE public.procurement_events (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    event_type character varying(40) NOT NULL,
    entity_type character varying(30) NOT NULL,
    entity_id integer,
    entity_ref character varying(60),
    actor_user_id integer,
    summary text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE ONLY public.procurement_events FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.procurement_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.procurement_events_id_seq OWNED BY public.procurement_events.id;

CREATE TABLE public.product_suppliers (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    item_id integer NOT NULL,
    supplier_id integer NOT NULL,
    unit_cost numeric(12,2) DEFAULT 0 NOT NULL,
    moq integer DEFAULT 1 NOT NULL,
    lead_time_days integer DEFAULT 7 NOT NULL,
    is_preferred boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE ONLY public.product_suppliers FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.product_suppliers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.product_suppliers_id_seq OWNED BY public.product_suppliers.id;

CREATE TABLE public.promotion_items (
    id integer NOT NULL,
    promotion_id integer NOT NULL,
    item_id integer NOT NULL,
    custom_discount_value numeric(10,2),
    required_quantity integer DEFAULT 1,
    free_quantity integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE ONLY public.promotion_items FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.promotion_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.promotion_items_id_seq OWNED BY public.promotion_items.id;

CREATE TABLE public.promotion_stores (
    id integer NOT NULL,
    promotion_id integer NOT NULL,
    store_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE ONLY public.promotion_stores FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.promotion_stores_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.promotion_stores_id_seq OWNED BY public.promotion_stores.id;

CREATE TABLE public.promotions (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    promotion_code character varying(50),
    promotion_type public.promotion_type NOT NULL,
    discount_value numeric(10,2) NOT NULL,
    discount_cap numeric(10,2),
    applies_to_all_stores boolean DEFAULT true,
    applies_to_all_items boolean DEFAULT false,
    minimum_purchase numeric(10,2),
    minimum_quantity integer,
    max_uses_total integer,
    max_uses_per_customer integer,
    current_uses integer DEFAULT 0,
    start_date timestamp with time zone NOT NULL,
    end_date timestamp with time zone NOT NULL,
    status public.promotion_status DEFAULT 'draft'::public.promotion_status,
    total_revenue numeric(14,2) DEFAULT 0,
    total_discount_given numeric(12,2) DEFAULT 0,
    total_transactions integer DEFAULT 0,
    created_by integer,
    approved_by integer,
    approved_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    tenant_id integer DEFAULT 1 NOT NULL
);

ALTER TABLE ONLY public.promotions FORCE ROW LEVEL SECURITY;

COMMENT ON COLUMN public.promotions.tenant_id IS 'Owning tenant. Added by migration 060: the write endpoints previously scoped on role alone, so any promotions manager could edit another tenant''s promotion by id.';

CREATE SEQUENCE public.promotions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.promotions_id_seq OWNED BY public.promotions.id;

CREATE TABLE public.purchase_order_lines (
    id integer NOT NULL,
    po_id integer NOT NULL,
    item_id integer NOT NULL,
    quantity integer NOT NULL,
    unit_cost numeric(12,2) DEFAULT 0 NOT NULL,
    line_total numeric(14,2) DEFAULT 0 NOT NULL,
    days_of_cover numeric(8,1),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    received_qty integer DEFAULT 0 NOT NULL
);

ALTER TABLE ONLY public.purchase_order_lines FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.purchase_order_lines_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.purchase_order_lines_id_seq OWNED BY public.purchase_order_lines.id;

CREATE SEQUENCE public.purchase_orders_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.purchase_orders_id_seq OWNED BY public.purchase_orders.id;

CREATE SEQUENCE public.regions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.regions_id_seq OWNED BY public.regions.id;

CREATE TABLE public.report_history (
    id integer NOT NULL,
    scheduled_report_id integer,
    report_type character varying(100) NOT NULL,
    report_name character varying(255) NOT NULL,
    parameters jsonb,
    status public.report_status DEFAULT 'pending'::public.report_status,
    format public.report_format,
    file_path character varying(500),
    file_size_bytes bigint,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    duration_seconds integer,
    error_message text,
    retry_count integer DEFAULT 0,
    generated_by integer,
    download_count integer DEFAULT 0,
    last_downloaded_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE public.report_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.report_history_id_seq OWNED BY public.report_history.id;

CREATE TABLE public.retention_budget_ledger (
    id bigint NOT NULL,
    tenant_id integer DEFAULT 1 NOT NULL,
    campaign_id integer NOT NULL,
    entry_type character varying(20) NOT NULL,
    amount_aed numeric(14,2) NOT NULL,
    balance_before_aed numeric(14,2) NOT NULL,
    balance_after_aed numeric(14,2) NOT NULL,
    currency character varying(8) DEFAULT 'AED'::character varying NOT NULL,
    source_type character varying(30) NOT NULL,
    source_id integer,
    idempotency_key character varying(80),
    actor_user_id integer,
    reason text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT retention_budget_ledger_entry_type_check CHECK (((entry_type)::text = ANY ((ARRAY['reserve'::character varying, 'release'::character varying, 'spend'::character varying])::text[])))
);

CREATE SEQUENCE public.retention_budget_ledger_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.retention_budget_ledger_id_seq OWNED BY public.retention_budget_ledger.id;

CREATE TABLE public.retention_campaigns (
    id integer NOT NULL,
    tenant_id integer DEFAULT 1 NOT NULL,
    name character varying(200) NOT NULL,
    objective character varying(40) DEFAULT 'churn_retention'::character varying NOT NULL,
    status character varying(30) DEFAULT 'draft'::character varying NOT NULL,
    paused_reason text,
    store_id integer NOT NULL,
    item_id integer NOT NULL,
    starts_on date NOT NULL,
    ends_on date NOT NULL,
    max_discount_pct numeric(5,2) DEFAULT 15 NOT NULL,
    min_margin_pct numeric(5,2) DEFAULT 10 NOT NULL,
    discount_budget_aed numeric(14,2) NOT NULL,
    budget_reserved_aed numeric(14,2) DEFAULT 0 NOT NULL,
    budget_spent_aed numeric(14,2) DEFAULT 0 NOT NULL,
    control_pct numeric(5,2) DEFAULT 10 NOT NULL,
    churn_threshold numeric(4,3) DEFAULT 0.5 NOT NULL,
    safety_stock_units integer DEFAULT 20 NOT NULL,
    contact_cap_month integer DEFAULT 4 NOT NULL,
    simulation jsonb,
    model_version character varying(40),
    policy_version character varying(40) DEFAULT 'policy_v1'::character varying NOT NULL,
    requisition_po_id integer,
    created_by integer,
    approved_by integer,
    approved_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_retention_budget_nonneg CHECK (((discount_budget_aed >= (0)::numeric) AND (budget_reserved_aed >= (0)::numeric) AND (budget_spent_aed >= (0)::numeric))),
    CONSTRAINT ck_retention_dates CHECK ((ends_on >= starts_on)),
    CONSTRAINT ck_retention_spend_within_budget CHECK ((budget_spent_aed <= discount_budget_aed))
);

CREATE SEQUENCE public.retention_campaigns_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.retention_campaigns_id_seq OWNED BY public.retention_campaigns.id;

CREATE TABLE public.retention_events (
    id bigint NOT NULL,
    tenant_id integer DEFAULT 1 NOT NULL,
    event_type character varying(50) NOT NULL,
    entity_type character varying(30) NOT NULL,
    entity_id integer,
    actor_user_id integer,
    summary text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE public.retention_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.retention_events_id_seq OWNED BY public.retention_events.id;

CREATE VIEW public.role_performance_view AS
 SELECT e.role,
    count(DISTINCT e.id) AS employee_count,
    round(avg(ep.performance_score), 2) AS avg_performance_score,
    round(avg(ep.sales_achieved), 2) AS avg_sales,
    round(avg(ep.customer_rating), 2) AS avg_customer_rating,
    round(avg(ep.attendance_percentage), 2) AS avg_attendance,
    sum(ep.transactions_count) AS total_transactions,
    sum(ep.items_sold) AS total_items_sold
   FROM (public.employees e
     LEFT JOIN public.employee_performance ep ON ((e.id = ep.employee_id)))
  WHERE (e.status = 'active'::public.employee_status)
  GROUP BY e.role;

CREATE VIEW public.sage_sales WITH (security_invoker='false') AS
 SELECT s.id,
    s.date,
    s.store_id,
    st.name AS store_name,
    s.item_id,
    i.name AS item_name,
    i.category,
    s.sales AS units,
    i.unit_price_aed,
    ((s.sales)::numeric * i.unit_price_aed) AS revenue_aed,
    s.is_streaming,
    (s.sales < 0) AS is_return
   FROM ((public.sales_fact_view s
     JOIN public.items i ON (((i.id = s.item_id) AND (i.tenant_id = s.tenant_id))))
     JOIN public.stores st ON (((st.id = s.store_id) AND (st.tenant_id = s.tenant_id))))
  WHERE ((s.tenant_id = public.current_tenant_id()) AND public.sage_store_in_scope(s.store_id));

CREATE VIEW public.sage_category_performance WITH (security_invoker='false') AS
 SELECT sage_sales.category,
    sum(sage_sales.units) AS units,
    sum(sage_sales.revenue_aed) AS revenue_aed
   FROM public.sage_sales
  GROUP BY sage_sales.category;

CREATE VIEW public.sage_crm_pipeline AS
 SELECT crm_opportunities.id AS opportunity_id,
    crm_opportunities.name AS opportunity_name,
    crm_opportunities.zone,
    crm_opportunities.stage,
    crm_opportunities.expected_revenue,
    crm_opportunities.distributor_id
   FROM public.crm_opportunities
  WHERE (crm_opportunities.tenant_id = public.current_tenant_id());

CREATE VIEW public.sage_daily_sales WITH (security_invoker='false') AS
 SELECT sage_sales.date,
    sum(sage_sales.units) AS units,
    sum(sage_sales.revenue_aed) AS revenue_aed,
    count(*) AS line_count
   FROM public.sage_sales
  GROUP BY sage_sales.date;

CREATE VIEW public.sage_distributors AS
 SELECT distributors.id AS distributor_id,
    distributors.name AS distributor_name,
    distributors.zone,
    distributors.active
   FROM public.distributors
  WHERE (distributors.tenant_id = public.current_tenant_id());

CREATE VIEW public.sage_item_performance WITH (security_invoker='false') AS
 SELECT sage_sales.item_id,
    sage_sales.item_name,
    sage_sales.category,
    sage_sales.unit_price_aed,
    sum(sage_sales.units) AS units,
    sum(sage_sales.revenue_aed) AS revenue_aed
   FROM public.sage_sales
  GROUP BY sage_sales.item_id, sage_sales.item_name, sage_sales.category, sage_sales.unit_price_aed;

CREATE VIEW public.sage_items WITH (security_invoker='false') AS
 SELECT items.id AS item_id,
    items.name AS item_name,
    items.category,
    items.unit_price_aed
   FROM public.items
  WHERE (items.tenant_id = public.current_tenant_id());

CREATE VIEW public.sage_online_prices AS
 SELECT o.item_id,
    i.name AS item_name,
    i.category,
    o.channel,
    o.price_aed
   FROM (public.online_prices o
     JOIN public.items i ON (((i.id = o.item_id) AND (i.tenant_id = o.tenant_id))))
  WHERE (o.tenant_id = public.current_tenant_id());

CREATE VIEW public.sage_store_performance WITH (security_invoker='false') AS
 SELECT sage_sales.store_id,
    sage_sales.store_name,
    sum(sage_sales.units) AS units,
    sum(sage_sales.revenue_aed) AS revenue_aed,
    count(*) AS line_count
   FROM public.sage_sales
  GROUP BY sage_sales.store_id, sage_sales.store_name;

CREATE VIEW public.sage_stores WITH (security_invoker='false') AS
 SELECT stores.id AS store_id,
    stores.name AS store_name,
    stores.location,
    stores.zone
   FROM public.stores
  WHERE ((stores.tenant_id = public.current_tenant_id()) AND public.sage_store_in_scope(stores.id));

CREATE VIEW public.sage_targets AS
 SELECT company_targets.metric,
    company_targets.label,
    company_targets.year,
    company_targets.value,
    company_targets.unit,
    company_targets.source_doc
   FROM public.company_targets
  WHERE (company_targets.tenant_id = public.current_tenant_id());

CREATE VIEW public.sage_zones AS
 SELECT DISTINCT stores.zone
   FROM public.stores
  WHERE ((stores.tenant_id = public.current_tenant_id()) AND (stores.zone IS NOT NULL));

CREATE SEQUENCE public.sales_historical_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.sales_historical_id_seq OWNED BY public.sales_historical.id;

CREATE TABLE public.sales_rollup_daily (
    tenant_id integer NOT NULL,
    store_id integer NOT NULL,
    item_id integer NOT NULL,
    day date NOT NULL,
    units numeric(16,2) DEFAULT 0 NOT NULL,
    revenue_aed numeric(18,2) DEFAULT 0 NOT NULL,
    txn_count bigint DEFAULT 0 NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE public.sales_stream_raw_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.sales_stream_raw_id_seq OWNED BY public.sales_stream_raw.id;

CREATE TABLE public.sales_stream_raw_2026_08 (
    id integer DEFAULT nextval('public.sales_stream_raw_id_seq'::regclass) NOT NULL,
    event_id uuid NOT NULL,
    "timestamp" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    store_id integer NOT NULL,
    item_id integer NOT NULL,
    sales integer NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    tenant_id integer DEFAULT 1 NOT NULL,
    is_synthetic boolean DEFAULT false NOT NULL
);

CREATE TABLE public.sales_stream_raw_2026_09 (
    id integer DEFAULT nextval('public.sales_stream_raw_id_seq'::regclass) NOT NULL,
    event_id uuid NOT NULL,
    "timestamp" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    store_id integer NOT NULL,
    item_id integer NOT NULL,
    sales integer NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    tenant_id integer DEFAULT 1 NOT NULL,
    is_synthetic boolean DEFAULT false NOT NULL
);

CREATE TABLE public.sales_stream_raw_2026_10 (
    id integer DEFAULT nextval('public.sales_stream_raw_id_seq'::regclass) NOT NULL,
    event_id uuid NOT NULL,
    "timestamp" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    store_id integer NOT NULL,
    item_id integer NOT NULL,
    sales integer NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    tenant_id integer DEFAULT 1 NOT NULL,
    is_synthetic boolean DEFAULT false NOT NULL
);

CREATE TABLE public.sales_stream_raw_2026_11 (
    id integer DEFAULT nextval('public.sales_stream_raw_id_seq'::regclass) NOT NULL,
    event_id uuid NOT NULL,
    "timestamp" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    store_id integer NOT NULL,
    item_id integer NOT NULL,
    sales integer NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    tenant_id integer DEFAULT 1 NOT NULL,
    is_synthetic boolean DEFAULT false NOT NULL
);

CREATE TABLE public.sales_stream_raw_default (
    id integer DEFAULT nextval('public.sales_stream_raw_id_seq'::regclass) NOT NULL,
    event_id uuid NOT NULL,
    "timestamp" timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    store_id integer NOT NULL,
    item_id integer NOT NULL,
    sales integer NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    tenant_id integer DEFAULT 1 NOT NULL,
    is_synthetic boolean DEFAULT false NOT NULL
);

CREATE TABLE public.scheduled_reports (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    report_type character varying(100) NOT NULL,
    parameters jsonb DEFAULT '{}'::jsonb,
    frequency public.report_frequency NOT NULL,
    day_of_week integer,
    day_of_month integer,
    time_of_day time without time zone DEFAULT '08:00:00'::time without time zone,
    timezone character varying(50) DEFAULT 'Asia/Dubai'::character varying,
    format public.report_format DEFAULT 'pdf'::public.report_format,
    recipient_emails text[],
    recipient_users integer[],
    is_active boolean DEFAULT true,
    last_run_at timestamp with time zone,
    next_run_at timestamp with time zone,
    created_by integer,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE public.scheduled_reports_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.scheduled_reports_id_seq OWNED BY public.scheduled_reports.id;

CREATE TABLE public.schema_migrations (
    version character varying(255) NOT NULL,
    applied_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.scim_external_users (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    user_id integer,
    external_id text,
    scim_user_name text NOT NULL,
    raw_profile jsonb DEFAULT '{}'::jsonb NOT NULL,
    last_synced_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE public.scim_external_users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.scim_external_users_id_seq OWNED BY public.scim_external_users.id;

CREATE TABLE public.scim_group_memberships (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    group_id integer NOT NULL,
    user_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE public.scim_group_memberships_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.scim_group_memberships_id_seq OWNED BY public.scim_group_memberships.id;

CREATE TABLE public.scim_group_role_mappings (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    group_id integer NOT NULL,
    role public.user_role DEFAULT 'analyst'::public.user_role NOT NULL,
    enabled boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE public.scim_group_role_mappings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.scim_group_role_mappings_id_seq OWNED BY public.scim_group_role_mappings.id;

CREATE TABLE public.scim_groups (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    display_name text NOT NULL,
    external_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE public.scim_groups_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.scim_groups_id_seq OWNED BY public.scim_groups.id;

CREATE TABLE public.security_events (
    id bigint NOT NULL,
    tenant_id integer DEFAULT 1 NOT NULL,
    occurred_at timestamp with time zone DEFAULT now() NOT NULL,
    event_type text NOT NULL,
    severity text DEFAULT 'info'::text NOT NULL,
    category text DEFAULT 'threat'::text NOT NULL,
    actor_user_id integer,
    actor_email text,
    ip_address text,
    method text,
    path text,
    detail text,
    evidence jsonb DEFAULT '{}'::jsonb NOT NULL,
    request_id text,
    CONSTRAINT security_events_severity_check CHECK ((severity = ANY (ARRAY['critical'::text, 'high'::text, 'medium'::text, 'low'::text, 'info'::text])))
);

ALTER TABLE ONLY public.security_events FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.security_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.security_events_id_seq OWNED BY public.security_events.id;

CREATE TABLE public.shrinkage_records (
    id integer NOT NULL,
    store_id integer NOT NULL,
    item_id integer NOT NULL,
    quantity integer NOT NULL,
    unit_cost numeric(10,2),
    total_loss numeric(12,2),
    reason public.shrinkage_reason NOT NULL,
    description text,
    investigated boolean DEFAULT false,
    investigation_notes text,
    investigated_by integer,
    reported_by integer NOT NULL,
    reported_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE public.shrinkage_records_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.shrinkage_records_id_seq OWNED BY public.shrinkage_records.id;

CREATE TABLE public.sso_auth_states (
    state_hash text NOT NULL,
    nonce_hash text NOT NULL,
    tenant_id integer NOT NULL,
    provider_id integer NOT NULL,
    redirect_uri text,
    return_to text,
    code_verifier_hash text,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    ip_address text,
    user_agent text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.stock_transfer_items (
    id integer NOT NULL,
    transfer_id integer NOT NULL,
    item_id integer NOT NULL,
    quantity_requested integer NOT NULL,
    quantity_sent integer,
    quantity_received integer,
    unit_cost numeric(10,2),
    notes text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE public.stock_transfer_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.stock_transfer_items_id_seq OWNED BY public.stock_transfer_items.id;

CREATE TABLE public.stock_transfers (
    id integer NOT NULL,
    transfer_number character varying(50) NOT NULL,
    from_store_id integer NOT NULL,
    to_store_id integer NOT NULL,
    status public.transfer_status DEFAULT 'pending'::public.transfer_status,
    requested_by integer NOT NULL,
    requested_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    approved_by integer,
    approved_at timestamp with time zone,
    completed_by integer,
    completed_at timestamp with time zone,
    reason text,
    notes text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT different_stores CHECK ((from_store_id <> to_store_id))
);

CREATE SEQUENCE public.stock_transfers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.stock_transfers_id_seq OWNED BY public.stock_transfers.id;

CREATE VIEW public.store_employee_performance_view AS
 SELECT s.id AS store_id,
    s.name AS store_name,
    e.role,
    count(DISTINCT e.id) AS employee_count,
    round(avg(ep.performance_score), 2) AS avg_performance,
    round(sum(ep.sales_achieved), 2) AS total_sales,
    sum(ep.transactions_count) AS total_transactions
   FROM ((public.stores s
     LEFT JOIN public.employees e ON (((s.id = e.store_id) AND (e.status = 'active'::public.employee_status))))
     LEFT JOIN public.employee_performance ep ON (((e.id = ep.employee_id) AND (ep.period_end >= (CURRENT_DATE - '30 days'::interval)))))
  GROUP BY s.id, s.name, e.role
  ORDER BY s.id, e.role;

CREATE SEQUENCE public.stores_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.stores_id_seq OWNED BY public.stores.id;

CREATE TABLE public.subscriptions (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    plan character varying(40) DEFAULT 'free'::character varying NOT NULL,
    status text DEFAULT 'trialing'::text NOT NULL,
    billing_provider text DEFAULT 'manual'::text NOT NULL,
    billing_cycle text DEFAULT 'monthly'::text NOT NULL,
    currency character(3) DEFAULT 'AED'::bpchar NOT NULL,
    current_period_start timestamp with time zone,
    current_period_end timestamp with time zone,
    trial_ends_at timestamp with time zone,
    external_customer_id character varying(120),
    external_subscription_id character varying(120),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT subscriptions_billing_cycle_check CHECK ((billing_cycle = ANY (ARRAY['monthly'::text, 'annual'::text]))),
    CONSTRAINT subscriptions_billing_provider_check CHECK ((billing_provider = ANY (ARRAY['manual'::text, 'bank_transfer'::text, 'purchase_order'::text, 'stripe'::text, 'telr'::text, 'paytabs'::text, 'network'::text, 'checkout'::text]))),
    CONSTRAINT subscriptions_status_check CHECK ((status = ANY (ARRAY['trialing'::text, 'active'::text, 'past_due'::text, 'cancelled'::text, 'manual'::text])))
);

CREATE SEQUENCE public.subscriptions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.subscriptions_id_seq OWNED BY public.subscriptions.id;

CREATE TABLE public.supplier_invoice_lines (
    id integer NOT NULL,
    invoice_id integer NOT NULL,
    item_id integer NOT NULL,
    quantity integer NOT NULL,
    unit_cost numeric(12,2) DEFAULT 0 NOT NULL,
    line_total numeric(14,2) DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE ONLY public.supplier_invoice_lines FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.supplier_invoice_lines_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.supplier_invoice_lines_id_seq OWNED BY public.supplier_invoice_lines.id;

CREATE TABLE public.supplier_invoices (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    po_id integer NOT NULL,
    supplier_id integer NOT NULL,
    invoice_number character varying(60) NOT NULL,
    invoice_amount numeric(14,2) DEFAULT 0 NOT NULL,
    currency character varying(8) DEFAULT 'AED'::character varying NOT NULL,
    status character varying(24) DEFAULT 'received'::character varying NOT NULL,
    match_status character varying(16),
    notes text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE ONLY public.supplier_invoices FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.supplier_invoices_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.supplier_invoices_id_seq OWNED BY public.supplier_invoices.id;

CREATE SEQUENCE public.suppliers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.suppliers_id_seq OWNED BY public.suppliers.id;

CREATE TABLE public.tenant_admin_notes (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    note text NOT NULL,
    author_id integer,
    author_email text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE SEQUENCE public.tenant_admin_notes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.tenant_admin_notes_id_seq OWNED BY public.tenant_admin_notes.id;

CREATE TABLE public.tenant_api_keys (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    name character varying(120) NOT NULL,
    key_prefix character varying(20) NOT NULL,
    key_hash character varying(64) NOT NULL,
    scopes text[] DEFAULT ARRAY['read'::text] NOT NULL,
    created_by integer,
    last_used_at timestamp with time zone,
    request_count bigint DEFAULT 0 NOT NULL,
    revoked_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    expires_at timestamp with time zone
);

ALTER TABLE ONLY public.tenant_api_keys FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.tenant_api_keys_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.tenant_api_keys_id_seq OWNED BY public.tenant_api_keys.id;

CREATE TABLE public.tenant_billing_profile (
    tenant_id integer NOT NULL,
    legal_name text,
    legal_name_ar text,
    trading_name text,
    trn character varying(15),
    trade_license_no text,
    emirate text,
    jurisdiction text,
    free_zone_name text,
    vat_registered boolean DEFAULT true NOT NULL,
    registered_address text,
    billing_address text,
    currency character(3) DEFAULT 'AED'::bpchar NOT NULL,
    timezone text DEFAULT 'Asia/Dubai'::text NOT NULL,
    preferred_language character varying(2) DEFAULT 'en'::character varying NOT NULL,
    industry_vertical text,
    store_count integer,
    sku_count integer,
    procurement_type text,
    billing_contact_name text,
    billing_contact_email text,
    billing_contact_phone text,
    finance_contact_name text,
    finance_contact_email text,
    finance_contact_phone text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT tenant_billing_profile_currency_check CHECK ((currency ~ '^[A-Z]{3}$'::text)),
    CONSTRAINT tenant_billing_profile_emirate_check CHECK (((emirate IS NULL) OR (emirate = ANY (ARRAY['abu_dhabi'::text, 'dubai'::text, 'sharjah'::text, 'ajman'::text, 'umm_al_quwain'::text, 'ras_al_khaimah'::text, 'fujairah'::text])))),
    CONSTRAINT tenant_billing_profile_jurisdiction_check CHECK (((jurisdiction IS NULL) OR (jurisdiction = ANY (ARRAY['mainland'::text, 'free_zone'::text])))),
    CONSTRAINT tenant_billing_profile_preferred_language_check CHECK (((preferred_language)::text = ANY ((ARRAY['en'::character varying, 'ar'::character varying])::text[]))),
    CONSTRAINT tenant_billing_profile_sku_count_check CHECK (((sku_count IS NULL) OR (sku_count >= 0))),
    CONSTRAINT tenant_billing_profile_store_count_check CHECK (((store_count IS NULL) OR (store_count >= 0)))
);

CREATE TABLE public.tenant_operations_policies (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    policy jsonb DEFAULT '{}'::jsonb NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    updated_by text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.tenant_operations_policies FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.tenant_operations_policies_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.tenant_operations_policies_id_seq OWNED BY public.tenant_operations_policies.id;

CREATE TABLE public.tenant_provisioning (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    tier text NOT NULL,
    status text DEFAULT 'requested'::text NOT NULL,
    schema_name text,
    db_ref text,
    error text,
    requested_by text,
    requested_at timestamp with time zone DEFAULT now() NOT NULL,
    activated_at timestamp with time zone,
    deprovisioned_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT tenant_provisioning_active_has_target CHECK (((status <> 'active'::text) OR (tier = 'shared'::text) OR ((tier = 'dedicated_schema'::text) AND (schema_name IS NOT NULL)) OR ((tier = 'dedicated_db'::text) AND (db_ref IS NOT NULL)))),
    CONSTRAINT tenant_provisioning_failure_has_reason CHECK (((status <> 'failed'::text) OR ((error IS NOT NULL) AND (length(btrim(error)) > 0)))),
    CONSTRAINT tenant_provisioning_status_check CHECK ((status = ANY (ARRAY['requested'::text, 'provisioning'::text, 'active'::text, 'failed'::text, 'deprovisioning'::text, 'deprovisioned'::text]))),
    CONSTRAINT tenant_provisioning_tier_check CHECK ((tier = ANY (ARRAY['shared'::text, 'dedicated_schema'::text, 'dedicated_db'::text])))
);

CREATE SEQUENCE public.tenant_provisioning_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.tenant_provisioning_id_seq OWNED BY public.tenant_provisioning.id;

CREATE TABLE public.tenant_scim_tokens (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    name text NOT NULL,
    token_hash text NOT NULL,
    token_prefix text,
    scopes text DEFAULT 'scim:read scim:write'::text NOT NULL,
    created_by_user_id integer,
    rotated_from_token_id integer,
    last_used_at timestamp with time zone,
    expires_at timestamp with time zone,
    revoked_at timestamp with time zone,
    revoked_by_user_id integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE public.tenant_scim_tokens_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.tenant_scim_tokens_id_seq OWNED BY public.tenant_scim_tokens.id;

CREATE TABLE public.tenant_sso_providers (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    provider_type text NOT NULL,
    name text NOT NULL,
    enabled boolean DEFAULT false NOT NULL,
    issuer text,
    authorization_endpoint text,
    token_endpoint text,
    jwks_uri text,
    client_id text,
    client_secret_env text,
    scopes text DEFAULT 'openid email profile'::text NOT NULL,
    allowed_domains jsonb DEFAULT '[]'::jsonb NOT NULL,
    jit_provisioning_enabled boolean DEFAULT false NOT NULL,
    default_role public.user_role DEFAULT 'analyst'::public.user_role NOT NULL,
    trust_idp_mfa boolean DEFAULT false NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT tenant_sso_providers_provider_type_check CHECK ((provider_type = ANY (ARRAY['oidc'::text, 'saml'::text, 'workos_saml'::text])))
);

CREATE SEQUENCE public.tenant_sso_providers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.tenant_sso_providers_id_seq OWNED BY public.tenant_sso_providers.id;

CREATE TABLE public.tenant_status_events (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    from_status text,
    to_status text NOT NULL,
    reason text,
    changed_by integer,
    changed_email text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE SEQUENCE public.tenant_status_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.tenant_status_events_id_seq OWNED BY public.tenant_status_events.id;

CREATE TABLE public.tenant_webhooks (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    url text NOT NULL,
    secret character varying(80) NOT NULL,
    events text[] DEFAULT ARRAY['*'::text] NOT NULL,
    description character varying(200),
    active boolean DEFAULT true NOT NULL,
    created_by integer,
    last_delivery_at timestamp with time zone,
    last_status integer,
    failure_count integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE ONLY public.tenant_webhooks FORCE ROW LEVEL SECURITY;

CREATE SEQUENCE public.tenant_webhooks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.tenant_webhooks_id_seq OWNED BY public.tenant_webhooks.id;

CREATE TABLE public.tenants (
    id integer NOT NULL,
    slug character varying(63) NOT NULL,
    name character varying(200) NOT NULL,
    plan character varying(40) DEFAULT 'free'::character varying NOT NULL,
    status character varying(20) DEFAULT 'active'::character varying NOT NULL,
    brand_name character varying(200),
    logo_url text,
    accent_color character varying(20),
    stripe_customer_id character varying(120),
    stripe_subscription_id character varying(120),
    trial_ends_at timestamp with time zone,
    settings jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    status_reason text,
    status_changed_at timestamp with time zone,
    status_changed_by integer,
    isolation_tier text DEFAULT 'shared'::text NOT NULL,
    CONSTRAINT tenants_isolation_tier_check CHECK ((isolation_tier = ANY (ARRAY['shared'::text, 'dedicated_schema'::text, 'dedicated_db'::text]))),
    CONSTRAINT tenants_status_check CHECK (((status)::text = ANY ((ARRAY['trial'::character varying, 'onboarding'::character varying, 'active'::character varying, 'payment_pending'::character varying, 'past_due'::character varying, 'suspended'::character varying, 'cancelled'::character varying, 'deletion_requested'::character varying, 'deleted'::character varying])::text[])))
);

COMMENT ON COLUMN public.tenants.isolation_tier IS 'Isolation the tenant was sold. Only ''shared'' is implemented; the app refuses to serve a tenant on any other tier rather than silently downgrade them.';

CREATE SEQUENCE public.tenants_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.tenants_id_seq OWNED BY public.tenants.id;

CREATE TABLE public.transaction_lines (
    id bigint NOT NULL,
    transaction_id bigint NOT NULL,
    line_no integer NOT NULL,
    item_id integer NOT NULL,
    qty numeric(10,3) NOT NULL,
    unit_price_aed numeric(10,2) NOT NULL,
    discount_aed numeric(10,2) DEFAULT 0 NOT NULL,
    line_total_aed numeric(12,2) NOT NULL,
    CONSTRAINT ck_transaction_lines_total CHECK ((abs((line_total_aed - ((qty * unit_price_aed) - discount_aed))) <= 0.01))
);

ALTER TABLE ONLY public.transaction_lines FORCE ROW LEVEL SECURITY;

COMMENT ON TABLE public.transaction_lines IS 'E2-5 basket grain (lines). qty is UNITS (negative = return); *_aed columns are money. No tenant_id: scoped through its parent transaction, matching the house pattern used by purchase_order_lines / goods_receipt_lines / supplier_invoice_lines (migration 020).';

CREATE SEQUENCE public.transaction_lines_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.transaction_lines_id_seq OWNED BY public.transaction_lines.id;

CREATE TABLE public.transactions (
    id bigint NOT NULL,
    tenant_id integer DEFAULT 1 NOT NULL,
    store_id integer NOT NULL,
    txn_time timestamp with time zone NOT NULL,
    txn_date date NOT NULL,
    source character varying(40) DEFAULT 'pos'::character varying NOT NULL,
    txn_ref character varying(120) NOT NULL,
    register_id character varying(40),
    cashier_employee_id integer,
    customer_ref character varying(80),
    payment_method character varying(30),
    status character varying(20) DEFAULT 'completed'::character varying NOT NULL,
    total_aed numeric(12,2) DEFAULT 0 NOT NULL,
    discount_total_aed numeric(12,2) DEFAULT 0 NOT NULL,
    tax_total_aed numeric(12,2),
    is_synthetic boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT transactions_status_check CHECK (((status)::text = ANY ((ARRAY['completed'::character varying, 'voided'::character varying, 'refunded'::character varying])::text[])))
);

ALTER TABLE ONLY public.transactions FORCE ROW LEVEL SECURITY;

COMMENT ON TABLE public.transactions IS 'E2-5 basket grain (header). Created unfilled; the POS connector (E2-1) writes here where the source supports line detail. Revenue stays sourced from the DAILY grain (sales_fact_view / sales_rollup_daily) — this is a parallel grain, never UNIONed in, or a connected POS would double-count. See ADR-010. Unrelated to inventory_transactions, employee_transactions and basket_associations.';

COMMENT ON COLUMN public.transactions.txn_date IS 'Store-local calendar day of txn_time. A plain column because timestamptz::date is not IMMUTABLE and so cannot be a generated/indexed expression.';

COMMENT ON COLUMN public.transactions.customer_ref IS 'Opaque loyalty/customer identifier from the POS. Never store PII here.';

CREATE SEQUENCE public.transactions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.transactions_id_seq OWNED BY public.transactions.id;

CREATE TABLE public.usage_events (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    event_type text NOT NULL,
    quantity integer DEFAULT 1 NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT usage_events_quantity_check CHECK ((quantity >= 0))
);

CREATE SEQUENCE public.usage_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.usage_events_id_seq OWNED BY public.usage_events.id;

CREATE TABLE public.user_feedback (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    user_id integer,
    kind text NOT NULL,
    score smallint,
    comment text,
    page text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT user_feedback_kind_check CHECK ((kind = ANY (ARRAY['nps'::text, 'feedback'::text]))),
    CONSTRAINT user_feedback_payload_check CHECK ((((kind = 'nps'::text) AND (score IS NOT NULL)) OR ((kind = 'feedback'::text) AND (comment IS NOT NULL)))),
    CONSTRAINT user_feedback_score_check CHECK (((score >= 0) AND (score <= 10)))
);

CREATE SEQUENCE public.user_feedback_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.user_feedback_id_seq OWNED BY public.user_feedback.id;

CREATE TABLE public.user_permissions (
    id integer NOT NULL,
    user_id integer NOT NULL,
    region_id integer,
    store_id integer,
    can_view boolean DEFAULT true,
    can_edit boolean DEFAULT false,
    can_delete boolean DEFAULT false,
    can_export boolean DEFAULT false,
    can_manage_users boolean DEFAULT false,
    can_manage_inventory boolean DEFAULT false,
    can_manage_promotions boolean DEFAULT false,
    can_view_financials boolean DEFAULT false,
    can_approve_transfers boolean DEFAULT false,
    valid_from date DEFAULT CURRENT_DATE,
    valid_until date,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE public.user_permissions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.user_permissions_id_seq OWNED BY public.user_permissions.id;

CREATE TABLE public.user_sessions (
    id integer NOT NULL,
    user_id integer NOT NULL,
    session_token character varying(500) NOT NULL,
    refresh_token character varying(500),
    ip_address character varying(45),
    user_agent text,
    device_type character varying(50),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    expires_at timestamp with time zone NOT NULL,
    last_activity_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    revoked_at timestamp with time zone,
    is_active boolean DEFAULT true
);

CREATE SEQUENCE public.user_sessions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.user_sessions_id_seq OWNED BY public.user_sessions.id;

CREATE TABLE public.users (
    id integer NOT NULL,
    email character varying(255) NOT NULL,
    password_hash character varying(255) NOT NULL,
    first_name character varying(100) NOT NULL,
    last_name character varying(100) NOT NULL,
    role public.user_role DEFAULT 'analyst'::public.user_role NOT NULL,
    status public.user_status DEFAULT 'active'::public.user_status NOT NULL,
    phone character varying(20),
    job_title character varying(100),
    department character varying(100),
    failed_login_attempts integer DEFAULT 0,
    locked_until timestamp with time zone,
    password_changed_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    must_change_password boolean DEFAULT false,
    two_factor_enabled boolean DEFAULT false,
    two_factor_secret character varying(100),
    last_login_at timestamp with time zone,
    last_login_ip character varying(45),
    last_activity_at timestamp with time zone,
    preferences jsonb DEFAULT '{}'::jsonb,
    notification_settings jsonb DEFAULT '{"sms": false, "email": true, "in_app": true}'::jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    tenant_id integer DEFAULT 1 NOT NULL,
    two_factor_backup_codes jsonb DEFAULT '[]'::jsonb NOT NULL,
    email_verified boolean DEFAULT true NOT NULL,
    is_platform_developer boolean DEFAULT false NOT NULL
);

ALTER TABLE ONLY public.users FORCE ROW LEVEL SECURITY;

COMMENT ON COLUMN public.users.is_platform_developer IS 'Platform-operator boundary (Platform Console). TRUE only for the vendor''s own developers — never for tenant admins. Checked by services/platform_access.py, which may additionally require membership in the PLATFORM_DEVELOPER_EMAILS allowlist. A tenant super_admin does NOT imply this.';

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;

CREATE TABLE public.value_realizations (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    finding_id integer NOT NULL,
    estimated_value_aed numeric(12,2),
    confirmed_value_aed numeric(12,2),
    method text,
    status text DEFAULT 'pending'::text NOT NULL,
    note text,
    confirmed_by text,
    confirmed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    dispute_reason text,
    disputed_at timestamp with time zone,
    disputed_by text,
    CONSTRAINT value_realizations_dispute_keeps_amount CHECK (((status <> 'disputed'::text) OR (confirmed_value_aed IS NOT NULL))),
    CONSTRAINT value_realizations_dispute_needs_reason CHECK (((status <> 'disputed'::text) OR ((dispute_reason IS NOT NULL) AND (length(btrim(dispute_reason)) > 0)))),
    CONSTRAINT value_realizations_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'confirmed'::text, 'dismissed'::text, 'disputed'::text])))
);

CREATE SEQUENCE public.value_realizations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.value_realizations_id_seq OWNED BY public.value_realizations.id;

CREATE TABLE public.webhook_deliveries (
    id bigint NOT NULL,
    tenant_id integer NOT NULL,
    webhook_id bigint NOT NULL,
    event text NOT NULL,
    status_code integer,
    ok boolean DEFAULT false NOT NULL,
    error text,
    delivered_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE public.webhook_deliveries_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.webhook_deliveries_id_seq OWNED BY public.webhook_deliveries.id;

ALTER TABLE ONLY public.sales_stream_raw ATTACH PARTITION public.sales_stream_raw_2026_08 FOR VALUES FROM ('2026-08-01 00:00:00+00') TO ('2026-09-01 00:00:00+00');

ALTER TABLE ONLY public.sales_stream_raw ATTACH PARTITION public.sales_stream_raw_2026_09 FOR VALUES FROM ('2026-09-01 00:00:00+00') TO ('2026-10-01 00:00:00+00');

ALTER TABLE ONLY public.sales_stream_raw ATTACH PARTITION public.sales_stream_raw_2026_10 FOR VALUES FROM ('2026-10-01 00:00:00+00') TO ('2026-11-01 00:00:00+00');

ALTER TABLE ONLY public.sales_stream_raw ATTACH PARTITION public.sales_stream_raw_2026_11 FOR VALUES FROM ('2026-11-01 00:00:00+00') TO ('2026-12-01 00:00:00+00');

ALTER TABLE ONLY public.sales_stream_raw ATTACH PARTITION public.sales_stream_raw_default DEFAULT;

ALTER TABLE ONLY public.action_drafts ALTER COLUMN id SET DEFAULT nextval('public.action_drafts_id_seq'::regclass);

ALTER TABLE ONLY public.alert_notifications ALTER COLUMN id SET DEFAULT nextval('public.alert_notifications_id_seq'::regclass);

ALTER TABLE ONLY public.alert_rules ALTER COLUMN id SET DEFAULT nextval('public.alert_rules_id_seq'::regclass);

ALTER TABLE ONLY public.alerts ALTER COLUMN id SET DEFAULT nextval('public.alerts_id_seq'::regclass);

ALTER TABLE ONLY public.approval_rules ALTER COLUMN id SET DEFAULT nextval('public.approval_rules_id_seq'::regclass);

ALTER TABLE ONLY public.audit_log ALTER COLUMN id SET DEFAULT nextval('public.audit_log_id_seq'::regclass);

ALTER TABLE ONLY public.auth_tokens ALTER COLUMN id SET DEFAULT nextval('public.auth_tokens_id_seq'::regclass);

ALTER TABLE ONLY public.basket_associations ALTER COLUMN id SET DEFAULT nextval('public.basket_associations_id_seq'::regclass);

ALTER TABLE ONLY public.bespoke_requests ALTER COLUMN id SET DEFAULT nextval('public.bespoke_requests_id_seq'::regclass);

ALTER TABLE ONLY public.campaign_allocations ALTER COLUMN id SET DEFAULT nextval('public.campaign_allocations_id_seq'::regclass);

ALTER TABLE ONLY public.campaign_offers ALTER COLUMN id SET DEFAULT nextval('public.campaign_offers_id_seq'::regclass);

ALTER TABLE ONLY public.company_targets ALTER COLUMN id SET DEFAULT nextval('public.company_targets_id_seq'::regclass);

ALTER TABLE ONLY public.competitor_prices ALTER COLUMN id SET DEFAULT nextval('public.competitor_prices_id_seq'::regclass);

ALTER TABLE ONLY public.crm_opportunities ALTER COLUMN id SET DEFAULT nextval('public.crm_opportunities_id_seq'::regclass);

ALTER TABLE ONLY public.customer_purchases ALTER COLUMN id SET DEFAULT nextval('public.customer_purchases_id_seq'::regclass);

ALTER TABLE ONLY public.customers ALTER COLUMN id SET DEFAULT nextval('public.customers_id_seq'::regclass);

ALTER TABLE ONLY public.data_requests ALTER COLUMN id SET DEFAULT nextval('public.data_requests_id_seq'::regclass);

ALTER TABLE ONLY public.data_sources ALTER COLUMN id SET DEFAULT nextval('public.data_sources_id_seq'::regclass);

ALTER TABLE ONLY public.distributors ALTER COLUMN id SET DEFAULT nextval('public.distributors_id_seq'::regclass);

ALTER TABLE ONLY public.documents ALTER COLUMN id SET DEFAULT nextval('public.documents_id_seq'::regclass);

ALTER TABLE ONLY public.einvoice_submissions ALTER COLUMN id SET DEFAULT nextval('public.einvoice_submissions_id_seq'::regclass);

ALTER TABLE ONLY public.employee_attendance ALTER COLUMN id SET DEFAULT nextval('public.employee_attendance_id_seq'::regclass);

ALTER TABLE ONLY public.employee_certifications ALTER COLUMN id SET DEFAULT nextval('public.employee_certifications_id_seq'::regclass);

ALTER TABLE ONLY public.employee_performance ALTER COLUMN id SET DEFAULT nextval('public.employee_performance_id_seq'::regclass);

ALTER TABLE ONLY public.employee_transactions ALTER COLUMN id SET DEFAULT nextval('public.employee_transactions_id_seq'::regclass);

ALTER TABLE ONLY public.employees ALTER COLUMN id SET DEFAULT nextval('public.employees_id_seq'::regclass);

ALTER TABLE ONLY public.external_identities ALTER COLUMN id SET DEFAULT nextval('public.external_identities_id_seq'::regclass);

ALTER TABLE ONLY public.findings ALTER COLUMN id SET DEFAULT nextval('public.findings_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_allocation_lines ALTER COLUMN id SET DEFAULT nextval('public.flywheel_allocation_lines_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_allocation_runs ALTER COLUMN id SET DEFAULT nextval('public.flywheel_allocation_runs_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_approval_policies ALTER COLUMN id SET DEFAULT nextval('public.flywheel_approval_policies_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_approval_requests ALTER COLUMN id SET DEFAULT nextval('public.flywheel_approval_requests_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_approval_steps ALTER COLUMN id SET DEFAULT nextval('public.flywheel_approval_steps_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_budget_ledger ALTER COLUMN id SET DEFAULT nextval('public.flywheel_budget_ledger_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_budgets ALTER COLUMN id SET DEFAULT nextval('public.flywheel_budgets_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_campaign_audience ALTER COLUMN id SET DEFAULT nextval('public.flywheel_campaign_audience_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_campaign_outcomes ALTER COLUMN id SET DEFAULT nextval('public.flywheel_campaign_outcomes_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_campaign_transitions ALTER COLUMN id SET DEFAULT nextval('public.flywheel_campaign_transitions_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_campaigns ALTER COLUMN id SET DEFAULT nextval('public.flywheel_campaigns_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_cannibalization ALTER COLUMN id SET DEFAULT nextval('public.flywheel_cannibalization_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_churn_predictions ALTER COLUMN id SET DEFAULT nextval('public.flywheel_churn_predictions_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_coalition_activity ALTER COLUMN id SET DEFAULT nextval('public.flywheel_coalition_activity_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_coalition_attribution ALTER COLUMN id SET DEFAULT nextval('public.flywheel_coalition_attribution_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_coalition_partners ALTER COLUMN id SET DEFAULT nextval('public.flywheel_coalition_partners_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_contact_log ALTER COLUMN id SET DEFAULT nextval('public.flywheel_contact_log_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_contact_policy ALTER COLUMN id SET DEFAULT nextval('public.flywheel_contact_policy_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_customer_consents ALTER COLUMN id SET DEFAULT nextval('public.flywheel_customer_consents_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_customer_events ALTER COLUMN id SET DEFAULT nextval('public.flywheel_customer_events_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_customers ALTER COLUMN id SET DEFAULT nextval('public.flywheel_customers_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_decisions ALTER COLUMN id SET DEFAULT nextval('public.flywheel_decisions_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_delivery_receipts ALTER COLUMN id SET DEFAULT nextval('public.flywheel_delivery_receipts_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_feature_snapshots ALTER COLUMN id SET DEFAULT nextval('public.flywheel_feature_snapshots_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_holdout_balance ALTER COLUMN id SET DEFAULT nextval('public.flywheel_holdout_balance_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_identity_links ALTER COLUMN id SET DEFAULT nextval('public.flywheel_identity_links_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_inventory_allocations ALTER COLUMN id SET DEFAULT nextval('public.flywheel_inventory_allocations_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_jobs ALTER COLUMN id SET DEFAULT nextval('public.flywheel_jobs_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_model_versions ALTER COLUMN id SET DEFAULT nextval('public.flywheel_model_versions_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_offer_response_predictions ALTER COLUMN id SET DEFAULT nextval('public.flywheel_offer_response_predictions_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_offer_suppressions ALTER COLUMN id SET DEFAULT nextval('public.flywheel_offer_suppressions_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_offers ALTER COLUMN id SET DEFAULT nextval('public.flywheel_offers_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_outbox ALTER COLUMN id SET DEFAULT nextval('public.flywheel_outbox_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_outcome_pricing ALTER COLUMN id SET DEFAULT nextval('public.flywheel_outcome_pricing_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_pos_staging ALTER COLUMN id SET DEFAULT nextval('public.flywheel_pos_staging_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_preregistrations ALTER COLUMN id SET DEFAULT nextval('public.flywheel_preregistrations_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_procurement_requisitions ALTER COLUMN id SET DEFAULT nextval('public.flywheel_procurement_requisitions_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_profiling_objections ALTER COLUMN id SET DEFAULT nextval('public.flywheel_profiling_objections_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_promotion_criteria ALTER COLUMN id SET DEFAULT nextval('public.flywheel_promotion_criteria_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_purchase_attributions ALTER COLUMN id SET DEFAULT nextval('public.flywheel_purchase_attributions_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_readouts ALTER COLUMN id SET DEFAULT nextval('public.flywheel_readouts_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_redemptions ALTER COLUMN id SET DEFAULT nextval('public.flywheel_redemptions_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_returns ALTER COLUMN id SET DEFAULT nextval('public.flywheel_returns_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_seasonality_calendar ALTER COLUMN id SET DEFAULT nextval('public.flywheel_seasonality_calendar_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_settlements ALTER COLUMN id SET DEFAULT nextval('public.flywheel_settlements_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_shadow_decisions ALTER COLUMN id SET DEFAULT nextval('public.flywheel_shadow_decisions_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_shelf_life ALTER COLUMN id SET DEFAULT nextval('public.flywheel_shelf_life_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_substitution ALTER COLUMN id SET DEFAULT nextval('public.flywheel_substitution_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_supplier_funding ALTER COLUMN id SET DEFAULT nextval('public.flywheel_supplier_funding_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_supplier_funding_skus ALTER COLUMN id SET DEFAULT nextval('public.flywheel_supplier_funding_skus_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_tax_rules ALTER COLUMN id SET DEFAULT nextval('public.flywheel_tax_rules_id_seq'::regclass);

ALTER TABLE ONLY public.flywheel_transfer_recommendations ALTER COLUMN id SET DEFAULT nextval('public.flywheel_transfer_recommendations_id_seq'::regclass);

ALTER TABLE ONLY public.goods_receipt_lines ALTER COLUMN id SET DEFAULT nextval('public.goods_receipt_lines_id_seq'::regclass);

ALTER TABLE ONLY public.goods_receipts ALTER COLUMN id SET DEFAULT nextval('public.goods_receipts_id_seq'::regclass);

ALTER TABLE ONLY public.import_jobs ALTER COLUMN id SET DEFAULT nextval('public.import_jobs_id_seq'::regclass);

ALTER TABLE ONLY public.import_row_undo ALTER COLUMN id SET DEFAULT nextval('public.import_row_undo_id_seq'::regclass);

ALTER TABLE ONLY public.import_schedules ALTER COLUMN id SET DEFAULT nextval('public.import_schedules_id_seq'::regclass);

ALTER TABLE ONLY public.ingest_ledger ALTER COLUMN id SET DEFAULT nextval('public.ingest_ledger_id_seq'::regclass);

ALTER TABLE ONLY public.inventory ALTER COLUMN id SET DEFAULT nextval('public.inventory_id_seq'::regclass);

ALTER TABLE ONLY public.inventory_batches ALTER COLUMN id SET DEFAULT nextval('public.inventory_batches_id_seq'::regclass);

ALTER TABLE ONLY public.inventory_transactions ALTER COLUMN id SET DEFAULT nextval('public.inventory_transactions_id_seq'::regclass);

ALTER TABLE ONLY public.invoice_lines ALTER COLUMN id SET DEFAULT nextval('public.invoice_lines_id_seq'::regclass);

ALTER TABLE ONLY public.invoices ALTER COLUMN id SET DEFAULT nextval('public.invoices_id_seq'::regclass);

ALTER TABLE ONLY public.item_costs ALTER COLUMN id SET DEFAULT nextval('public.item_costs_id_seq'::regclass);

ALTER TABLE ONLY public.items ALTER COLUMN id SET DEFAULT nextval('public.items_id_seq'::regclass);

ALTER TABLE ONLY public.notifications ALTER COLUMN id SET DEFAULT nextval('public.notifications_id_seq'::regclass);

ALTER TABLE ONLY public.online_prices ALTER COLUMN id SET DEFAULT nextval('public.online_prices_id_seq'::regclass);

ALTER TABLE ONLY public.operations_events ALTER COLUMN id SET DEFAULT nextval('public.operations_events_id_seq'::regclass);

ALTER TABLE ONLY public.operations_proposals ALTER COLUMN id SET DEFAULT nextval('public.operations_proposals_id_seq'::regclass);

ALTER TABLE ONLY public.operations_runs ALTER COLUMN id SET DEFAULT nextval('public.operations_runs_id_seq'::regclass);

ALTER TABLE ONLY public.password_reset_tokens ALTER COLUMN id SET DEFAULT nextval('public.password_reset_tokens_id_seq'::regclass);

ALTER TABLE ONLY public.payment_intents ALTER COLUMN id SET DEFAULT nextval('public.payment_intents_id_seq'::regclass);

ALTER TABLE ONLY public.payment_webhook_events ALTER COLUMN id SET DEFAULT nextval('public.payment_webhook_events_id_seq'::regclass);

ALTER TABLE ONLY public.pos_connections ALTER COLUMN id SET DEFAULT nextval('public.pos_connections_id_seq'::regclass);

ALTER TABLE ONLY public.pos_sync_runs ALTER COLUMN id SET DEFAULT nextval('public.pos_sync_runs_id_seq'::regclass);

ALTER TABLE ONLY public.predictions ALTER COLUMN id SET DEFAULT nextval('public.predictions_id_seq'::regclass);

ALTER TABLE ONLY public.procurement_events ALTER COLUMN id SET DEFAULT nextval('public.procurement_events_id_seq'::regclass);

ALTER TABLE ONLY public.product_suppliers ALTER COLUMN id SET DEFAULT nextval('public.product_suppliers_id_seq'::regclass);

ALTER TABLE ONLY public.promotion_items ALTER COLUMN id SET DEFAULT nextval('public.promotion_items_id_seq'::regclass);

ALTER TABLE ONLY public.promotion_stores ALTER COLUMN id SET DEFAULT nextval('public.promotion_stores_id_seq'::regclass);

ALTER TABLE ONLY public.promotions ALTER COLUMN id SET DEFAULT nextval('public.promotions_id_seq'::regclass);

ALTER TABLE ONLY public.purchase_order_lines ALTER COLUMN id SET DEFAULT nextval('public.purchase_order_lines_id_seq'::regclass);

ALTER TABLE ONLY public.purchase_orders ALTER COLUMN id SET DEFAULT nextval('public.purchase_orders_id_seq'::regclass);

ALTER TABLE ONLY public.regions ALTER COLUMN id SET DEFAULT nextval('public.regions_id_seq'::regclass);

ALTER TABLE ONLY public.report_history ALTER COLUMN id SET DEFAULT nextval('public.report_history_id_seq'::regclass);

ALTER TABLE ONLY public.retention_budget_ledger ALTER COLUMN id SET DEFAULT nextval('public.retention_budget_ledger_id_seq'::regclass);

ALTER TABLE ONLY public.retention_campaigns ALTER COLUMN id SET DEFAULT nextval('public.retention_campaigns_id_seq'::regclass);

ALTER TABLE ONLY public.retention_events ALTER COLUMN id SET DEFAULT nextval('public.retention_events_id_seq'::regclass);

ALTER TABLE ONLY public.sales_historical ALTER COLUMN id SET DEFAULT nextval('public.sales_historical_id_seq'::regclass);

ALTER TABLE ONLY public.sales_stream_raw ALTER COLUMN id SET DEFAULT nextval('public.sales_stream_raw_id_seq'::regclass);

ALTER TABLE ONLY public.scheduled_reports ALTER COLUMN id SET DEFAULT nextval('public.scheduled_reports_id_seq'::regclass);

ALTER TABLE ONLY public.scim_external_users ALTER COLUMN id SET DEFAULT nextval('public.scim_external_users_id_seq'::regclass);

ALTER TABLE ONLY public.scim_group_memberships ALTER COLUMN id SET DEFAULT nextval('public.scim_group_memberships_id_seq'::regclass);

ALTER TABLE ONLY public.scim_group_role_mappings ALTER COLUMN id SET DEFAULT nextval('public.scim_group_role_mappings_id_seq'::regclass);

ALTER TABLE ONLY public.scim_groups ALTER COLUMN id SET DEFAULT nextval('public.scim_groups_id_seq'::regclass);

ALTER TABLE ONLY public.security_events ALTER COLUMN id SET DEFAULT nextval('public.security_events_id_seq'::regclass);

ALTER TABLE ONLY public.shrinkage_records ALTER COLUMN id SET DEFAULT nextval('public.shrinkage_records_id_seq'::regclass);

ALTER TABLE ONLY public.stock_transfer_items ALTER COLUMN id SET DEFAULT nextval('public.stock_transfer_items_id_seq'::regclass);

ALTER TABLE ONLY public.stock_transfers ALTER COLUMN id SET DEFAULT nextval('public.stock_transfers_id_seq'::regclass);

ALTER TABLE ONLY public.stores ALTER COLUMN id SET DEFAULT nextval('public.stores_id_seq'::regclass);

ALTER TABLE ONLY public.subscriptions ALTER COLUMN id SET DEFAULT nextval('public.subscriptions_id_seq'::regclass);

ALTER TABLE ONLY public.supplier_invoice_lines ALTER COLUMN id SET DEFAULT nextval('public.supplier_invoice_lines_id_seq'::regclass);

ALTER TABLE ONLY public.supplier_invoices ALTER COLUMN id SET DEFAULT nextval('public.supplier_invoices_id_seq'::regclass);

ALTER TABLE ONLY public.suppliers ALTER COLUMN id SET DEFAULT nextval('public.suppliers_id_seq'::regclass);

ALTER TABLE ONLY public.tenant_admin_notes ALTER COLUMN id SET DEFAULT nextval('public.tenant_admin_notes_id_seq'::regclass);

ALTER TABLE ONLY public.tenant_api_keys ALTER COLUMN id SET DEFAULT nextval('public.tenant_api_keys_id_seq'::regclass);

ALTER TABLE ONLY public.tenant_operations_policies ALTER COLUMN id SET DEFAULT nextval('public.tenant_operations_policies_id_seq'::regclass);

ALTER TABLE ONLY public.tenant_provisioning ALTER COLUMN id SET DEFAULT nextval('public.tenant_provisioning_id_seq'::regclass);

ALTER TABLE ONLY public.tenant_scim_tokens ALTER COLUMN id SET DEFAULT nextval('public.tenant_scim_tokens_id_seq'::regclass);

ALTER TABLE ONLY public.tenant_sso_providers ALTER COLUMN id SET DEFAULT nextval('public.tenant_sso_providers_id_seq'::regclass);

ALTER TABLE ONLY public.tenant_status_events ALTER COLUMN id SET DEFAULT nextval('public.tenant_status_events_id_seq'::regclass);

ALTER TABLE ONLY public.tenant_webhooks ALTER COLUMN id SET DEFAULT nextval('public.tenant_webhooks_id_seq'::regclass);

ALTER TABLE ONLY public.tenants ALTER COLUMN id SET DEFAULT nextval('public.tenants_id_seq'::regclass);

ALTER TABLE ONLY public.transaction_lines ALTER COLUMN id SET DEFAULT nextval('public.transaction_lines_id_seq'::regclass);

ALTER TABLE ONLY public.transactions ALTER COLUMN id SET DEFAULT nextval('public.transactions_id_seq'::regclass);

ALTER TABLE ONLY public.usage_events ALTER COLUMN id SET DEFAULT nextval('public.usage_events_id_seq'::regclass);

ALTER TABLE ONLY public.user_feedback ALTER COLUMN id SET DEFAULT nextval('public.user_feedback_id_seq'::regclass);

ALTER TABLE ONLY public.user_permissions ALTER COLUMN id SET DEFAULT nextval('public.user_permissions_id_seq'::regclass);

ALTER TABLE ONLY public.user_sessions ALTER COLUMN id SET DEFAULT nextval('public.user_sessions_id_seq'::regclass);

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);

ALTER TABLE ONLY public.value_realizations ALTER COLUMN id SET DEFAULT nextval('public.value_realizations_id_seq'::regclass);

ALTER TABLE ONLY public.webhook_deliveries ALTER COLUMN id SET DEFAULT nextval('public.webhook_deliveries_id_seq'::regclass);

ALTER TABLE ONLY public.action_drafts
    ADD CONSTRAINT action_drafts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.alert_notifications
    ADD CONSTRAINT alert_notifications_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.alert_rules
    ADD CONSTRAINT alert_rules_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.approval_rules
    ADD CONSTRAINT approval_rules_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.approval_rules
    ADD CONSTRAINT approval_rules_tenant_id_key UNIQUE (tenant_id);

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.auth_tokens
    ADD CONSTRAINT auth_tokens_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.auth_tokens
    ADD CONSTRAINT auth_tokens_token_hash_key UNIQUE (token_hash);

ALTER TABLE ONLY public.basket_associations
    ADD CONSTRAINT basket_associations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.bespoke_requests
    ADD CONSTRAINT bespoke_requests_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.campaign_allocations
    ADD CONSTRAINT campaign_allocations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.campaign_offers
    ADD CONSTRAINT campaign_offers_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.company_targets
    ADD CONSTRAINT company_targets_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.competitor_prices
    ADD CONSTRAINT competitor_prices_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.crm_opportunities
    ADD CONSTRAINT crm_opportunities_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.customer_purchases
    ADD CONSTRAINT customer_purchases_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.customers
    ADD CONSTRAINT customers_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.data_requests
    ADD CONSTRAINT data_requests_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.data_sources
    ADD CONSTRAINT data_sources_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.distributors
    ADD CONSTRAINT distributors_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.einvoice_submissions
    ADD CONSTRAINT einvoice_submissions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.employee_attendance
    ADD CONSTRAINT employee_attendance_employee_id_attendance_date_key UNIQUE (employee_id, attendance_date);

ALTER TABLE ONLY public.employee_attendance
    ADD CONSTRAINT employee_attendance_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.employee_certifications
    ADD CONSTRAINT employee_certifications_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.employee_performance
    ADD CONSTRAINT employee_performance_employee_id_period_type_period_start_key UNIQUE (employee_id, period_type, period_start);

ALTER TABLE ONLY public.employee_performance
    ADD CONSTRAINT employee_performance_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.employee_transactions
    ADD CONSTRAINT employee_transactions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.employee_transactions
    ADD CONSTRAINT employee_transactions_transaction_code_key UNIQUE (transaction_code);

ALTER TABLE ONLY public.employees
    ADD CONSTRAINT employees_email_key UNIQUE (email);

ALTER TABLE ONLY public.employees
    ADD CONSTRAINT employees_employee_code_key UNIQUE (employee_code);

ALTER TABLE ONLY public.employees
    ADD CONSTRAINT employees_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.external_identities
    ADD CONSTRAINT external_identities_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.findings
    ADD CONSTRAINT findings_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.findings
    ADD CONSTRAINT findings_tenant_id_dedupe_key_key UNIQUE (tenant_id, dedupe_key);

ALTER TABLE ONLY public.flywheel_allocation_lines
    ADD CONSTRAINT flywheel_allocation_lines_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_allocation_runs
    ADD CONSTRAINT flywheel_allocation_runs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_approval_policies
    ADD CONSTRAINT flywheel_approval_policies_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_approval_requests
    ADD CONSTRAINT flywheel_approval_requests_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_approval_steps
    ADD CONSTRAINT flywheel_approval_steps_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_budget_ledger
    ADD CONSTRAINT flywheel_budget_ledger_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_budgets
    ADD CONSTRAINT flywheel_budgets_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_campaign_audience
    ADD CONSTRAINT flywheel_campaign_audience_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_campaign_outcomes
    ADD CONSTRAINT flywheel_campaign_outcomes_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_campaign_transitions
    ADD CONSTRAINT flywheel_campaign_transitions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_campaigns
    ADD CONSTRAINT flywheel_campaigns_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_cannibalization
    ADD CONSTRAINT flywheel_cannibalization_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_churn_predictions
    ADD CONSTRAINT flywheel_churn_predictions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_coalition_activity
    ADD CONSTRAINT flywheel_coalition_activity_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_coalition_attribution
    ADD CONSTRAINT flywheel_coalition_attribution_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_coalition_partners
    ADD CONSTRAINT flywheel_coalition_partners_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_contact_log
    ADD CONSTRAINT flywheel_contact_log_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_contact_policy
    ADD CONSTRAINT flywheel_contact_policy_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_customer_consents
    ADD CONSTRAINT flywheel_customer_consents_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_customer_events
    ADD CONSTRAINT flywheel_customer_events_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_customers
    ADD CONSTRAINT flywheel_customers_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_decisions
    ADD CONSTRAINT flywheel_decisions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_delivery_receipts
    ADD CONSTRAINT flywheel_delivery_receipts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_feature_snapshots
    ADD CONSTRAINT flywheel_feature_snapshots_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_holdout_balance
    ADD CONSTRAINT flywheel_holdout_balance_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_identity_links
    ADD CONSTRAINT flywheel_identity_links_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_inventory_allocations
    ADD CONSTRAINT flywheel_inventory_allocations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_jobs
    ADD CONSTRAINT flywheel_jobs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_model_versions
    ADD CONSTRAINT flywheel_model_versions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_offer_response_predictions
    ADD CONSTRAINT flywheel_offer_response_predictions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_offer_suppressions
    ADD CONSTRAINT flywheel_offer_suppressions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_offers
    ADD CONSTRAINT flywheel_offers_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_outbox
    ADD CONSTRAINT flywheel_outbox_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_outcome_pricing
    ADD CONSTRAINT flywheel_outcome_pricing_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_pos_staging
    ADD CONSTRAINT flywheel_pos_staging_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_preregistrations
    ADD CONSTRAINT flywheel_preregistrations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_procurement_requisitions
    ADD CONSTRAINT flywheel_procurement_requisitions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_profiling_objections
    ADD CONSTRAINT flywheel_profiling_objections_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_promotion_criteria
    ADD CONSTRAINT flywheel_promotion_criteria_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_purchase_attributions
    ADD CONSTRAINT flywheel_purchase_attributions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_readouts
    ADD CONSTRAINT flywheel_readouts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_redemptions
    ADD CONSTRAINT flywheel_redemptions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_returns
    ADD CONSTRAINT flywheel_returns_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_seasonality_calendar
    ADD CONSTRAINT flywheel_seasonality_calendar_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_settlements
    ADD CONSTRAINT flywheel_settlements_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_shadow_decisions
    ADD CONSTRAINT flywheel_shadow_decisions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_shelf_life
    ADD CONSTRAINT flywheel_shelf_life_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_substitution
    ADD CONSTRAINT flywheel_substitution_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_supplier_funding
    ADD CONSTRAINT flywheel_supplier_funding_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_supplier_funding_skus
    ADD CONSTRAINT flywheel_supplier_funding_skus_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_tax_rules
    ADD CONSTRAINT flywheel_tax_rules_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.flywheel_transfer_recommendations
    ADD CONSTRAINT flywheel_transfer_recommendations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.goods_receipt_lines
    ADD CONSTRAINT goods_receipt_lines_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.goods_receipts
    ADD CONSTRAINT goods_receipts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.import_jobs
    ADD CONSTRAINT import_jobs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.import_row_undo
    ADD CONSTRAINT import_row_undo_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.import_schedules
    ADD CONSTRAINT import_schedules_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.import_schedules
    ADD CONSTRAINT import_schedules_tenant_id_name_key UNIQUE (tenant_id, name);

ALTER TABLE ONLY public.ingest_ledger
    ADD CONSTRAINT ingest_ledger_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.inventory_batches
    ADD CONSTRAINT inventory_batches_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.inventory
    ADD CONSTRAINT inventory_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.inventory_transactions
    ADD CONSTRAINT inventory_transactions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.invoice_lines
    ADD CONSTRAINT invoice_lines_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_invoice_number_key UNIQUE (invoice_number);

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.item_costs
    ADD CONSTRAINT item_costs_no_overlap EXCLUDE USING gist (tenant_id WITH =, item_id WITH =, daterange(valid_from, valid_until, '[)'::text) WITH &&);

ALTER TABLE ONLY public.item_costs
    ADD CONSTRAINT item_costs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.items
    ADD CONSTRAINT items_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.notification_preferences
    ADD CONSTRAINT notification_preferences_pkey PRIMARY KEY (user_id);

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.online_prices
    ADD CONSTRAINT online_prices_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.operations_events
    ADD CONSTRAINT operations_events_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.operations_proposals
    ADD CONSTRAINT operations_proposals_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.operations_runs
    ADD CONSTRAINT operations_runs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.outcome_pricing_plans
    ADD CONSTRAINT outcome_pricing_plans_pkey PRIMARY KEY (tenant_id);

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_token_key UNIQUE (token);

ALTER TABLE ONLY public.payment_intents
    ADD CONSTRAINT payment_intents_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.payment_webhook_events
    ADD CONSTRAINT payment_webhook_events_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.payment_webhook_events
    ADD CONSTRAINT payment_webhook_events_provider_event_ref_key UNIQUE (provider, event_ref);

ALTER TABLE ONLY public.pos_connections
    ADD CONSTRAINT pos_connections_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.pos_connections
    ADD CONSTRAINT pos_connections_tenant_id_vendor_key UNIQUE (tenant_id, vendor);

ALTER TABLE ONLY public.pos_sync_runs
    ADD CONSTRAINT pos_sync_runs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.predictions
    ADD CONSTRAINT predictions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.predictions
    ADD CONSTRAINT predictions_prediction_date_store_id_item_id_key UNIQUE (prediction_date, store_id, item_id);

ALTER TABLE ONLY public.procurement_events
    ADD CONSTRAINT procurement_events_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.product_suppliers
    ADD CONSTRAINT product_suppliers_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.promotion_items
    ADD CONSTRAINT promotion_items_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.promotion_stores
    ADD CONSTRAINT promotion_stores_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.promotions
    ADD CONSTRAINT promotions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.promotions
    ADD CONSTRAINT promotions_promotion_code_key UNIQUE (promotion_code);

ALTER TABLE ONLY public.purchase_order_lines
    ADD CONSTRAINT purchase_order_lines_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.purchase_orders
    ADD CONSTRAINT purchase_orders_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.regions
    ADD CONSTRAINT regions_code_key UNIQUE (code);

ALTER TABLE ONLY public.regions
    ADD CONSTRAINT regions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.report_history
    ADD CONSTRAINT report_history_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.retention_budget_ledger
    ADD CONSTRAINT retention_budget_ledger_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.retention_campaigns
    ADD CONSTRAINT retention_campaigns_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.retention_events
    ADD CONSTRAINT retention_events_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.sales_historical
    ADD CONSTRAINT sales_historical_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.sales_rollup_daily
    ADD CONSTRAINT sales_rollup_daily_pkey PRIMARY KEY (tenant_id, store_id, item_id, day);

ALTER TABLE ONLY public.sales_stream_raw
    ADD CONSTRAINT sales_stream_raw_event_id_key UNIQUE (event_id, "timestamp");

ALTER TABLE ONLY public.sales_stream_raw_2026_08
    ADD CONSTRAINT sales_stream_raw_new_2026_08_event_id_timestamp_key UNIQUE (event_id, "timestamp");

ALTER TABLE ONLY public.sales_stream_raw
    ADD CONSTRAINT sales_stream_raw_pkey PRIMARY KEY (id, "timestamp");

ALTER TABLE ONLY public.sales_stream_raw_2026_08
    ADD CONSTRAINT sales_stream_raw_new_2026_08_pkey PRIMARY KEY (id, "timestamp");

ALTER TABLE ONLY public.sales_stream_raw_2026_09
    ADD CONSTRAINT sales_stream_raw_new_2026_09_event_id_timestamp_key UNIQUE (event_id, "timestamp");

ALTER TABLE ONLY public.sales_stream_raw_2026_09
    ADD CONSTRAINT sales_stream_raw_new_2026_09_pkey PRIMARY KEY (id, "timestamp");

ALTER TABLE ONLY public.sales_stream_raw_2026_10
    ADD CONSTRAINT sales_stream_raw_new_2026_10_event_id_timestamp_key UNIQUE (event_id, "timestamp");

ALTER TABLE ONLY public.sales_stream_raw_2026_10
    ADD CONSTRAINT sales_stream_raw_new_2026_10_pkey PRIMARY KEY (id, "timestamp");

ALTER TABLE ONLY public.sales_stream_raw_2026_11
    ADD CONSTRAINT sales_stream_raw_new_2026_11_event_id_timestamp_key UNIQUE (event_id, "timestamp");

ALTER TABLE ONLY public.sales_stream_raw_2026_11
    ADD CONSTRAINT sales_stream_raw_new_2026_11_pkey PRIMARY KEY (id, "timestamp");

ALTER TABLE ONLY public.sales_stream_raw_default
    ADD CONSTRAINT sales_stream_raw_new_default_event_id_timestamp_key UNIQUE (event_id, "timestamp");

ALTER TABLE ONLY public.sales_stream_raw_default
    ADD CONSTRAINT sales_stream_raw_new_default_pkey PRIMARY KEY (id, "timestamp");

ALTER TABLE ONLY public.scheduled_reports
    ADD CONSTRAINT scheduled_reports_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);

ALTER TABLE ONLY public.scim_external_users
    ADD CONSTRAINT scim_external_users_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.scim_group_memberships
    ADD CONSTRAINT scim_group_memberships_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.scim_group_role_mappings
    ADD CONSTRAINT scim_group_role_mappings_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.scim_groups
    ADD CONSTRAINT scim_groups_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.security_events
    ADD CONSTRAINT security_events_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.shrinkage_records
    ADD CONSTRAINT shrinkage_records_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.sso_auth_states
    ADD CONSTRAINT sso_auth_states_pkey PRIMARY KEY (state_hash);

ALTER TABLE ONLY public.stock_transfer_items
    ADD CONSTRAINT stock_transfer_items_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.stock_transfers
    ADD CONSTRAINT stock_transfers_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.stock_transfers
    ADD CONSTRAINT stock_transfers_transfer_number_key UNIQUE (transfer_number);

ALTER TABLE ONLY public.stores
    ADD CONSTRAINT stores_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT subscriptions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.supplier_invoice_lines
    ADD CONSTRAINT supplier_invoice_lines_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.supplier_invoices
    ADD CONSTRAINT supplier_invoices_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.suppliers
    ADD CONSTRAINT suppliers_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.tenant_admin_notes
    ADD CONSTRAINT tenant_admin_notes_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.tenant_api_keys
    ADD CONSTRAINT tenant_api_keys_key_hash_key UNIQUE (key_hash);

ALTER TABLE ONLY public.tenant_api_keys
    ADD CONSTRAINT tenant_api_keys_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.tenant_billing_profile
    ADD CONSTRAINT tenant_billing_profile_pkey PRIMARY KEY (tenant_id);

ALTER TABLE ONLY public.tenant_operations_policies
    ADD CONSTRAINT tenant_operations_policies_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.tenant_operations_policies
    ADD CONSTRAINT tenant_operations_policies_tenant_id_key UNIQUE (tenant_id);

ALTER TABLE ONLY public.tenant_provisioning
    ADD CONSTRAINT tenant_provisioning_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.tenant_provisioning
    ADD CONSTRAINT tenant_provisioning_tenant_id_key UNIQUE (tenant_id);

ALTER TABLE ONLY public.tenant_scim_tokens
    ADD CONSTRAINT tenant_scim_tokens_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.tenant_sso_providers
    ADD CONSTRAINT tenant_sso_providers_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.tenant_status_events
    ADD CONSTRAINT tenant_status_events_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.tenant_webhooks
    ADD CONSTRAINT tenant_webhooks_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.tenants
    ADD CONSTRAINT tenants_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.tenants
    ADD CONSTRAINT tenants_slug_key UNIQUE (slug);

ALTER TABLE ONLY public.transaction_lines
    ADD CONSTRAINT transaction_lines_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.basket_associations
    ADD CONSTRAINT unique_item_pair UNIQUE (item_a_id, item_b_id);

ALTER TABLE ONLY public.promotion_items
    ADD CONSTRAINT unique_promotion_item UNIQUE (promotion_id, item_id);

ALTER TABLE ONLY public.promotion_stores
    ADD CONSTRAINT unique_promotion_store UNIQUE (promotion_id, store_id);

ALTER TABLE ONLY public.inventory
    ADD CONSTRAINT unique_store_item UNIQUE (store_id, item_id);

ALTER TABLE ONLY public.inventory_batches
    ADD CONSTRAINT unique_store_item_batch UNIQUE (store_id, item_id, batch_number);

ALTER TABLE ONLY public.campaign_allocations
    ADD CONSTRAINT uq_alloc UNIQUE (campaign_id, store_id, item_id);

ALTER TABLE ONLY public.flywheel_coalition_attribution
    ADD CONSTRAINT uq_coalition_attribution UNIQUE (tenant_id, campaign_id, customer_id, partner_id);

ALTER TABLE ONLY public.flywheel_coalition_partners
    ADD CONSTRAINT uq_coalition_partner UNIQUE (tenant_id, partner_name);

ALTER TABLE ONLY public.customers
    ADD CONSTRAINT uq_customers_ref UNIQUE (tenant_id, customer_ref);

ALTER TABLE ONLY public.external_identities
    ADD CONSTRAINT uq_external_identities_provider_email UNIQUE (provider_id, email);

ALTER TABLE ONLY public.external_identities
    ADD CONSTRAINT uq_external_identities_provider_subject UNIQUE (provider_id, subject);

ALTER TABLE ONLY public.flywheel_inventory_allocations
    ADD CONSTRAINT uq_flywheel_allocation UNIQUE (campaign_id, store_id, item_id);

ALTER TABLE ONLY public.flywheel_campaign_audience
    ADD CONSTRAINT uq_flywheel_audience UNIQUE (campaign_id, customer_id);

ALTER TABLE ONLY public.flywheel_holdout_balance
    ADD CONSTRAINT uq_flywheel_balance UNIQUE (tenant_id, campaign_id, checked_on, covariate);

ALTER TABLE ONLY public.flywheel_budgets
    ADD CONSTRAINT uq_flywheel_budget UNIQUE (tenant_id, budget_type, period_start);

ALTER TABLE ONLY public.flywheel_cannibalization
    ADD CONSTRAINT uq_flywheel_cannibalization UNIQUE (tenant_id, campaign_id, promoted_item_id, window_end);

ALTER TABLE ONLY public.flywheel_churn_predictions
    ADD CONSTRAINT uq_flywheel_churn_pred UNIQUE (tenant_id, customer_id, as_of_date, model_version_id);

ALTER TABLE ONLY public.flywheel_customer_consents
    ADD CONSTRAINT uq_flywheel_consent UNIQUE (tenant_id, customer_id, channel);

ALTER TABLE ONLY public.flywheel_contact_policy
    ADD CONSTRAINT uq_flywheel_contact_policy UNIQUE (tenant_id, channel);

ALTER TABLE ONLY public.flywheel_customers
    ADD CONSTRAINT uq_flywheel_customer_ref UNIQUE (tenant_id, external_ref);

ALTER TABLE ONLY public.flywheel_feature_snapshots
    ADD CONSTRAINT uq_flywheel_features UNIQUE (tenant_id, customer_id, as_of_date);

ALTER TABLE ONLY public.flywheel_supplier_funding_skus
    ADD CONSTRAINT uq_flywheel_funding_sku UNIQUE (funding_id, item_id);

ALTER TABLE ONLY public.flywheel_identity_links
    ADD CONSTRAINT uq_flywheel_identity_key UNIQUE (tenant_id, pos_key);

ALTER TABLE ONLY public.flywheel_model_versions
    ADD CONSTRAINT uq_flywheel_model_version UNIQUE (tenant_id, model_kind, version_label);

ALTER TABLE ONLY public.flywheel_profiling_objections
    ADD CONSTRAINT uq_flywheel_objection UNIQUE (tenant_id, customer_id);

ALTER TABLE ONLY public.flywheel_offers
    ADD CONSTRAINT uq_flywheel_offer_code UNIQUE (tenant_id, offer_code);

ALTER TABLE ONLY public.flywheel_campaign_outcomes
    ADD CONSTRAINT uq_flywheel_outcome UNIQUE (campaign_id, measured_at);

ALTER TABLE ONLY public.flywheel_pos_staging
    ADD CONSTRAINT uq_flywheel_pos_txn UNIQUE (tenant_id, external_txn_id);

ALTER TABLE ONLY public.flywheel_preregistrations
    ADD CONSTRAINT uq_flywheel_prereg_campaign UNIQUE (tenant_id, campaign_id);

ALTER TABLE ONLY public.flywheel_promotion_criteria
    ADD CONSTRAINT uq_flywheel_promotion UNIQUE (tenant_id, model_label);

ALTER TABLE ONLY public.flywheel_readouts
    ADD CONSTRAINT uq_flywheel_readout_window UNIQUE (tenant_id, campaign_id, window_end);

ALTER TABLE ONLY public.flywheel_delivery_receipts
    ADD CONSTRAINT uq_flywheel_receipt UNIQUE (tenant_id, consumer, event_key);

ALTER TABLE ONLY public.flywheel_redemptions
    ADD CONSTRAINT uq_flywheel_redemption_idem UNIQUE (tenant_id, idempotency_key);

ALTER TABLE ONLY public.flywheel_returns
    ADD CONSTRAINT uq_flywheel_return_idem UNIQUE (tenant_id, idempotency_key);

ALTER TABLE ONLY public.flywheel_settlements
    ADD CONSTRAINT uq_flywheel_settlement UNIQUE (tenant_id, funding_id, period_start, period_end);

ALTER TABLE ONLY public.flywheel_shadow_decisions
    ADD CONSTRAINT uq_flywheel_shadow UNIQUE (tenant_id, customer_id, campaign_id, model_label);

ALTER TABLE ONLY public.flywheel_substitution
    ADD CONSTRAINT uq_flywheel_substitution UNIQUE (tenant_id, campaign_id, from_item_id, to_item_id);

ALTER TABLE ONLY public.flywheel_offer_response_predictions
    ADD CONSTRAINT uq_flywheel_uplift_pred UNIQUE (tenant_id, customer_id, action_type, as_of_date, model_version_id);

ALTER TABLE ONLY public.ingest_ledger
    ADD CONSTRAINT uq_ingest_chunk UNIQUE (tenant_id, source_name, chunk_sha256);

ALTER TABLE ONLY public.supplier_invoices
    ADD CONSTRAINT uq_invoice_number UNIQUE (tenant_id, invoice_number);

ALTER TABLE ONLY public.campaign_offers
    ADD CONSTRAINT uq_offer_campaign_customer UNIQUE (campaign_id, customer_id);

ALTER TABLE ONLY public.campaign_offers
    ADD CONSTRAINT uq_offer_redemption_key UNIQUE (tenant_id, redemption_key);

ALTER TABLE ONLY public.operations_proposals
    ADD CONSTRAINT uq_operations_proposals_tenant_id UNIQUE (tenant_id, id);

ALTER TABLE ONLY public.operations_runs
    ADD CONSTRAINT uq_operations_runs_tenant_id UNIQUE (tenant_id, id);

ALTER TABLE ONLY public.flywheel_outcome_pricing
    ADD CONSTRAINT uq_outcome_pricing UNIQUE (tenant_id, plan_name);

ALTER TABLE ONLY public.purchase_orders
    ADD CONSTRAINT uq_po_number UNIQUE (tenant_id, po_number);

ALTER TABLE ONLY public.product_suppliers
    ADD CONSTRAINT uq_product_supplier UNIQUE (tenant_id, item_id, supplier_id);

ALTER TABLE ONLY public.goods_receipts
    ADD CONSTRAINT uq_receipt_number UNIQUE (tenant_id, receipt_number);

ALTER TABLE ONLY public.scim_external_users
    ADD CONSTRAINT uq_scim_external_users_tenant_username UNIQUE (tenant_id, scim_user_name);

ALTER TABLE ONLY public.scim_group_memberships
    ADD CONSTRAINT uq_scim_group_membership UNIQUE (group_id, user_id);

ALTER TABLE ONLY public.scim_group_role_mappings
    ADD CONSTRAINT uq_scim_group_role_mapping UNIQUE (group_id);

ALTER TABLE ONLY public.scim_groups
    ADD CONSTRAINT uq_scim_groups_tenant_name UNIQUE (tenant_id, display_name);

ALTER TABLE ONLY public.flywheel_shelf_life
    ADD CONSTRAINT uq_shelf_life_batch UNIQUE (tenant_id, store_id, item_id, batch_ref);

ALTER TABLE ONLY public.tenant_sso_providers
    ADD CONSTRAINT uq_tenant_sso_providers_tenant_name UNIQUE (tenant_id, name);

ALTER TABLE ONLY public.transaction_lines
    ADD CONSTRAINT uq_transaction_lines_line_no UNIQUE (transaction_id, line_no);

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT uq_transactions_source_ref UNIQUE (tenant_id, source, txn_ref);

ALTER TABLE ONLY public.usage_events
    ADD CONSTRAINT usage_events_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.user_feedback
    ADD CONSTRAINT user_feedback_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.user_permissions
    ADD CONSTRAINT user_permissions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.user_sessions
    ADD CONSTRAINT user_sessions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.user_sessions
    ADD CONSTRAINT user_sessions_refresh_token_key UNIQUE (refresh_token);

ALTER TABLE ONLY public.user_sessions
    ADD CONSTRAINT user_sessions_session_token_key UNIQUE (session_token);

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.value_realizations
    ADD CONSTRAINT value_realizations_finding_id_key UNIQUE (finding_id);

ALTER TABLE ONLY public.value_realizations
    ADD CONSTRAINT value_realizations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.webhook_deliveries
    ADD CONSTRAINT webhook_deliveries_pkey PRIMARY KEY (id);

CREATE INDEX idx_alert_notifications_unread ON public.alert_notifications USING btree (user_id) WHERE (read_at IS NULL);

CREATE INDEX idx_alert_notifications_user ON public.alert_notifications USING btree (user_id);

CREATE INDEX idx_alerts_assigned_to ON public.alerts USING btree (assigned_to) WHERE (assigned_to IS NOT NULL);

CREATE INDEX idx_alerts_created ON public.alerts USING btree (created_at DESC);

CREATE UNIQUE INDEX idx_alerts_dedupe_open ON public.alerts USING btree (dedupe_key) WHERE ((status = ANY (ARRAY['active'::public.alert_status, 'acknowledged'::public.alert_status])) AND (dedupe_key IS NOT NULL));

CREATE INDEX idx_alerts_severity ON public.alerts USING btree (severity);

CREATE INDEX idx_alerts_status ON public.alerts USING btree (status);

CREATE INDEX idx_alerts_store ON public.alerts USING btree (store_id);

CREATE INDEX idx_alerts_type ON public.alerts USING btree (alert_type);

CREATE INDEX idx_audit_log_action ON public.audit_log USING btree (action);

CREATE INDEX idx_audit_log_created ON public.audit_log USING btree (created_at DESC);

CREATE INDEX idx_audit_log_resource ON public.audit_log USING btree (resource_type, resource_id);

CREATE INDEX idx_audit_log_user ON public.audit_log USING btree (user_id);

CREATE INDEX idx_auth_tokens_expires ON public.auth_tokens USING btree (expires_at);

CREATE INDEX idx_auth_tokens_type_hash ON public.auth_tokens USING btree (token_type, token_hash);

CREATE INDEX idx_auth_tokens_user ON public.auth_tokens USING btree (user_id);

CREATE INDEX idx_basket_items ON public.basket_associations USING btree (item_a_id, item_b_id);

CREATE INDEX idx_basket_lift ON public.basket_associations USING btree (lift DESC);

CREATE INDEX idx_batches_expiry ON public.inventory_batches USING btree (expiry_date) WHERE (((status)::text = 'active'::text) AND (expiry_date IS NOT NULL));

CREATE INDEX idx_batches_store_item ON public.inventory_batches USING btree (store_id, item_id);

CREATE INDEX idx_campaign_allocations_tenant ON public.campaign_allocations USING btree (tenant_id);

CREATE INDEX idx_campaign_offers_campaign ON public.campaign_offers USING btree (campaign_id);

CREATE INDEX idx_campaign_offers_customer ON public.campaign_offers USING btree (tenant_id, customer_id);

CREATE INDEX idx_competitor_prices_date ON public.competitor_prices USING btree (observed_date DESC);

CREATE INDEX idx_competitor_prices_item ON public.competitor_prices USING btree (item_id);

CREATE INDEX idx_customer_purchases_scan ON public.customer_purchases USING btree (tenant_id, customer_id, purchase_date DESC);

CREATE INDEX idx_customers_tenant ON public.customers USING btree (tenant_id);

CREATE INDEX idx_data_sources_tenant ON public.data_sources USING btree (tenant_id);

CREATE INDEX idx_documents_content_hash ON public.documents USING btree (content_hash);

CREATE INDEX idx_documents_corpus ON public.documents USING btree (tenant_id, corpus);

CREATE INDEX idx_documents_embedding ON public.documents USING hnsw (embedding public.vector_cosine_ops);

CREATE INDEX idx_documents_needs_embedding ON public.documents USING btree (tenant_id) WHERE (embedding IS NULL);

CREATE INDEX idx_documents_store_scope ON public.documents USING gin (store_scope);

CREATE INDEX idx_documents_tenant ON public.documents USING btree (tenant_id);

CREATE INDEX idx_documents_tsv ON public.documents USING gin (tsv);

CREATE INDEX idx_documents_visibility_roles ON public.documents USING gin (visibility_roles);

CREATE INDEX idx_emp_attendance_date ON public.employee_attendance USING btree (attendance_date);

CREATE INDEX idx_emp_attendance_employee ON public.employee_attendance USING btree (employee_id);

CREATE INDEX idx_emp_perf_employee ON public.employee_performance USING btree (employee_id);

CREATE INDEX idx_emp_perf_period ON public.employee_performance USING btree (period_start, period_end);

CREATE INDEX idx_emp_perf_score ON public.employee_performance USING btree (performance_score DESC);

CREATE INDEX idx_emp_txn_date ON public.employee_transactions USING btree (transaction_date);

CREATE INDEX idx_emp_txn_employee ON public.employee_transactions USING btree (employee_id);

CREATE INDEX idx_emp_txn_store ON public.employee_transactions USING btree (store_id);

CREATE INDEX idx_emp_txn_type ON public.employee_transactions USING btree (transaction_type);

CREATE INDEX idx_employees_code ON public.employees USING btree (employee_code);

CREATE INDEX idx_employees_region ON public.employees USING btree (region_id);

CREATE INDEX idx_employees_role ON public.employees USING btree (role);

CREATE INDEX idx_employees_status ON public.employees USING btree (status);

CREATE INDEX idx_employees_store ON public.employees USING btree (store_id);

CREATE INDEX idx_external_identities_provider ON public.external_identities USING btree (provider_id);

CREATE INDEX idx_external_identities_tenant ON public.external_identities USING btree (tenant_id);

CREATE INDEX idx_external_identities_user ON public.external_identities USING btree (user_id);

CREATE INDEX idx_external_sales_date_brin ON ONLY public.external_sales USING brin (sale_date);

CREATE INDEX idx_external_sales_tenant ON ONLY public.external_sales USING btree (tenant_id, store_id);

CREATE INDEX idx_findings_measure ON public.findings USING btree (tenant_id, measured_at) WHERE ((action_accepted_at IS NOT NULL) AND (status <> 'resolved'::text));

CREATE INDEX idx_findings_tenant_detected ON public.findings USING btree (tenant_id, detected_at DESC);

CREATE INDEX idx_findings_tenant_status ON public.findings USING btree (tenant_id, status, severity);

CREATE INDEX idx_flywheel_alloc_lines_customer ON public.flywheel_allocation_lines USING btree (tenant_id, customer_id);

CREATE INDEX idx_flywheel_alloc_lines_run ON public.flywheel_allocation_lines USING btree (tenant_id, run_id, selected);

CREATE INDEX idx_flywheel_alloc_runs_campaign ON public.flywheel_allocation_runs USING btree (tenant_id, campaign_id, created_at DESC);

CREATE INDEX idx_flywheel_balance_campaign ON public.flywheel_holdout_balance USING btree (tenant_id, campaign_id, checked_on DESC);

CREATE INDEX idx_flywheel_cannibalization_campaign ON public.flywheel_cannibalization USING btree (tenant_id, campaign_id, window_end DESC);

CREATE INDEX idx_flywheel_coalition_activity_customer ON public.flywheel_coalition_activity USING btree (tenant_id, customer_id, occurred_at DESC);

CREATE INDEX idx_flywheel_coalition_attr_campaign ON public.flywheel_coalition_attribution USING btree (tenant_id, campaign_id, partner_id);

CREATE INDEX idx_flywheel_decisions_trace ON public.flywheel_decisions USING btree (tenant_id, trace_id) WHERE (trace_id IS NOT NULL);

CREATE INDEX idx_flywheel_funding_campaign ON public.flywheel_supplier_funding USING btree (tenant_id, campaign_id);

CREATE INDEX idx_flywheel_funding_skus_item ON public.flywheel_supplier_funding_skus USING btree (tenant_id, item_id);

CREATE INDEX idx_flywheel_funding_supplier ON public.flywheel_supplier_funding USING btree (tenant_id, supplier_id, status);

CREATE INDEX idx_flywheel_identity_customer ON public.flywheel_identity_links USING btree (tenant_id, customer_id);

CREATE INDEX idx_flywheel_jobs_ready ON public.flywheel_jobs USING btree (run_after, id) WHERE ((status)::text = ANY ((ARRAY['queued'::character varying, 'failed'::character varying])::text[]));

CREATE INDEX idx_flywheel_jobs_running_lease ON public.flywheel_jobs USING btree (lease_expires_at) WHERE ((status)::text = 'running'::text);

CREATE INDEX idx_flywheel_model_versions_lifecycle ON public.flywheel_model_versions USING btree (tenant_id, lifecycle_status);

CREATE INDEX idx_flywheel_model_versions_snapshot ON public.flywheel_model_versions USING btree (tenant_id, data_snapshot_hash);

CREATE INDEX idx_flywheel_objections_active ON public.flywheel_profiling_objections USING btree (tenant_id, customer_id) WHERE ((status)::text = 'active'::text);

CREATE INDEX idx_flywheel_pos_unresolved ON public.flywheel_pos_staging USING btree (tenant_id) WHERE (resolved = false);

CREATE INDEX idx_flywheel_prereg_campaign ON public.flywheel_preregistrations USING btree (tenant_id, campaign_id);

CREATE INDEX idx_flywheel_readouts_campaign ON public.flywheel_readouts USING btree (tenant_id, campaign_id, window_end DESC);

CREATE INDEX idx_flywheel_readouts_computed ON public.flywheel_readouts USING btree (tenant_id, computed_at DESC);

CREATE INDEX idx_flywheel_receipts_consumer ON public.flywheel_delivery_receipts USING btree (tenant_id, consumer, processed_at DESC);

CREATE INDEX idx_flywheel_season_window ON public.flywheel_seasonality_calendar USING btree (tenant_id, starts_on, ends_on);

CREATE INDEX idx_flywheel_settlements_funding ON public.flywheel_settlements USING btree (tenant_id, funding_id, period_end DESC);

CREATE INDEX idx_flywheel_shadow_campaign ON public.flywheel_shadow_decisions USING btree (tenant_id, campaign_id, agreed);

CREATE INDEX idx_flywheel_shadow_model ON public.flywheel_shadow_decisions USING btree (tenant_id, model_label, created_at DESC);

CREATE INDEX idx_flywheel_shelf_life_expiry ON public.flywheel_shelf_life USING btree (tenant_id, expires_on) WHERE ((status)::text = 'active'::text);

CREATE INDEX idx_flywheel_substitution_campaign ON public.flywheel_substitution USING btree (tenant_id, campaign_id);

CREATE INDEX idx_goods_receipts_po ON public.goods_receipts USING btree (po_id);

CREATE INDEX idx_goods_receipts_tenant ON public.goods_receipts USING btree (tenant_id);

CREATE INDEX idx_ingest_ledger_job ON public.ingest_ledger USING btree (job_id, chunk_no);

CREATE INDEX idx_inv_trans_date ON public.inventory_transactions USING btree (created_at DESC);

CREATE INDEX idx_inv_trans_inventory ON public.inventory_transactions USING btree (inventory_id);

CREATE INDEX idx_inv_trans_store ON public.inventory_transactions USING btree (store_id);

CREATE INDEX idx_inv_trans_type ON public.inventory_transactions USING btree (transaction_type);

CREATE INDEX idx_inventory_abc ON public.inventory USING btree (abc_class);

CREATE INDEX idx_inventory_item ON public.inventory USING btree (item_id);

CREATE INDEX idx_inventory_low_stock ON public.inventory USING btree (current_stock) WHERE (current_stock <= reorder_point);

CREATE INDEX idx_inventory_store ON public.inventory USING btree (store_id);

CREATE INDEX idx_invoice_lines_invoice ON public.supplier_invoice_lines USING btree (invoice_id);

CREATE INDEX idx_item_costs_lookup ON public.item_costs USING btree (tenant_id, item_id, valid_from DESC);

CREATE INDEX idx_item_costs_tenant ON public.item_costs USING btree (tenant_id);

CREATE INDEX idx_items_tenant ON public.items USING btree (tenant_id);

CREATE UNIQUE INDEX idx_mv_daily_store ON public.mv_daily_sales_by_store USING btree (date, store_id);

CREATE UNIQUE INDEX idx_mv_hourly_pattern ON public.mv_hourly_sales_pattern USING btree (day_of_week, hour_of_day, store_id);

CREATE UNIQUE INDEX idx_mv_weekly_category ON public.mv_weekly_sales_by_category USING btree (week_start, category);

CREATE INDEX idx_po_lines_po ON public.purchase_order_lines USING btree (po_id);

CREATE INDEX idx_proc_events_entity ON public.procurement_events USING btree (entity_type, entity_id);

CREATE INDEX idx_proc_events_tenant_time ON public.procurement_events USING btree (tenant_id, created_at DESC);

CREATE INDEX idx_product_suppliers_item ON public.product_suppliers USING btree (item_id);

CREATE INDEX idx_product_suppliers_tenant ON public.product_suppliers USING btree (tenant_id);

CREATE INDEX idx_promotion_items_item ON public.promotion_items USING btree (item_id);

CREATE INDEX idx_promotion_items_promotion ON public.promotion_items USING btree (promotion_id);

CREATE INDEX idx_promotions_active ON public.promotions USING btree (status) WHERE (status = 'active'::public.promotion_status);

CREATE INDEX idx_promotions_dates ON public.promotions USING btree (start_date, end_date);

CREATE INDEX idx_promotions_status ON public.promotions USING btree (status);

CREATE INDEX idx_promotions_tenant ON public.promotions USING btree (tenant_id);

CREATE INDEX idx_promotions_window ON public.promotions USING btree (tenant_id, start_date, end_date);

CREATE INDEX idx_purchase_orders_supplier ON public.purchase_orders USING btree (supplier_id);

CREATE INDEX idx_purchase_orders_tenant ON public.purchase_orders USING btree (tenant_id);

CREATE INDEX idx_receipt_lines_receipt ON public.goods_receipt_lines USING btree (receipt_id);

CREATE INDEX idx_report_history_date ON public.report_history USING btree (created_at DESC);

CREATE INDEX idx_report_history_scheduled ON public.report_history USING btree (scheduled_report_id);

CREATE INDEX idx_report_history_status ON public.report_history USING btree (status);

CREATE INDEX idx_retention_campaigns_tenant ON public.retention_campaigns USING btree (tenant_id);

CREATE INDEX idx_retention_events_scan ON public.retention_events USING btree (tenant_id, created_at DESC);

CREATE INDEX idx_retention_ledger_campaign ON public.retention_budget_ledger USING btree (tenant_id, campaign_id, created_at DESC);

CREATE INDEX idx_rollup_daily_tenant_day ON public.sales_rollup_daily USING btree (tenant_id, day);

CREATE INDEX idx_sales_hist_date_store_item ON public.sales_historical USING btree (date, store_id, item_id) INCLUDE (sales);

CREATE INDEX idx_sales_historical_date ON public.sales_historical USING btree (date);

CREATE INDEX idx_sales_historical_store_item ON public.sales_historical USING btree (store_id, item_id);

CREATE INDEX idx_sales_historical_tenant ON public.sales_historical USING btree (tenant_id);

CREATE INDEX idx_sales_stream_raw_tenant ON ONLY public.sales_stream_raw USING btree (tenant_id);

CREATE INDEX idx_sales_stream_store_item ON ONLY public.sales_stream_raw USING btree (store_id, item_id);

CREATE INDEX idx_sales_stream_synthetic ON ONLY public.sales_stream_raw USING btree (tenant_id, "timestamp") WHERE is_synthetic;

CREATE INDEX idx_sales_stream_timestamp ON ONLY public.sales_stream_raw USING btree ("timestamp");

CREATE INDEX idx_scheduled_reports_active ON public.scheduled_reports USING btree (is_active) WHERE (is_active = true);

CREATE INDEX idx_scheduled_reports_next_run ON public.scheduled_reports USING btree (next_run_at);

CREATE INDEX idx_scim_external_users_user ON public.scim_external_users USING btree (user_id);

CREATE INDEX idx_scim_group_memberships_group ON public.scim_group_memberships USING btree (group_id);

CREATE INDEX idx_scim_groups_tenant ON public.scim_groups USING btree (tenant_id);

CREATE INDEX idx_security_events_ip ON public.security_events USING btree (tenant_id, ip_address, occurred_at DESC);

CREATE INDEX idx_security_events_tenant_sev ON public.security_events USING btree (tenant_id, severity, occurred_at DESC);

CREATE INDEX idx_security_events_tenant_time ON public.security_events USING btree (tenant_id, occurred_at DESC);

CREATE INDEX idx_security_events_tenant_type ON public.security_events USING btree (tenant_id, event_type, occurred_at DESC);

CREATE INDEX idx_sso_auth_states_expires ON public.sso_auth_states USING btree (expires_at);

CREATE INDEX idx_sso_auth_states_provider ON public.sso_auth_states USING btree (provider_id);

CREATE INDEX idx_stores_tenant ON public.stores USING btree (tenant_id);

CREATE INDEX idx_supplier_invoices_po ON public.supplier_invoices USING btree (po_id);

CREATE INDEX idx_supplier_invoices_tenant ON public.supplier_invoices USING btree (tenant_id);

CREATE INDEX idx_suppliers_tenant ON public.suppliers USING btree (tenant_id);

CREATE INDEX idx_tenant_api_keys_hash ON public.tenant_api_keys USING btree (key_hash);

CREATE INDEX idx_tenant_api_keys_tenant ON public.tenant_api_keys USING btree (tenant_id);

CREATE INDEX idx_tenant_scim_tokens_active ON public.tenant_scim_tokens USING btree (tenant_id, revoked_at);

CREATE INDEX idx_tenant_scim_tokens_hash ON public.tenant_scim_tokens USING btree (token_hash);

CREATE INDEX idx_tenant_scim_tokens_tenant ON public.tenant_scim_tokens USING btree (tenant_id);

CREATE INDEX idx_tenant_sso_providers_enabled ON public.tenant_sso_providers USING btree (tenant_id, enabled);

CREATE INDEX idx_tenant_sso_providers_tenant ON public.tenant_sso_providers USING btree (tenant_id);

CREATE INDEX idx_tenant_webhooks_tenant ON public.tenant_webhooks USING btree (tenant_id);

CREATE INDEX idx_transaction_lines_item ON public.transaction_lines USING btree (item_id);

CREATE INDEX idx_transaction_lines_txn ON public.transaction_lines USING btree (transaction_id);

CREATE INDEX idx_transactions_scan ON public.transactions USING btree (tenant_id, store_id, txn_date);

CREATE INDEX idx_transactions_tenant ON public.transactions USING btree (tenant_id);

CREATE INDEX idx_transactions_time ON public.transactions USING btree (tenant_id, txn_time);

CREATE INDEX idx_transfers_from ON public.stock_transfers USING btree (from_store_id);

CREATE INDEX idx_transfers_status ON public.stock_transfers USING btree (status);

CREATE INDEX idx_transfers_to ON public.stock_transfers USING btree (to_store_id);

CREATE INDEX idx_user_permissions_region ON public.user_permissions USING btree (region_id);

CREATE INDEX idx_user_permissions_store ON public.user_permissions USING btree (store_id);

CREATE INDEX idx_user_permissions_user ON public.user_permissions USING btree (user_id);

CREATE INDEX idx_user_sessions_token ON public.user_sessions USING btree (session_token);

CREATE INDEX idx_user_sessions_user ON public.user_sessions USING btree (user_id);

CREATE INDEX idx_users_email ON public.users USING btree (email);

CREATE INDEX idx_users_role ON public.users USING btree (role);

CREATE INDEX idx_users_status ON public.users USING btree (status);

CREATE INDEX idx_users_tenant ON public.users USING btree (tenant_id);

CREATE INDEX idx_webhook_deliveries_hook ON public.webhook_deliveries USING btree (webhook_id, delivered_at DESC);

CREATE INDEX idx_webhook_deliveries_tenant ON public.webhook_deliveries USING btree (tenant_id, delivered_at DESC);

CREATE INDEX ix_action_drafts_finding ON public.action_drafts USING btree (finding_id);

CREATE INDEX ix_action_drafts_tenant_status ON public.action_drafts USING btree (tenant_id, status, created_at DESC);

CREATE INDEX ix_bespoke_requests_status ON public.bespoke_requests USING btree (status);

CREATE INDEX ix_bespoke_requests_tenant ON public.bespoke_requests USING btree (tenant_id);

CREATE INDEX ix_data_requests_status ON public.data_requests USING btree (status) WHERE (status = 'pending'::text);

CREATE INDEX ix_data_requests_tenant ON public.data_requests USING btree (tenant_id, created_at DESC);

CREATE INDEX ix_einvoice_submissions_chain ON public.einvoice_submissions USING btree (tenant_id, cleared_at DESC) WHERE (status = 'cleared'::text);

CREATE INDEX ix_einvoice_submissions_invoice ON public.einvoice_submissions USING btree (invoice_id);

CREATE INDEX ix_flywheel_alloc_lookup ON public.flywheel_inventory_allocations USING btree (tenant_id, store_id, item_id, status);

CREATE INDEX ix_flywheel_approval_requests ON public.flywheel_approval_requests USING btree (tenant_id, status, created_at DESC);

CREATE INDEX ix_flywheel_attr_event ON public.flywheel_purchase_attributions USING btree (event_id);

CREATE INDEX ix_flywheel_attr_sale ON public.flywheel_purchase_attributions USING btree (tenant_id, sale_source, sale_id);

CREATE INDEX ix_flywheel_audience_campaign ON public.flywheel_campaign_audience USING btree (tenant_id, campaign_id, assignment);

CREATE INDEX ix_flywheel_budgets_tenant ON public.flywheel_budgets USING btree (tenant_id, budget_type);

CREATE INDEX ix_flywheel_campaigns_tenant ON public.flywheel_campaigns USING btree (tenant_id, status);

CREATE INDEX ix_flywheel_churn_lookup ON public.flywheel_churn_predictions USING btree (tenant_id, as_of_date, churn_probability DESC);

CREATE INDEX ix_flywheel_consents_customer ON public.flywheel_customer_consents USING btree (customer_id);

CREATE INDEX ix_flywheel_contact_global ON public.flywheel_contact_log USING btree (tenant_id, customer_id, channel, contacted_at DESC);

CREATE INDEX ix_flywheel_contact_window ON public.flywheel_contact_log USING btree (tenant_id, customer_id, contacted_at DESC);

CREATE INDEX ix_flywheel_customers_status ON public.flywheel_customers USING btree (tenant_id, status);

CREATE INDEX ix_flywheel_customers_store ON public.flywheel_customers USING btree (home_store_id);

CREATE INDEX ix_flywheel_customers_tenant ON public.flywheel_customers USING btree (tenant_id);

CREATE INDEX ix_flywheel_decisions_campaign ON public.flywheel_decisions USING btree (tenant_id, campaign_id, decided_at DESC);

CREATE INDEX ix_flywheel_decisions_customer ON public.flywheel_decisions USING btree (tenant_id, customer_id, decided_at DESC);

CREATE INDEX ix_flywheel_events_seq ON public.flywheel_customer_events USING btree (tenant_id, customer_id, occurred_at);

CREATE INDEX ix_flywheel_events_type ON public.flywheel_customer_events USING btree (tenant_id, event_type, occurred_at);

CREATE INDEX ix_flywheel_features_asof ON public.flywheel_feature_snapshots USING btree (tenant_id, as_of_date);

CREATE INDEX ix_flywheel_ledger_budget ON public.flywheel_budget_ledger USING btree (tenant_id, budget_id, created_at DESC);

CREATE INDEX ix_flywheel_ledger_campaign ON public.flywheel_budget_ledger USING btree (tenant_id, campaign_id, entry_type);

CREATE INDEX ix_flywheel_models_active ON public.flywheel_model_versions USING btree (tenant_id, model_kind, is_active);

CREATE INDEX ix_flywheel_offers_campaign ON public.flywheel_offers USING btree (tenant_id, campaign_id, status);

CREATE INDEX ix_flywheel_offers_customer ON public.flywheel_offers USING btree (tenant_id, customer_id, status);

CREATE INDEX ix_flywheel_outbox_pending ON public.flywheel_outbox USING btree (published, id) WHERE (published = false);

CREATE INDEX ix_flywheel_outcomes_campaign ON public.flywheel_campaign_outcomes USING btree (tenant_id, campaign_id);

CREATE INDEX ix_flywheel_policies_tenant ON public.flywheel_approval_policies USING btree (tenant_id, applies_to, is_active);

CREATE INDEX ix_flywheel_redemptions_campaign ON public.flywheel_redemptions USING btree (tenant_id, campaign_id, created_at DESC);

CREATE INDEX ix_flywheel_requisitions_campaign ON public.flywheel_procurement_requisitions USING btree (tenant_id, campaign_id, status);

CREATE INDEX ix_flywheel_returns_campaign ON public.flywheel_returns USING btree (tenant_id, campaign_id, created_at DESC);

CREATE INDEX ix_flywheel_steps_request ON public.flywheel_approval_steps USING btree (request_id, step_order);

CREATE INDEX ix_flywheel_suppressions_campaign ON public.flywheel_offer_suppressions USING btree (tenant_id, suppressed_campaign_id);

CREATE INDEX ix_flywheel_suppressions_customer ON public.flywheel_offer_suppressions USING btree (tenant_id, customer_id, created_at DESC);

CREATE INDEX ix_flywheel_tax_lookup ON public.flywheel_tax_rules USING btree (tenant_id, is_active, category);

CREATE INDEX ix_flywheel_transfers_campaign ON public.flywheel_transfer_recommendations USING btree (tenant_id, campaign_id, status);

CREATE INDEX ix_flywheel_transitions_campaign ON public.flywheel_campaign_transitions USING btree (campaign_id, created_at);

CREATE INDEX ix_flywheel_uplift_lookup ON public.flywheel_offer_response_predictions USING btree (tenant_id, as_of_date, uplift DESC);

CREATE INDEX ix_import_jobs_tenant ON public.import_jobs USING btree (tenant_id, created_at DESC);

CREATE INDEX ix_import_row_undo_job ON public.import_row_undo USING btree (import_job_id, id DESC);

CREATE INDEX ix_import_schedules_due ON public.import_schedules USING btree (next_run_at) WHERE active;

CREATE INDEX ix_import_schedules_tenant ON public.import_schedules USING btree (tenant_id, active);

CREATE INDEX ix_invoice_lines_invoice ON public.invoice_lines USING btree (invoice_id);

CREATE INDEX ix_invoices_tenant ON public.invoices USING btree (tenant_id, created_at DESC);

CREATE INDEX ix_items_import_job ON public.items USING btree (import_job_id) WHERE (import_job_id IS NOT NULL);

CREATE INDEX ix_notifications_tenant_user_time ON public.notifications USING btree (tenant_id, user_id, created_at DESC);

CREATE INDEX ix_notifications_unread ON public.notifications USING btree (tenant_id, created_at DESC) WHERE (read_at IS NULL);

CREATE INDEX ix_operations_events_run ON public.operations_events USING btree (run_id, created_at);

CREATE INDEX ix_operations_events_tenant_type ON public.operations_events USING btree (tenant_id, event_type, created_at DESC);

CREATE INDEX ix_operations_proposals_finding ON public.operations_proposals USING btree (tenant_id, finding_id);

CREATE INDEX ix_operations_proposals_run ON public.operations_proposals USING btree (run_id);

CREATE INDEX ix_operations_proposals_tenant_status ON public.operations_proposals USING btree (tenant_id, status, created_at DESC);

CREATE INDEX ix_operations_runs_finding ON public.operations_runs USING btree (tenant_id, finding_id);

CREATE INDEX ix_operations_runs_tenant_status ON public.operations_runs USING btree (tenant_id, status, created_at DESC);

CREATE INDEX ix_payment_intents_external ON public.payment_intents USING btree (provider, external_ref);

CREATE INDEX ix_payment_intents_tenant ON public.payment_intents USING btree (tenant_id, status);

CREATE INDEX ix_payment_webhook_intent ON public.payment_webhook_events USING btree (intent_id);

CREATE INDEX ix_pos_connections_tenant ON public.pos_connections USING btree (tenant_id, status);

CREATE INDEX ix_pos_sync_runs_conn ON public.pos_sync_runs USING btree (connection_id, started_at DESC);

CREATE INDEX ix_sales_historical_import_job ON public.sales_historical USING btree (import_job_id) WHERE (import_job_id IS NOT NULL);

CREATE INDEX ix_stores_import_job ON public.stores USING btree (import_job_id) WHERE (import_job_id IS NOT NULL);

CREATE INDEX ix_suppliers_import_job ON public.suppliers USING btree (import_job_id) WHERE (import_job_id IS NOT NULL);

CREATE INDEX ix_tenant_admin_notes_tenant ON public.tenant_admin_notes USING btree (tenant_id, created_at DESC);

CREATE INDEX ix_tenant_api_keys_expires_at ON public.tenant_api_keys USING btree (expires_at) WHERE (expires_at IS NOT NULL);

CREATE INDEX ix_tenant_provisioning_active ON public.tenant_provisioning USING btree (tenant_id) WHERE (status = 'active'::text);

CREATE INDEX ix_tenant_status_events_tenant ON public.tenant_status_events USING btree (tenant_id, created_at DESC);

CREATE INDEX ix_tenants_isolation_tier ON public.tenants USING btree (isolation_tier) WHERE (isolation_tier <> 'shared'::text);

CREATE INDEX ix_usage_events_tenant_type_time ON public.usage_events USING btree (tenant_id, event_type, created_at DESC);

CREATE INDEX ix_user_feedback_tenant_time ON public.user_feedback USING btree (tenant_id, created_at DESC);

CREATE INDEX ix_value_realizations_disputed ON public.value_realizations USING btree (tenant_id, disputed_at DESC) WHERE (status = 'disputed'::text);

CREATE INDEX ix_value_realizations_tenant ON public.value_realizations USING btree (tenant_id, status, confirmed_at DESC);

CREATE INDEX sales_stream_raw_new_2026_08_store_id_item_id_idx ON public.sales_stream_raw_2026_08 USING btree (store_id, item_id);

CREATE INDEX sales_stream_raw_new_2026_08_tenant_id_idx ON public.sales_stream_raw_2026_08 USING btree (tenant_id);

CREATE INDEX sales_stream_raw_new_2026_08_tenant_id_timestamp_idx ON public.sales_stream_raw_2026_08 USING btree (tenant_id, "timestamp") WHERE is_synthetic;

CREATE INDEX sales_stream_raw_new_2026_08_timestamp_idx ON public.sales_stream_raw_2026_08 USING btree ("timestamp");

CREATE INDEX sales_stream_raw_new_2026_09_store_id_item_id_idx ON public.sales_stream_raw_2026_09 USING btree (store_id, item_id);

CREATE INDEX sales_stream_raw_new_2026_09_tenant_id_idx ON public.sales_stream_raw_2026_09 USING btree (tenant_id);

CREATE INDEX sales_stream_raw_new_2026_09_tenant_id_timestamp_idx ON public.sales_stream_raw_2026_09 USING btree (tenant_id, "timestamp") WHERE is_synthetic;

CREATE INDEX sales_stream_raw_new_2026_09_timestamp_idx ON public.sales_stream_raw_2026_09 USING btree ("timestamp");

CREATE INDEX sales_stream_raw_new_2026_10_store_id_item_id_idx ON public.sales_stream_raw_2026_10 USING btree (store_id, item_id);

CREATE INDEX sales_stream_raw_new_2026_10_tenant_id_idx ON public.sales_stream_raw_2026_10 USING btree (tenant_id);

CREATE INDEX sales_stream_raw_new_2026_10_tenant_id_timestamp_idx ON public.sales_stream_raw_2026_10 USING btree (tenant_id, "timestamp") WHERE is_synthetic;

CREATE INDEX sales_stream_raw_new_2026_10_timestamp_idx ON public.sales_stream_raw_2026_10 USING btree ("timestamp");

CREATE INDEX sales_stream_raw_new_2026_11_store_id_item_id_idx ON public.sales_stream_raw_2026_11 USING btree (store_id, item_id);

CREATE INDEX sales_stream_raw_new_2026_11_tenant_id_idx ON public.sales_stream_raw_2026_11 USING btree (tenant_id);

CREATE INDEX sales_stream_raw_new_2026_11_tenant_id_timestamp_idx ON public.sales_stream_raw_2026_11 USING btree (tenant_id, "timestamp") WHERE is_synthetic;

CREATE INDEX sales_stream_raw_new_2026_11_timestamp_idx ON public.sales_stream_raw_2026_11 USING btree ("timestamp");

CREATE INDEX sales_stream_raw_new_default_store_id_item_id_idx ON public.sales_stream_raw_default USING btree (store_id, item_id);

CREATE INDEX sales_stream_raw_new_default_tenant_id_idx ON public.sales_stream_raw_default USING btree (tenant_id);

CREATE INDEX sales_stream_raw_new_default_tenant_id_timestamp_idx ON public.sales_stream_raw_default USING btree (tenant_id, "timestamp") WHERE is_synthetic;

CREATE INDEX sales_stream_raw_new_default_timestamp_idx ON public.sales_stream_raw_default USING btree ("timestamp");

CREATE UNIQUE INDEX uq_data_sources_one_active_per_tenant ON public.data_sources USING btree (tenant_id) WHERE is_active;

CREATE UNIQUE INDEX uq_flywheel_jobs_live_key ON public.flywheel_jobs USING btree (tenant_id, idempotency_key) WHERE ((idempotency_key IS NOT NULL) AND ((status)::text = ANY ((ARRAY['queued'::character varying, 'running'::character varying, 'failed'::character varying])::text[])));

CREATE UNIQUE INDEX uq_flywheel_ledger_idem ON public.flywheel_budget_ledger USING btree (tenant_id, idempotency_key) WHERE (idempotency_key IS NOT NULL);

CREATE UNIQUE INDEX uq_flywheel_season ON public.flywheel_seasonality_calendar USING btree (tenant_id, name, COALESCE(category, ''::character varying));

CREATE UNIQUE INDEX uq_operations_proposals_idem ON public.operations_proposals USING btree (tenant_id, idempotency_key) WHERE (idempotency_key IS NOT NULL);

CREATE UNIQUE INDEX uq_operations_runs_live_finding ON public.operations_runs USING btree (tenant_id, finding_id) WHERE (status = ANY (ARRAY['analyzing'::text, 'awaiting_approval'::text, 'executing'::text, 'measuring'::text]));

CREATE UNIQUE INDEX uq_scim_external_users_tenant_extid ON public.scim_external_users USING btree (tenant_id, external_id) WHERE (external_id IS NOT NULL);

CREATE UNIQUE INDEX ux_subscriptions_tenant ON public.subscriptions USING btree (tenant_id);

ALTER INDEX public.sales_stream_raw_event_id_key ATTACH PARTITION public.sales_stream_raw_new_2026_08_event_id_timestamp_key;

ALTER INDEX public.sales_stream_raw_pkey ATTACH PARTITION public.sales_stream_raw_new_2026_08_pkey;

ALTER INDEX public.idx_sales_stream_store_item ATTACH PARTITION public.sales_stream_raw_new_2026_08_store_id_item_id_idx;

ALTER INDEX public.idx_sales_stream_raw_tenant ATTACH PARTITION public.sales_stream_raw_new_2026_08_tenant_id_idx;

ALTER INDEX public.idx_sales_stream_synthetic ATTACH PARTITION public.sales_stream_raw_new_2026_08_tenant_id_timestamp_idx;

ALTER INDEX public.idx_sales_stream_timestamp ATTACH PARTITION public.sales_stream_raw_new_2026_08_timestamp_idx;

ALTER INDEX public.sales_stream_raw_event_id_key ATTACH PARTITION public.sales_stream_raw_new_2026_09_event_id_timestamp_key;

ALTER INDEX public.sales_stream_raw_pkey ATTACH PARTITION public.sales_stream_raw_new_2026_09_pkey;

ALTER INDEX public.idx_sales_stream_store_item ATTACH PARTITION public.sales_stream_raw_new_2026_09_store_id_item_id_idx;

ALTER INDEX public.idx_sales_stream_raw_tenant ATTACH PARTITION public.sales_stream_raw_new_2026_09_tenant_id_idx;

ALTER INDEX public.idx_sales_stream_synthetic ATTACH PARTITION public.sales_stream_raw_new_2026_09_tenant_id_timestamp_idx;

ALTER INDEX public.idx_sales_stream_timestamp ATTACH PARTITION public.sales_stream_raw_new_2026_09_timestamp_idx;

ALTER INDEX public.sales_stream_raw_event_id_key ATTACH PARTITION public.sales_stream_raw_new_2026_10_event_id_timestamp_key;

ALTER INDEX public.sales_stream_raw_pkey ATTACH PARTITION public.sales_stream_raw_new_2026_10_pkey;

ALTER INDEX public.idx_sales_stream_store_item ATTACH PARTITION public.sales_stream_raw_new_2026_10_store_id_item_id_idx;

ALTER INDEX public.idx_sales_stream_raw_tenant ATTACH PARTITION public.sales_stream_raw_new_2026_10_tenant_id_idx;

ALTER INDEX public.idx_sales_stream_synthetic ATTACH PARTITION public.sales_stream_raw_new_2026_10_tenant_id_timestamp_idx;

ALTER INDEX public.idx_sales_stream_timestamp ATTACH PARTITION public.sales_stream_raw_new_2026_10_timestamp_idx;

ALTER INDEX public.sales_stream_raw_event_id_key ATTACH PARTITION public.sales_stream_raw_new_2026_11_event_id_timestamp_key;

ALTER INDEX public.sales_stream_raw_pkey ATTACH PARTITION public.sales_stream_raw_new_2026_11_pkey;

ALTER INDEX public.idx_sales_stream_store_item ATTACH PARTITION public.sales_stream_raw_new_2026_11_store_id_item_id_idx;

ALTER INDEX public.idx_sales_stream_raw_tenant ATTACH PARTITION public.sales_stream_raw_new_2026_11_tenant_id_idx;

ALTER INDEX public.idx_sales_stream_synthetic ATTACH PARTITION public.sales_stream_raw_new_2026_11_tenant_id_timestamp_idx;

ALTER INDEX public.idx_sales_stream_timestamp ATTACH PARTITION public.sales_stream_raw_new_2026_11_timestamp_idx;

ALTER INDEX public.sales_stream_raw_event_id_key ATTACH PARTITION public.sales_stream_raw_new_default_event_id_timestamp_key;

ALTER INDEX public.sales_stream_raw_pkey ATTACH PARTITION public.sales_stream_raw_new_default_pkey;

ALTER INDEX public.idx_sales_stream_store_item ATTACH PARTITION public.sales_stream_raw_new_default_store_id_item_id_idx;

ALTER INDEX public.idx_sales_stream_raw_tenant ATTACH PARTITION public.sales_stream_raw_new_default_tenant_id_idx;

ALTER INDEX public.idx_sales_stream_synthetic ATTACH PARTITION public.sales_stream_raw_new_default_tenant_id_timestamp_idx;

ALTER INDEX public.idx_sales_stream_timestamp ATTACH PARTITION public.sales_stream_raw_new_default_timestamp_idx;

CREATE TRIGGER touch_operations_proposals BEFORE UPDATE ON public.operations_proposals FOR EACH ROW EXECUTE FUNCTION public.operations_proposal_touch();

CREATE TRIGGER trg_flywheel_prereg_immutable BEFORE DELETE OR UPDATE ON public.flywheel_preregistrations FOR EACH ROW EXECUTE FUNCTION public.flywheel_forbid_mutation();

CREATE TRIGGER trg_flywheel_readouts_immutable BEFORE DELETE OR UPDATE ON public.flywheel_readouts FOR EACH ROW EXECUTE FUNCTION public.flywheel_forbid_mutation();

CREATE TRIGGER trg_flywheel_settlement_immutable BEFORE UPDATE ON public.flywheel_settlements FOR EACH ROW EXECUTE FUNCTION public.flywheel_settlement_immutable();

CREATE TRIGGER trg_item_costs_sync_current AFTER INSERT OR DELETE OR UPDATE ON public.item_costs FOR EACH ROW EXECUTE FUNCTION public.item_costs_sync_current();

CREATE TRIGGER trg_sales_stream_raw_confine_synthetic BEFORE INSERT OR UPDATE ON public.sales_stream_raw FOR EACH ROW EXECUTE FUNCTION public.sales_stream_raw_confine_synthetic();

CREATE TRIGGER update_emp_performance_updated_at BEFORE UPDATE ON public.employee_performance FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER update_employees_updated_at BEFORE UPDATE ON public.employees FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER update_operations_runs_updated_at BEFORE UPDATE ON public.operations_runs FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER update_tenant_operations_policies_updated_at BEFORE UPDATE ON public.tenant_operations_policies FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER update_user_permissions_updated_at BEFORE UPDATE ON public.user_permissions FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON public.users FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

ALTER TABLE ONLY public.action_drafts
    ADD CONSTRAINT action_drafts_finding_id_fkey FOREIGN KEY (finding_id) REFERENCES public.findings(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.action_drafts
    ADD CONSTRAINT action_drafts_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.alert_notifications
    ADD CONSTRAINT alert_notifications_alert_id_fkey FOREIGN KEY (alert_id) REFERENCES public.alerts(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.alert_notifications
    ADD CONSTRAINT alert_notifications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.alert_rules
    ADD CONSTRAINT alert_rules_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.alert_rules
    ADD CONSTRAINT alert_rules_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id);

ALTER TABLE ONLY public.alert_rules
    ADD CONSTRAINT alert_rules_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id);

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_acknowledged_by_fkey FOREIGN KEY (acknowledged_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_assigned_by_fkey FOREIGN KEY (assigned_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_assigned_to_fkey FOREIGN KEY (assigned_to) REFERENCES public.users(id);

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_escalated_to_fkey FOREIGN KEY (escalated_to) REFERENCES public.users(id);

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id);

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_region_id_fkey FOREIGN KEY (region_id) REFERENCES public.regions(id);

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_resolved_by_fkey FOREIGN KEY (resolved_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id);

ALTER TABLE ONLY public.approval_rules
    ADD CONSTRAINT approval_rules_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.auth_tokens
    ADD CONSTRAINT auth_tokens_invited_by_fkey FOREIGN KEY (invited_by) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.auth_tokens
    ADD CONSTRAINT auth_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.basket_associations
    ADD CONSTRAINT basket_associations_item_a_id_fkey FOREIGN KEY (item_a_id) REFERENCES public.items(id);

ALTER TABLE ONLY public.basket_associations
    ADD CONSTRAINT basket_associations_item_b_id_fkey FOREIGN KEY (item_b_id) REFERENCES public.items(id);

ALTER TABLE ONLY public.bespoke_requests
    ADD CONSTRAINT bespoke_requests_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.campaign_allocations
    ADD CONSTRAINT campaign_allocations_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.retention_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.campaign_allocations
    ADD CONSTRAINT campaign_allocations_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id);

ALTER TABLE ONLY public.campaign_allocations
    ADD CONSTRAINT campaign_allocations_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id);

ALTER TABLE ONLY public.campaign_allocations
    ADD CONSTRAINT campaign_allocations_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.campaign_offers
    ADD CONSTRAINT campaign_offers_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.retention_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.campaign_offers
    ADD CONSTRAINT campaign_offers_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.campaign_offers
    ADD CONSTRAINT campaign_offers_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id);

ALTER TABLE ONLY public.campaign_offers
    ADD CONSTRAINT campaign_offers_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id);

ALTER TABLE ONLY public.campaign_offers
    ADD CONSTRAINT campaign_offers_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.competitor_prices
    ADD CONSTRAINT competitor_prices_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id);

ALTER TABLE ONLY public.competitor_prices
    ADD CONSTRAINT competitor_prices_recorded_by_fkey FOREIGN KEY (recorded_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.competitor_prices
    ADD CONSTRAINT competitor_prices_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id);

ALTER TABLE ONLY public.customer_purchases
    ADD CONSTRAINT customer_purchases_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.customer_purchases
    ADD CONSTRAINT customer_purchases_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id);

ALTER TABLE ONLY public.customer_purchases
    ADD CONSTRAINT customer_purchases_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id);

ALTER TABLE ONLY public.customer_purchases
    ADD CONSTRAINT customer_purchases_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.customers
    ADD CONSTRAINT customers_home_store_id_fkey FOREIGN KEY (home_store_id) REFERENCES public.stores(id);

ALTER TABLE ONLY public.customers
    ADD CONSTRAINT customers_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.data_requests
    ADD CONSTRAINT data_requests_requested_by_fkey FOREIGN KEY (requested_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.data_requests
    ADD CONSTRAINT data_requests_reviewed_by_fkey FOREIGN KEY (reviewed_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.data_requests
    ADD CONSTRAINT data_requests_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id);

ALTER TABLE ONLY public.data_sources
    ADD CONSTRAINT data_sources_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.einvoice_submissions
    ADD CONSTRAINT einvoice_submissions_invoice_id_fkey FOREIGN KEY (invoice_id) REFERENCES public.invoices(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.einvoice_submissions
    ADD CONSTRAINT einvoice_submissions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.employee_attendance
    ADD CONSTRAINT employee_attendance_employee_id_fkey FOREIGN KEY (employee_id) REFERENCES public.employees(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.employee_certifications
    ADD CONSTRAINT employee_certifications_employee_id_fkey FOREIGN KEY (employee_id) REFERENCES public.employees(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.employee_performance
    ADD CONSTRAINT employee_performance_employee_id_fkey FOREIGN KEY (employee_id) REFERENCES public.employees(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.employee_performance
    ADD CONSTRAINT employee_performance_reviewed_by_fkey FOREIGN KEY (reviewed_by) REFERENCES public.employees(id);

ALTER TABLE ONLY public.employee_transactions
    ADD CONSTRAINT employee_transactions_employee_id_fkey FOREIGN KEY (employee_id) REFERENCES public.employees(id);

ALTER TABLE ONLY public.employee_transactions
    ADD CONSTRAINT employee_transactions_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id);

ALTER TABLE ONLY public.employee_transactions
    ADD CONSTRAINT employee_transactions_voided_by_fkey FOREIGN KEY (voided_by) REFERENCES public.employees(id);

ALTER TABLE ONLY public.employees
    ADD CONSTRAINT employees_region_id_fkey FOREIGN KEY (region_id) REFERENCES public.regions(id);

ALTER TABLE ONLY public.employees
    ADD CONSTRAINT employees_reports_to_fkey FOREIGN KEY (reports_to) REFERENCES public.employees(id);

ALTER TABLE ONLY public.employees
    ADD CONSTRAINT employees_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id);

ALTER TABLE ONLY public.employees
    ADD CONSTRAINT employees_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.external_identities
    ADD CONSTRAINT external_identities_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.tenant_sso_providers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.external_identities
    ADD CONSTRAINT external_identities_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.external_identities
    ADD CONSTRAINT external_identities_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.operations_events
    ADD CONSTRAINT fk_operations_events_proposal FOREIGN KEY (tenant_id, proposal_id) REFERENCES public.operations_proposals(tenant_id, id);

ALTER TABLE ONLY public.operations_events
    ADD CONSTRAINT fk_operations_events_run FOREIGN KEY (tenant_id, run_id) REFERENCES public.operations_runs(tenant_id, id);

ALTER TABLE ONLY public.operations_proposals
    ADD CONSTRAINT fk_operations_proposals_run FOREIGN KEY (tenant_id, run_id) REFERENCES public.operations_runs(tenant_id, id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_allocation_lines
    ADD CONSTRAINT flywheel_allocation_lines_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.flywheel_customers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_allocation_lines
    ADD CONSTRAINT flywheel_allocation_lines_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_allocation_lines
    ADD CONSTRAINT flywheel_allocation_lines_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.flywheel_allocation_runs(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_allocation_lines
    ADD CONSTRAINT flywheel_allocation_lines_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_allocation_lines
    ADD CONSTRAINT flywheel_allocation_lines_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_allocation_runs
    ADD CONSTRAINT flywheel_allocation_runs_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_allocation_runs
    ADD CONSTRAINT flywheel_allocation_runs_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_approval_policies
    ADD CONSTRAINT flywheel_approval_policies_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_approval_requests
    ADD CONSTRAINT flywheel_approval_requests_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_approval_requests
    ADD CONSTRAINT flywheel_approval_requests_requested_by_fkey FOREIGN KEY (requested_by) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_approval_requests
    ADD CONSTRAINT flywheel_approval_requests_requisition_id_fkey FOREIGN KEY (requisition_id) REFERENCES public.flywheel_procurement_requisitions(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_approval_requests
    ADD CONSTRAINT flywheel_approval_requests_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_approval_steps
    ADD CONSTRAINT flywheel_approval_steps_decided_by_fkey FOREIGN KEY (decided_by) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_approval_steps
    ADD CONSTRAINT flywheel_approval_steps_policy_id_fkey FOREIGN KEY (policy_id) REFERENCES public.flywheel_approval_policies(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_approval_steps
    ADD CONSTRAINT flywheel_approval_steps_request_id_fkey FOREIGN KEY (request_id) REFERENCES public.flywheel_approval_requests(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_approval_steps
    ADD CONSTRAINT flywheel_approval_steps_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_budget_ledger
    ADD CONSTRAINT flywheel_budget_ledger_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_budget_ledger
    ADD CONSTRAINT flywheel_budget_ledger_budget_id_fkey FOREIGN KEY (budget_id) REFERENCES public.flywheel_budgets(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_budget_ledger
    ADD CONSTRAINT flywheel_budget_ledger_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_budget_ledger
    ADD CONSTRAINT flywheel_budget_ledger_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_budgets
    ADD CONSTRAINT flywheel_budgets_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_campaign_audience
    ADD CONSTRAINT flywheel_campaign_audience_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_campaign_audience
    ADD CONSTRAINT flywheel_campaign_audience_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.flywheel_customers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_campaign_audience
    ADD CONSTRAINT flywheel_campaign_audience_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_campaign_outcomes
    ADD CONSTRAINT flywheel_campaign_outcomes_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_campaign_outcomes
    ADD CONSTRAINT flywheel_campaign_outcomes_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_campaign_transitions
    ADD CONSTRAINT flywheel_campaign_transitions_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_campaign_transitions
    ADD CONSTRAINT flywheel_campaign_transitions_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_campaign_transitions
    ADD CONSTRAINT flywheel_campaign_transitions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_campaigns
    ADD CONSTRAINT flywheel_campaigns_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_campaigns
    ADD CONSTRAINT flywheel_campaigns_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_cannibalization
    ADD CONSTRAINT flywheel_cannibalization_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_cannibalization
    ADD CONSTRAINT flywheel_cannibalization_promoted_item_id_fkey FOREIGN KEY (promoted_item_id) REFERENCES public.items(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_cannibalization
    ADD CONSTRAINT flywheel_cannibalization_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_churn_predictions
    ADD CONSTRAINT flywheel_churn_predictions_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.flywheel_customers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_churn_predictions
    ADD CONSTRAINT flywheel_churn_predictions_model_version_id_fkey FOREIGN KEY (model_version_id) REFERENCES public.flywheel_model_versions(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.flywheel_churn_predictions
    ADD CONSTRAINT flywheel_churn_predictions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_coalition_activity
    ADD CONSTRAINT flywheel_coalition_activity_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.flywheel_customers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_coalition_activity
    ADD CONSTRAINT flywheel_coalition_activity_partner_id_fkey FOREIGN KEY (partner_id) REFERENCES public.flywheel_coalition_partners(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_coalition_activity
    ADD CONSTRAINT flywheel_coalition_activity_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_coalition_attribution
    ADD CONSTRAINT flywheel_coalition_attribution_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_coalition_attribution
    ADD CONSTRAINT flywheel_coalition_attribution_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.flywheel_customers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_coalition_attribution
    ADD CONSTRAINT flywheel_coalition_attribution_partner_id_fkey FOREIGN KEY (partner_id) REFERENCES public.flywheel_coalition_partners(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_coalition_attribution
    ADD CONSTRAINT flywheel_coalition_attribution_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_coalition_partners
    ADD CONSTRAINT flywheel_coalition_partners_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_contact_log
    ADD CONSTRAINT flywheel_contact_log_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_contact_log
    ADD CONSTRAINT flywheel_contact_log_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.flywheel_customers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_contact_log
    ADD CONSTRAINT flywheel_contact_log_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_contact_policy
    ADD CONSTRAINT flywheel_contact_policy_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_customer_consents
    ADD CONSTRAINT flywheel_customer_consents_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.flywheel_customers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_customer_consents
    ADD CONSTRAINT flywheel_customer_consents_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_customer_events
    ADD CONSTRAINT flywheel_customer_events_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.flywheel_customers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_customer_events
    ADD CONSTRAINT flywheel_customer_events_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_customer_events
    ADD CONSTRAINT flywheel_customer_events_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_customer_events
    ADD CONSTRAINT flywheel_customer_events_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_customers
    ADD CONSTRAINT flywheel_customers_home_store_id_fkey FOREIGN KEY (home_store_id) REFERENCES public.stores(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.flywheel_customers
    ADD CONSTRAINT flywheel_customers_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_decisions
    ADD CONSTRAINT flywheel_decisions_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_decisions
    ADD CONSTRAINT flywheel_decisions_churn_model_version_id_fkey FOREIGN KEY (churn_model_version_id) REFERENCES public.flywheel_model_versions(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_decisions
    ADD CONSTRAINT flywheel_decisions_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.flywheel_customers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_decisions
    ADD CONSTRAINT flywheel_decisions_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_decisions
    ADD CONSTRAINT flywheel_decisions_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_decisions
    ADD CONSTRAINT flywheel_decisions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_decisions
    ADD CONSTRAINT flywheel_decisions_uplift_model_version_id_fkey FOREIGN KEY (uplift_model_version_id) REFERENCES public.flywheel_model_versions(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_delivery_receipts
    ADD CONSTRAINT flywheel_delivery_receipts_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_feature_snapshots
    ADD CONSTRAINT flywheel_feature_snapshots_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.flywheel_customers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_feature_snapshots
    ADD CONSTRAINT flywheel_feature_snapshots_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_holdout_balance
    ADD CONSTRAINT flywheel_holdout_balance_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_holdout_balance
    ADD CONSTRAINT flywheel_holdout_balance_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_identity_links
    ADD CONSTRAINT flywheel_identity_links_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.flywheel_customers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_identity_links
    ADD CONSTRAINT flywheel_identity_links_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_inventory_allocations
    ADD CONSTRAINT flywheel_inventory_allocations_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_inventory_allocations
    ADD CONSTRAINT flywheel_inventory_allocations_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_inventory_allocations
    ADD CONSTRAINT flywheel_inventory_allocations_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_inventory_allocations
    ADD CONSTRAINT flywheel_inventory_allocations_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_jobs
    ADD CONSTRAINT flywheel_jobs_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_model_versions
    ADD CONSTRAINT flywheel_model_versions_promoted_by_fkey FOREIGN KEY (promoted_by) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_model_versions
    ADD CONSTRAINT flywheel_model_versions_rolled_back_to_fkey FOREIGN KEY (rolled_back_to) REFERENCES public.flywheel_model_versions(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_model_versions
    ADD CONSTRAINT flywheel_model_versions_superseded_by_fkey FOREIGN KEY (superseded_by) REFERENCES public.flywheel_model_versions(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_model_versions
    ADD CONSTRAINT flywheel_model_versions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_offer_response_predictions
    ADD CONSTRAINT flywheel_offer_response_predictions_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.flywheel_customers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_offer_response_predictions
    ADD CONSTRAINT flywheel_offer_response_predictions_model_version_id_fkey FOREIGN KEY (model_version_id) REFERENCES public.flywheel_model_versions(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.flywheel_offer_response_predictions
    ADD CONSTRAINT flywheel_offer_response_predictions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_offer_suppressions
    ADD CONSTRAINT flywheel_offer_suppressions_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.flywheel_customers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_offer_suppressions
    ADD CONSTRAINT flywheel_offer_suppressions_suppressed_campaign_id_fkey FOREIGN KEY (suppressed_campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_offer_suppressions
    ADD CONSTRAINT flywheel_offer_suppressions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_offer_suppressions
    ADD CONSTRAINT flywheel_offer_suppressions_winning_campaign_id_fkey FOREIGN KEY (winning_campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_offers
    ADD CONSTRAINT flywheel_offers_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_offers
    ADD CONSTRAINT flywheel_offers_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.flywheel_customers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_offers
    ADD CONSTRAINT flywheel_offers_decision_id_fkey FOREIGN KEY (decision_id) REFERENCES public.flywheel_decisions(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_offers
    ADD CONSTRAINT flywheel_offers_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_offers
    ADD CONSTRAINT flywheel_offers_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_offers
    ADD CONSTRAINT flywheel_offers_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_outbox
    ADD CONSTRAINT flywheel_outbox_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_outcome_pricing
    ADD CONSTRAINT flywheel_outcome_pricing_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_pos_staging
    ADD CONSTRAINT flywheel_pos_staging_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_pos_staging
    ADD CONSTRAINT flywheel_pos_staging_matched_customer_id_fkey FOREIGN KEY (matched_customer_id) REFERENCES public.flywheel_customers(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_pos_staging
    ADD CONSTRAINT flywheel_pos_staging_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_pos_staging
    ADD CONSTRAINT flywheel_pos_staging_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_preregistrations
    ADD CONSTRAINT flywheel_preregistrations_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_preregistrations
    ADD CONSTRAINT flywheel_preregistrations_registered_by_fkey FOREIGN KEY (registered_by) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_preregistrations
    ADD CONSTRAINT flywheel_preregistrations_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_procurement_requisitions
    ADD CONSTRAINT flywheel_procurement_requisitions_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_procurement_requisitions
    ADD CONSTRAINT flywheel_procurement_requisitions_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_procurement_requisitions
    ADD CONSTRAINT flywheel_procurement_requisitions_purchase_order_id_fkey FOREIGN KEY (purchase_order_id) REFERENCES public.purchase_orders(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_procurement_requisitions
    ADD CONSTRAINT flywheel_procurement_requisitions_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_procurement_requisitions
    ADD CONSTRAINT flywheel_procurement_requisitions_supplier_id_fkey FOREIGN KEY (supplier_id) REFERENCES public.suppliers(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_procurement_requisitions
    ADD CONSTRAINT flywheel_procurement_requisitions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_profiling_objections
    ADD CONSTRAINT flywheel_profiling_objections_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.flywheel_customers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_profiling_objections
    ADD CONSTRAINT flywheel_profiling_objections_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_promotion_criteria
    ADD CONSTRAINT flywheel_promotion_criteria_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_purchase_attributions
    ADD CONSTRAINT flywheel_purchase_attributions_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.flywheel_customer_events(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_purchase_attributions
    ADD CONSTRAINT flywheel_purchase_attributions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_readouts
    ADD CONSTRAINT flywheel_readouts_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_readouts
    ADD CONSTRAINT flywheel_readouts_preregistration_id_fkey FOREIGN KEY (preregistration_id) REFERENCES public.flywheel_preregistrations(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_readouts
    ADD CONSTRAINT flywheel_readouts_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_redemptions
    ADD CONSTRAINT flywheel_redemptions_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_redemptions
    ADD CONSTRAINT flywheel_redemptions_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.flywheel_customers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_redemptions
    ADD CONSTRAINT flywheel_redemptions_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_redemptions
    ADD CONSTRAINT flywheel_redemptions_offer_id_fkey FOREIGN KEY (offer_id) REFERENCES public.flywheel_offers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_redemptions
    ADD CONSTRAINT flywheel_redemptions_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.flywheel_redemptions
    ADD CONSTRAINT flywheel_redemptions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_returns
    ADD CONSTRAINT flywheel_returns_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_returns
    ADD CONSTRAINT flywheel_returns_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.flywheel_customers(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_returns
    ADD CONSTRAINT flywheel_returns_redemption_id_fkey FOREIGN KEY (redemption_id) REFERENCES public.flywheel_redemptions(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_returns
    ADD CONSTRAINT flywheel_returns_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_seasonality_calendar
    ADD CONSTRAINT flywheel_seasonality_calendar_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_settlements
    ADD CONSTRAINT flywheel_settlements_funding_id_fkey FOREIGN KEY (funding_id) REFERENCES public.flywheel_supplier_funding(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_settlements
    ADD CONSTRAINT flywheel_settlements_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_shadow_decisions
    ADD CONSTRAINT flywheel_shadow_decisions_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_shadow_decisions
    ADD CONSTRAINT flywheel_shadow_decisions_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.flywheel_customers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_shadow_decisions
    ADD CONSTRAINT flywheel_shadow_decisions_decision_id_fkey FOREIGN KEY (decision_id) REFERENCES public.flywheel_decisions(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_shadow_decisions
    ADD CONSTRAINT flywheel_shadow_decisions_model_version_id_fkey FOREIGN KEY (model_version_id) REFERENCES public.flywheel_model_versions(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_shadow_decisions
    ADD CONSTRAINT flywheel_shadow_decisions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_shelf_life
    ADD CONSTRAINT flywheel_shelf_life_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_shelf_life
    ADD CONSTRAINT flywheel_shelf_life_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_shelf_life
    ADD CONSTRAINT flywheel_shelf_life_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_substitution
    ADD CONSTRAINT flywheel_substitution_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_substitution
    ADD CONSTRAINT flywheel_substitution_from_item_id_fkey FOREIGN KEY (from_item_id) REFERENCES public.items(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_substitution
    ADD CONSTRAINT flywheel_substitution_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_substitution
    ADD CONSTRAINT flywheel_substitution_to_item_id_fkey FOREIGN KEY (to_item_id) REFERENCES public.items(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_supplier_funding
    ADD CONSTRAINT flywheel_supplier_funding_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_supplier_funding
    ADD CONSTRAINT flywheel_supplier_funding_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_supplier_funding_skus
    ADD CONSTRAINT flywheel_supplier_funding_skus_funding_id_fkey FOREIGN KEY (funding_id) REFERENCES public.flywheel_supplier_funding(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_supplier_funding_skus
    ADD CONSTRAINT flywheel_supplier_funding_skus_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_supplier_funding_skus
    ADD CONSTRAINT flywheel_supplier_funding_skus_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_supplier_funding
    ADD CONSTRAINT flywheel_supplier_funding_supplier_id_fkey FOREIGN KEY (supplier_id) REFERENCES public.suppliers(id) ON DELETE RESTRICT;

ALTER TABLE ONLY public.flywheel_supplier_funding
    ADD CONSTRAINT flywheel_supplier_funding_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_tax_rules
    ADD CONSTRAINT flywheel_tax_rules_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_transfer_recommendations
    ADD CONSTRAINT flywheel_transfer_recommendations_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.flywheel_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_transfer_recommendations
    ADD CONSTRAINT flywheel_transfer_recommendations_from_store_id_fkey FOREIGN KEY (from_store_id) REFERENCES public.stores(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_transfer_recommendations
    ADD CONSTRAINT flywheel_transfer_recommendations_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_transfer_recommendations
    ADD CONSTRAINT flywheel_transfer_recommendations_stock_transfer_id_fkey FOREIGN KEY (stock_transfer_id) REFERENCES public.stock_transfers(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.flywheel_transfer_recommendations
    ADD CONSTRAINT flywheel_transfer_recommendations_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.flywheel_transfer_recommendations
    ADD CONSTRAINT flywheel_transfer_recommendations_to_store_id_fkey FOREIGN KEY (to_store_id) REFERENCES public.stores(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.goods_receipt_lines
    ADD CONSTRAINT goods_receipt_lines_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.goods_receipt_lines
    ADD CONSTRAINT goods_receipt_lines_po_line_id_fkey FOREIGN KEY (po_line_id) REFERENCES public.purchase_order_lines(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.goods_receipt_lines
    ADD CONSTRAINT goods_receipt_lines_receipt_id_fkey FOREIGN KEY (receipt_id) REFERENCES public.goods_receipts(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.goods_receipts
    ADD CONSTRAINT goods_receipts_po_id_fkey FOREIGN KEY (po_id) REFERENCES public.purchase_orders(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.goods_receipts
    ADD CONSTRAINT goods_receipts_received_by_fkey FOREIGN KEY (received_by) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.goods_receipts
    ADD CONSTRAINT goods_receipts_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.import_jobs
    ADD CONSTRAINT import_jobs_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.import_row_undo
    ADD CONSTRAINT import_row_undo_import_job_id_fkey FOREIGN KEY (import_job_id) REFERENCES public.import_jobs(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.import_row_undo
    ADD CONSTRAINT import_row_undo_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.import_schedules
    ADD CONSTRAINT import_schedules_last_job_id_fkey FOREIGN KEY (last_job_id) REFERENCES public.import_jobs(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.import_schedules
    ADD CONSTRAINT import_schedules_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.inventory_batches
    ADD CONSTRAINT inventory_batches_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id);

ALTER TABLE ONLY public.inventory_batches
    ADD CONSTRAINT inventory_batches_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id);

ALTER TABLE ONLY public.inventory
    ADD CONSTRAINT inventory_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id);

ALTER TABLE ONLY public.inventory
    ADD CONSTRAINT inventory_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id);

ALTER TABLE ONLY public.inventory_transactions
    ADD CONSTRAINT inventory_transactions_inventory_id_fkey FOREIGN KEY (inventory_id) REFERENCES public.inventory(id);

ALTER TABLE ONLY public.inventory_transactions
    ADD CONSTRAINT inventory_transactions_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id);

ALTER TABLE ONLY public.inventory_transactions
    ADD CONSTRAINT inventory_transactions_performed_by_fkey FOREIGN KEY (performed_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.inventory_transactions
    ADD CONSTRAINT inventory_transactions_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id);

ALTER TABLE ONLY public.invoice_lines
    ADD CONSTRAINT invoice_lines_invoice_id_fkey FOREIGN KEY (invoice_id) REFERENCES public.invoices(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.item_costs
    ADD CONSTRAINT item_costs_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.item_costs
    ADD CONSTRAINT item_costs_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id);

ALTER TABLE ONLY public.items
    ADD CONSTRAINT items_import_job_fk FOREIGN KEY (import_job_id) REFERENCES public.import_jobs(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.items
    ADD CONSTRAINT items_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id);

ALTER TABLE ONLY public.notification_preferences
    ADD CONSTRAINT notification_preferences_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.notification_preferences
    ADD CONSTRAINT notification_preferences_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.operations_events
    ADD CONSTRAINT operations_events_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.operations_proposals
    ADD CONSTRAINT operations_proposals_finding_id_fkey FOREIGN KEY (finding_id) REFERENCES public.findings(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.operations_proposals
    ADD CONSTRAINT operations_proposals_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.operations_runs
    ADD CONSTRAINT operations_runs_finding_id_fkey FOREIGN KEY (finding_id) REFERENCES public.findings(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.operations_runs
    ADD CONSTRAINT operations_runs_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.outcome_pricing_plans
    ADD CONSTRAINT outcome_pricing_plans_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.payment_intents
    ADD CONSTRAINT payment_intents_invoice_id_fkey FOREIGN KEY (invoice_id) REFERENCES public.invoices(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.payment_intents
    ADD CONSTRAINT payment_intents_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.payment_webhook_events
    ADD CONSTRAINT payment_webhook_events_intent_id_fkey FOREIGN KEY (intent_id) REFERENCES public.payment_intents(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.pos_connections
    ADD CONSTRAINT pos_connections_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.pos_sync_runs
    ADD CONSTRAINT pos_sync_runs_connection_id_fkey FOREIGN KEY (connection_id) REFERENCES public.pos_connections(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.pos_sync_runs
    ADD CONSTRAINT pos_sync_runs_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.predictions
    ADD CONSTRAINT predictions_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id);

ALTER TABLE ONLY public.predictions
    ADD CONSTRAINT predictions_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id);

ALTER TABLE ONLY public.procurement_events
    ADD CONSTRAINT procurement_events_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.procurement_events
    ADD CONSTRAINT procurement_events_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.product_suppliers
    ADD CONSTRAINT product_suppliers_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.product_suppliers
    ADD CONSTRAINT product_suppliers_supplier_id_fkey FOREIGN KEY (supplier_id) REFERENCES public.suppliers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.product_suppliers
    ADD CONSTRAINT product_suppliers_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.promotion_items
    ADD CONSTRAINT promotion_items_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id);

ALTER TABLE ONLY public.promotion_items
    ADD CONSTRAINT promotion_items_promotion_id_fkey FOREIGN KEY (promotion_id) REFERENCES public.promotions(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.promotion_stores
    ADD CONSTRAINT promotion_stores_promotion_id_fkey FOREIGN KEY (promotion_id) REFERENCES public.promotions(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.promotion_stores
    ADD CONSTRAINT promotion_stores_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id);

ALTER TABLE ONLY public.promotions
    ADD CONSTRAINT promotions_approved_by_fkey FOREIGN KEY (approved_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.promotions
    ADD CONSTRAINT promotions_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.promotions
    ADD CONSTRAINT promotions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id);

ALTER TABLE ONLY public.purchase_order_lines
    ADD CONSTRAINT purchase_order_lines_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.purchase_order_lines
    ADD CONSTRAINT purchase_order_lines_po_id_fkey FOREIGN KEY (po_id) REFERENCES public.purchase_orders(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.purchase_orders
    ADD CONSTRAINT purchase_orders_approved_by_fkey FOREIGN KEY (approved_by) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.purchase_orders
    ADD CONSTRAINT purchase_orders_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.purchase_orders
    ADD CONSTRAINT purchase_orders_supplier_id_fkey FOREIGN KEY (supplier_id) REFERENCES public.suppliers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.purchase_orders
    ADD CONSTRAINT purchase_orders_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.report_history
    ADD CONSTRAINT report_history_generated_by_fkey FOREIGN KEY (generated_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.report_history
    ADD CONSTRAINT report_history_scheduled_report_id_fkey FOREIGN KEY (scheduled_report_id) REFERENCES public.scheduled_reports(id);

ALTER TABLE ONLY public.retention_budget_ledger
    ADD CONSTRAINT retention_budget_ledger_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.retention_budget_ledger
    ADD CONSTRAINT retention_budget_ledger_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES public.retention_campaigns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.retention_budget_ledger
    ADD CONSTRAINT retention_budget_ledger_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.retention_campaigns
    ADD CONSTRAINT retention_campaigns_approved_by_fkey FOREIGN KEY (approved_by) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.retention_campaigns
    ADD CONSTRAINT retention_campaigns_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.retention_campaigns
    ADD CONSTRAINT retention_campaigns_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id);

ALTER TABLE ONLY public.retention_campaigns
    ADD CONSTRAINT retention_campaigns_requisition_po_id_fkey FOREIGN KEY (requisition_po_id) REFERENCES public.purchase_orders(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.retention_campaigns
    ADD CONSTRAINT retention_campaigns_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id);

ALTER TABLE ONLY public.retention_campaigns
    ADD CONSTRAINT retention_campaigns_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.retention_events
    ADD CONSTRAINT retention_events_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.retention_events
    ADD CONSTRAINT retention_events_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.sales_historical
    ADD CONSTRAINT sales_historical_import_job_fk FOREIGN KEY (import_job_id) REFERENCES public.import_jobs(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.sales_historical
    ADD CONSTRAINT sales_historical_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id);

ALTER TABLE ONLY public.sales_historical
    ADD CONSTRAINT sales_historical_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id);

ALTER TABLE public.sales_stream_raw
    ADD CONSTRAINT sales_stream_raw_new_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id);

ALTER TABLE public.sales_stream_raw
    ADD CONSTRAINT sales_stream_raw_new_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id);

ALTER TABLE ONLY public.scheduled_reports
    ADD CONSTRAINT scheduled_reports_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.scim_external_users
    ADD CONSTRAINT scim_external_users_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.scim_external_users
    ADD CONSTRAINT scim_external_users_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.scim_group_memberships
    ADD CONSTRAINT scim_group_memberships_group_id_fkey FOREIGN KEY (group_id) REFERENCES public.scim_groups(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.scim_group_memberships
    ADD CONSTRAINT scim_group_memberships_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.scim_group_memberships
    ADD CONSTRAINT scim_group_memberships_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.scim_group_role_mappings
    ADD CONSTRAINT scim_group_role_mappings_group_id_fkey FOREIGN KEY (group_id) REFERENCES public.scim_groups(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.scim_group_role_mappings
    ADD CONSTRAINT scim_group_role_mappings_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.scim_groups
    ADD CONSTRAINT scim_groups_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.shrinkage_records
    ADD CONSTRAINT shrinkage_records_investigated_by_fkey FOREIGN KEY (investigated_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.shrinkage_records
    ADD CONSTRAINT shrinkage_records_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id);

ALTER TABLE ONLY public.shrinkage_records
    ADD CONSTRAINT shrinkage_records_reported_by_fkey FOREIGN KEY (reported_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.shrinkage_records
    ADD CONSTRAINT shrinkage_records_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id);

ALTER TABLE ONLY public.sso_auth_states
    ADD CONSTRAINT sso_auth_states_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.tenant_sso_providers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.sso_auth_states
    ADD CONSTRAINT sso_auth_states_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.stock_transfer_items
    ADD CONSTRAINT stock_transfer_items_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id);

ALTER TABLE ONLY public.stock_transfer_items
    ADD CONSTRAINT stock_transfer_items_transfer_id_fkey FOREIGN KEY (transfer_id) REFERENCES public.stock_transfers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.stock_transfers
    ADD CONSTRAINT stock_transfers_approved_by_fkey FOREIGN KEY (approved_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.stock_transfers
    ADD CONSTRAINT stock_transfers_completed_by_fkey FOREIGN KEY (completed_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.stock_transfers
    ADD CONSTRAINT stock_transfers_from_store_id_fkey FOREIGN KEY (from_store_id) REFERENCES public.stores(id);

ALTER TABLE ONLY public.stock_transfers
    ADD CONSTRAINT stock_transfers_requested_by_fkey FOREIGN KEY (requested_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.stock_transfers
    ADD CONSTRAINT stock_transfers_to_store_id_fkey FOREIGN KEY (to_store_id) REFERENCES public.stores(id);

ALTER TABLE ONLY public.stores
    ADD CONSTRAINT stores_import_job_fk FOREIGN KEY (import_job_id) REFERENCES public.import_jobs(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.stores
    ADD CONSTRAINT stores_region_id_fkey FOREIGN KEY (region_id) REFERENCES public.regions(id);

ALTER TABLE ONLY public.stores
    ADD CONSTRAINT stores_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id);

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT subscriptions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.supplier_invoice_lines
    ADD CONSTRAINT supplier_invoice_lines_invoice_id_fkey FOREIGN KEY (invoice_id) REFERENCES public.supplier_invoices(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.supplier_invoice_lines
    ADD CONSTRAINT supplier_invoice_lines_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.supplier_invoices
    ADD CONSTRAINT supplier_invoices_po_id_fkey FOREIGN KEY (po_id) REFERENCES public.purchase_orders(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.supplier_invoices
    ADD CONSTRAINT supplier_invoices_supplier_id_fkey FOREIGN KEY (supplier_id) REFERENCES public.suppliers(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.supplier_invoices
    ADD CONSTRAINT supplier_invoices_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.suppliers
    ADD CONSTRAINT suppliers_import_job_fk FOREIGN KEY (import_job_id) REFERENCES public.import_jobs(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.suppliers
    ADD CONSTRAINT suppliers_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.tenant_admin_notes
    ADD CONSTRAINT tenant_admin_notes_author_id_fkey FOREIGN KEY (author_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.tenant_admin_notes
    ADD CONSTRAINT tenant_admin_notes_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.tenant_api_keys
    ADD CONSTRAINT tenant_api_keys_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.tenant_api_keys
    ADD CONSTRAINT tenant_api_keys_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.tenant_billing_profile
    ADD CONSTRAINT tenant_billing_profile_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.tenant_operations_policies
    ADD CONSTRAINT tenant_operations_policies_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.tenant_provisioning
    ADD CONSTRAINT tenant_provisioning_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.tenant_scim_tokens
    ADD CONSTRAINT tenant_scim_tokens_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.tenant_scim_tokens
    ADD CONSTRAINT tenant_scim_tokens_revoked_by_user_id_fkey FOREIGN KEY (revoked_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.tenant_scim_tokens
    ADD CONSTRAINT tenant_scim_tokens_rotated_from_token_id_fkey FOREIGN KEY (rotated_from_token_id) REFERENCES public.tenant_scim_tokens(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.tenant_scim_tokens
    ADD CONSTRAINT tenant_scim_tokens_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.tenant_sso_providers
    ADD CONSTRAINT tenant_sso_providers_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.tenant_status_events
    ADD CONSTRAINT tenant_status_events_changed_by_fkey FOREIGN KEY (changed_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.tenant_status_events
    ADD CONSTRAINT tenant_status_events_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.tenant_webhooks
    ADD CONSTRAINT tenant_webhooks_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.tenant_webhooks
    ADD CONSTRAINT tenant_webhooks_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.tenants
    ADD CONSTRAINT tenants_status_changed_by_fkey FOREIGN KEY (status_changed_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.transaction_lines
    ADD CONSTRAINT transaction_lines_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id);

ALTER TABLE ONLY public.transaction_lines
    ADD CONSTRAINT transaction_lines_transaction_id_fkey FOREIGN KEY (transaction_id) REFERENCES public.transactions(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_cashier_employee_id_fkey FOREIGN KEY (cashier_employee_id) REFERENCES public.employees(id);

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id);

ALTER TABLE ONLY public.transactions
    ADD CONSTRAINT transactions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id);

ALTER TABLE ONLY public.usage_events
    ADD CONSTRAINT usage_events_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.user_feedback
    ADD CONSTRAINT user_feedback_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.user_feedback
    ADD CONSTRAINT user_feedback_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.user_permissions
    ADD CONSTRAINT user_permissions_region_id_fkey FOREIGN KEY (region_id) REFERENCES public.regions(id);

ALTER TABLE ONLY public.user_permissions
    ADD CONSTRAINT user_permissions_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.stores(id);

ALTER TABLE ONLY public.user_permissions
    ADD CONSTRAINT user_permissions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.user_sessions
    ADD CONSTRAINT user_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id);

ALTER TABLE ONLY public.value_realizations
    ADD CONSTRAINT value_realizations_finding_id_fkey FOREIGN KEY (finding_id) REFERENCES public.findings(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.value_realizations
    ADD CONSTRAINT value_realizations_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;

ALTER TABLE public.action_drafts ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.approval_rules ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.campaign_allocations ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.campaign_offers ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.company_targets ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.crm_opportunities ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.customer_purchases ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.customers ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.data_requests ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.data_sources ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.distributors ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.einvoice_submissions ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.findings ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_allocation_lines ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_allocation_runs ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_approval_policies ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_approval_requests ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_approval_steps ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_budget_ledger ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_budgets ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_campaign_audience ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_campaign_outcomes ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_campaign_transitions ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_campaigns ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_cannibalization ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_churn_predictions ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_coalition_activity ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_coalition_attribution ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_coalition_partners ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_contact_log ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_contact_policy ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_customer_consents ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_customer_events ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_customers ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_decisions ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_delivery_receipts ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_feature_snapshots ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_holdout_balance ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_identity_links ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_inventory_allocations ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_jobs ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_model_versions ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_offer_response_predictions ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_offer_suppressions ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_offers ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_outbox ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_outcome_pricing ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_pos_staging ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_preregistrations ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_procurement_requisitions ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_profiling_objections ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_promotion_criteria ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_purchase_attributions ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_readouts ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_redemptions ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_returns ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_seasonality_calendar ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_settlements ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_shadow_decisions ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_shelf_life ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_substitution ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_supplier_funding ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_supplier_funding_skus ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_tax_rules ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.flywheel_transfer_recommendations ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.goods_receipt_lines ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.goods_receipts ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.import_jobs ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.import_row_undo ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.import_schedules ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.invoice_lines ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.invoices ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.item_costs ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.items ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.notification_preferences ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.online_prices ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.operations_events ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.operations_proposals ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.operations_runs ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.outcome_pricing_plans ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.payment_intents ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.pos_connections ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.pos_sync_runs ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.procurement_events ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.product_suppliers ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.promotion_items ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.promotion_stores ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.promotions ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.purchase_order_lines ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.purchase_orders ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.retention_budget_ledger ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.retention_campaigns ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.retention_events ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.sales_historical ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.sales_stream_raw ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.security_events ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.stores ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.supplier_invoice_lines ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.supplier_invoices ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.suppliers ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.tenant_api_keys ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.tenant_billing_profile ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON public.action_drafts USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.approval_rules USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.campaign_allocations USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.campaign_offers USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.company_targets USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.crm_opportunities USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.customer_purchases USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.customers USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.data_requests USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.data_sources USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.distributors USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.documents USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.einvoice_submissions USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.findings USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_allocation_lines USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_allocation_runs USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_approval_policies USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_approval_requests USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_approval_steps USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_budget_ledger USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_budgets USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_campaign_audience USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_campaign_outcomes USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_campaign_transitions USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_campaigns USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_cannibalization USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_churn_predictions USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_coalition_activity USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_coalition_attribution USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_coalition_partners USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_contact_log USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_contact_policy USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_customer_consents USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_customer_events USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_customers USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_decisions USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_delivery_receipts USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_feature_snapshots USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_holdout_balance USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_identity_links USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_inventory_allocations USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_jobs USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_model_versions USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_offer_response_predictions USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_offer_suppressions USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_offers USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_outbox USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_outcome_pricing USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_pos_staging USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_preregistrations USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_procurement_requisitions USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_profiling_objections USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_promotion_criteria USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_purchase_attributions USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_readouts USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_redemptions USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_returns USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_seasonality_calendar USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_settlements USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_shadow_decisions USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_shelf_life USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_substitution USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_supplier_funding USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_supplier_funding_skus USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_tax_rules USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.flywheel_transfer_recommendations USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.goods_receipt_lines USING ((EXISTS ( SELECT 1
   FROM public.goods_receipts r
  WHERE ((r.id = goods_receipt_lines.receipt_id) AND (r.tenant_id = public.current_tenant_id())))));

CREATE POLICY tenant_isolation ON public.goods_receipts USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.import_jobs USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.import_row_undo USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.import_schedules USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.invoice_lines USING ((EXISTS ( SELECT 1
   FROM public.invoices i
  WHERE ((i.id = invoice_lines.invoice_id) AND (i.tenant_id = public.current_tenant_id())))));

CREATE POLICY tenant_isolation ON public.invoices USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.item_costs USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.items USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.notification_preferences USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.notifications USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.online_prices USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.operations_events USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.operations_proposals USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.operations_runs USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.outcome_pricing_plans USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.payment_intents USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.pos_connections USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.pos_sync_runs USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.procurement_events USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.product_suppliers USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.promotion_items USING ((EXISTS ( SELECT 1
   FROM public.promotions p
  WHERE ((p.id = promotion_items.promotion_id) AND (p.tenant_id = public.current_tenant_id())))));

CREATE POLICY tenant_isolation ON public.promotion_stores USING ((EXISTS ( SELECT 1
   FROM public.promotions p
  WHERE ((p.id = promotion_stores.promotion_id) AND (p.tenant_id = public.current_tenant_id())))));

CREATE POLICY tenant_isolation ON public.promotions USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.purchase_order_lines USING ((EXISTS ( SELECT 1
   FROM public.purchase_orders po
  WHERE ((po.id = purchase_order_lines.po_id) AND (po.tenant_id = public.current_tenant_id())))));

CREATE POLICY tenant_isolation ON public.purchase_orders USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.retention_budget_ledger USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.retention_campaigns USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.retention_events USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.sales_historical USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.sales_stream_raw USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.security_events USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.stores USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.subscriptions USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.supplier_invoice_lines USING ((EXISTS ( SELECT 1
   FROM public.supplier_invoices i
  WHERE ((i.id = supplier_invoice_lines.invoice_id) AND (i.tenant_id = public.current_tenant_id())))));

CREATE POLICY tenant_isolation ON public.supplier_invoices USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.suppliers USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.tenant_api_keys USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.tenant_billing_profile USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.tenant_operations_policies USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.tenant_webhooks USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.transaction_lines USING ((EXISTS ( SELECT 1
   FROM public.transactions t
  WHERE ((t.id = transaction_lines.transaction_id) AND (t.tenant_id = public.current_tenant_id())))));

CREATE POLICY tenant_isolation ON public.transactions USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.usage_events USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.user_feedback USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.users USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.value_realizations USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

CREATE POLICY tenant_isolation ON public.webhook_deliveries USING ((tenant_id = public.current_tenant_id())) WITH CHECK ((tenant_id = public.current_tenant_id()));

ALTER TABLE public.tenant_operations_policies ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.tenant_webhooks ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.transaction_lines ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.transactions ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.usage_events ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.user_feedback ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.value_realizations ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.webhook_deliveries ENABLE ROW LEVEL SECURITY;

