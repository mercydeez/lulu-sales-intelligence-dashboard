from pydantic_settings import BaseSettings
from pydantic import field_validator, model_validator
from functools import lru_cache
from typing import Optional, List
from datetime import date
import contextvars
import json
import logging
import re
import sys


# Request-scoped correlation id, set by RequestIDMiddleware and read by the
# logging filter below so every log line emitted while handling a request
# carries its request id — no need to thread it through call signatures.
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)

# Request-scoped tenant/user, set by get_current_user, surfaced in structured logs
# for correlation. Never include secrets — only the numeric ids.
log_tenant_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("log_tenant", default="-")
log_user_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("log_user", default="-")


# Known weak/default secrets that must not be used in production
_INSECURE_SECRETS = {
    "your-secret-key-change-in-production",
    "super-secret-change-in-production-2026",
    "changeme",
    "secret",
    "password",
    "",
}


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://salesuser:salespass@localhost:5432/salesdb"

    # RLS hardening (B2): when enabled, the request path connects as the
    # non-owner `app_rw` role so Postgres FORCE RLS enforces tenant isolation
    # (migration 020). Off by default — startup/migrations/background keep using
    # the (superuser) database_url, which bypasses RLS by design.
    use_rls_role: bool = False
    rls_database_url: Optional[str] = None  # defaults to database_url with app_rw creds

    # E6-4: default statement_timeout stamped onto every app DB connection (both
    # engines), so no endpoint can hold a connection on one runaway query. Known
    # long operations (migrations, CSV seed, bulk ingest, forecast fetch, demo
    # reset) opt out per-transaction with SET LOCAL statement_timeout = 0.
    # 0 disables. Sage's own tighter cap (sage_query_timeout_ms) still applies
    # to generated SQL.
    db_statement_timeout_ms: int = 10000

    # Redis
    redis_url: str = "redis://localhost:6379"
    
    # Application
    environment: str = "development"
    debug: bool = True
    secret_key: str = "your-secret-key-change-in-production"

    # Product branding — single source of truth for the product name
    # (owner-confirmed: "Retail Intelligence"); change it here (or via the
    # PRODUCT_NAME env var) and it propagates everywhere on the backend.
    # "Meridian Hypermarket" is the fictional demo retailer, never the product.
    product_name: str = "Retail Intelligence"
    
    # JWT
    jwt_secret_key: str = "super-secret-change-in-production-2026"

    # --- E5-6 JWT signing: RS256 (asymmetric) + vault-sourced keys + rotation ----
    # jwt_algorithm: "HS256" (legacy symmetric shared secret) or "RS256" (private
    # key signs, public key verifies — smaller key-compromise blast radius). The
    # private key comes from an inline PEM (JWT_PRIVATE_KEY) or, preferably, a file
    # a secret vault writes (JWT_PRIVATE_KEY_PATH). Verification keys live in
    # JWT_PUBLIC_KEYS_DIR as "<kid>.pem" so multiple keys coexist during rotation;
    # the active signing key id is JWT_ACTIVE_KID. See services/jwt_keys.py and
    # docs/runbooks/JWT_KEY_ROTATION.md. Defaults keep HS256 so existing
    # deployments/tests are unaffected until they opt in.
    jwt_algorithm: str = "HS256"                 # "HS256" | "RS256"
    jwt_private_key: str = ""                    # inline RS256 private key PEM (or use the path)
    jwt_private_key_path: str = ""               # file path a vault writes the private PEM to
    jwt_public_keys_dir: str = ""                # dir of "<kid>.pem" public keys (rotation set)
    jwt_active_kid: str = ""                     # key id stamped into the signing header
    jwt_allow_hs256_fallback: bool = True        # accept legacy HS256 tokens during cutover

    # CORS
    cors_origins: str = "http://localhost:3000,http://frontend:3000"

    # Content Security Policy — connect-src lists the API + websocket origins the
    # browser is allowed to call. Environment-specific; override via env in prod
    # (e.g. CSP_CONNECT_SRC="'self' https://api.example.com wss://api.example.com").
    csp_connect_src: str = "'self' http://localhost:8000 ws://localhost:8000 http://localhost:3000"
    
    # Request Body Size Limit (MB)
    max_body_size_mb: int = 10

    # Session revocation posture. When Redis (the JWT blacklist store) is
    # unreachable, the token blacklist can't be consulted. Secure default is
    # FAIL-CLOSED: reject the request so a logged-out / rotated token can never be
    # honored during an outage. Set AUTH_FAIL_OPEN_ON_REDIS_DOWN=true ONLY if you
    # consciously prefer availability over revocation guarantees.
    auth_fail_open_on_redis_down: bool = False

    # Reverse-proxy trust. X-Forwarded-For / X-Real-IP are client-spoofable
    # unless a trusted proxy overwrites them. OFF by default so an attacker can't
    # forge their source IP to evade per-IP rate limiting or poison audit-log IPs.
    # Set TRUST_PROXY_HEADERS=true ONLY when the app sits behind a proxy (nginx,
    # load balancer) that strips inbound XFF and sets the real client IP.
    trust_proxy_headers: bool = False
    
    # API Keys (optional - for AI features)
    openai_api_key: Optional[str] = None
    deepgram_api_key: Optional[str] = None

    # Local LLM via Ollama (preferred provider when configured — zero paid keys)
    ollama_url: Optional[str] = None  # e.g. http://ollama:11434
    ollama_model: str = "llama3.2"

    # Sage — NL->SQL diagnostic assistant (A2). Generates SQL with the LLM, runs it
    # through an allow-list guard, then executes it as the least-privilege `sage_ro`
    # role (migration 023) against the tenant-filtered sage_* views only. Works with
    # zero LLM provider configured — it falls back to the rule-based responder.
    chatbot_name: str = "Sage"
    sage_enabled: bool = True
    # Connection for Sage's read-only execution. Defaults to database_url with the
    # sage_ro creds (least privilege: SELECT on sage_* views only). Set explicitly
    # in prod (and override the dev password on the role).
    sage_database_url: Optional[str] = None
    sage_query_timeout_ms: int = 5000   # statement_timeout for generated SQL
    sage_max_rows: int = 200            # hard LIMIT injected/clamped by the guard

    # Sage v3 — multi-agent LangGraph chatbot (router → intent → executor →
    # synthesiser → validation → finaliser). OFF by default: the proven Sage v2
    # path stays the default so v3 can be A/B'd and rolled back via this flag
    # alone. When false, routes/ai.py never imports LangGraph. See
    # docs/SAGE_V3_AGENT_INTEGRATION.md and services/sage3/.
    use_sage_v3: bool = False
    # Optional Langfuse tracing for the v3 graph (Phase 5). No-op until both keys
    # are set, so the stack runs with zero external services by default.
    langfuse_public_key: Optional[str] = None
    langfuse_secret_key: Optional[str] = None
    langfuse_host: Optional[str] = None  # e.g. https://cloud.langfuse.com

    # Sage v2 external API sources (S4) — JSON map of third-party data feeds the
    # decompose-route-recompose engine can call for a sub-question, e.g. weather /
    # FX / market prices. Empty by default (no-op). Shape:
    #   {"fx": {"keyword":"exchange rate","url":"https://api.x/rate?base=AED",
    #           "value_path":"rates.USD","header_env":"FX_API_KEY","header_name":"X-Api-Key"}}
    external_api_sources: str = ""
    
    # Streaming - 10 seconds for fast real-time updates
    streaming_interval_seconds: int = 10
    
    # Predictions
    forecast_days: int = 30

    # Background forecast trainer (Forecast Lab). CPU-heavy; runs off the event
    # loop in a worker thread. Disable on constrained hosts to keep the API lean.
    forecast_trainer_enabled: bool = True
    forecast_trainer_startup_delay_seconds: int = 60  # let the API settle before first train
    
    # Rate Limiting (E0-7: per-identity sliding windows, one bucket per request).
    # Scope precedence in the middleware: API key > authenticated user > IP.
    # rate_limit_requests is the ANONYMOUS per-IP bucket — the strictest, because
    # unauthenticated abuse has no identity to bill. Authenticated users get their
    # own per-user_id bucket (so one hot user can't starve an office NAT'd behind
    # one IP, and IP rotation no longer resets an authed abuser's budget); API
    # keys get a per-key bucket.
    rate_limit_requests: int = 100  # requests per minute
    rate_limit_window: int = 60  # seconds
    rate_limit_user_requests: int = 600      # per authenticated user_id / window
    rate_limit_api_key_requests: int = 300   # per API key (sha256 of the raw key)
    
    # Observability (Track B) — env-gated, optional. No DSN/key => no-op, so the
    # stack runs with zero external services. Drop in when you add the accounts.
    sentry_dsn: Optional[str] = None        # error tracking
    posthog_api_key: Optional[str] = None   # product analytics (frontend reads NEXT_PUBLIC_*)

    # Notifications (Track B) — provider-agnostic. The diagnostics worker posts new
    # high/critical findings to NOTIFY_WEBHOOK_URL (any Slack/Discord/Teams incoming
    # webhook). Empty => the worker just logs. No SDK, no paid service.
    notify_webhook_url: Optional[str] = None

    # Security alerting (Google-style "we noticed a security event" emails). Fires
    # when a security event at/above security_alert_min_severity is recorded. All
    # env-gated and no-op until configured, so nothing leaves the stack by default.
    # SMTP works with any provider — e.g. Gmail: smtp.gmail.com:587 + an app password.
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: bool = True
    security_alert_email_from: Optional[str] = None   # defaults to smtp_user
    security_alert_email_to: Optional[str] = None      # comma-separated recipients
    security_alert_webhook_url: Optional[str] = None   # Slack/Discord/Teams incoming webhook
    security_alert_min_severity: str = "high"          # critical | high | medium | low | info

    # Logging
    log_level: str = "INFO"
    log_format: str = "%(asctime)s | %(levelname)-8s | %(name)s | req=%(request_id)s | %(message)s"
    log_json: bool = False  # emit one JSON object per line (structured logging)

    # =========================================================================
    # PRODUCTION MODES & FEATURE FLAGS (fail-closed in prod/staging)
    # -------------------------------------------------------------------------
    # Operational + demo toggles are Optional[bool] = None meaning "auto":
    # enabled in development/testing for convenience, disabled in
    # production/staging for safety. Set the env var explicitly (true/false) to
    # override. The model_validator below resolves None -> concrete bool, and
    # validate_security() rejects unsafe combinations in production.
    # =========================================================================

    # Demo / sample data (SYNTHETIC — never real customer data; see
    # docs/product/DEMO_VS_REAL_DATA.md).
    demo_mode: Optional[bool] = None               # master switch for demo behavior
    sample_data_enabled: Optional[bool] = None     # seed synthetic historical data
    live_generator_enabled: Optional[bool] = None  # run the synthetic sale generator
    allow_demo_users: Optional[bool] = None        # seed/permit demo logins

    # E0-8: the ONE tenant synthetic data may touch. The generator scopes every
    # store/item lookup to it, stamps it on each row, and migration 057's trigger
    # rejects any synthetic row carrying a different tenant_id. Keep in sync with
    # the `demo` tenant seeded by migration 010.
    demo_tenant_id: int = 1

    # E7-2: publish the forecast methodology + accuracy at /methodology and
    # GET /api/monitoring/forecast-methodology (unauthenticated). The payload is
    # anonymous by construction — error rates and feature flags, never a tenant's
    # revenue. Set false to withhold it (the endpoint then 404s).
    forecast_methodology_public: bool = True

    # E6-5 follow-up: process model + connection budget for `gunicorn --workers N`.
    # web_concurrency is set per-service in compose (command:), NOT in the
    # Dockerfile CMD, so production never silently inherits a worker count. The
    # pool is PER PROCESS, so total server connections ≈
    #   (API workers + singletons + worker) × engines-per-process × (pool + overflow).
    # Keep these small so N workers stay under Postgres max_connections (raised to
    # 200 in production compose). Owner + optional rls + optional replica = up to 3
    # engines per process.
    web_concurrency: int = 4          # gunicorn worker count (per-service override wins)
    db_pool_size: int = 10            # warm connections kept open, per engine per process
    db_max_overflow: int = 10         # extra on-demand connections, per engine per process

    # E10-7: lag-tolerant reads (analytics, reports, history) route here. Unset =>
    # every read goes to the primary and get_read_db is a no-op. A replica is
    # BEHIND the primary, so nothing that reads its own write may use it.
    database_replica_url: Optional[str] = None

    # E10-2: the isolation tiers this deployment can PROVISION. `dedicated_schema`
    # is now buildable (migration 068's provision_tenant_schema), so it is listed;
    # actual serving is still gated on the provisioning control plane recording a
    # tenant `active` (services/provisioning.py). `dedicated_db` stays out until an
    # operator provisions a separate database + per-tenant routing.
    supported_isolation_tiers: List[str] = ["shared", "dedicated_schema"]

    # E10-2: whether an active dedicated_schema tenant's session is routed to their
    # schema via search_path. OFF by default — routing raw tables to the tenant
    # schema while the shared analytics views still bind to `public` would give a
    # correct-looking-but-wrong dashboard. Enable only once the view stack is
    # replicated per tenant (docs/product/ISOLATION_TIERS.md).
    enable_dedicated_schema_routing: bool = False

    # E6-3: sales_stream_raw is partitioned by month. Maintenance creates the next
    # three months and DROPs whole partitions older than the retention window —
    # instant, and it returns the disk, where a DELETE would bloat the table.
    # Dropping a month is irreversible: 0 disables pruning entirely (partitions are
    # still created), and anything under 1 month is refused by the SQL function.
    partition_maintenance_enabled: bool = True
    sales_stream_retention_months: int = 12

    # E2-2: the recurring-import poller. On by default and inert with no schedules
    # — the claim query returns nothing and it sleeps. Creating a schedule (an
    # explicit, operator-supplied https URL) is the consent to make egress calls.
    import_scheduler_enabled: bool = True

    # E2-1: the POS connector nightly sync. On by default and inert with no
    # connections — sync_all_connected finds nothing and sleeps. It runs in the
    # singletons container (exactly one process), never per web worker.
    pos_sync_enabled: bool = True

    # HORIZON 1: the Flywheel incrementality readout scheduler. Recomputes every
    # measurable campaign's treatment-vs-control outcome and writes an immutable
    # row with an anytime-valid confidence interval. Runs in the singletons
    # container (exactly one process). Readouts are idempotent per
    # (campaign, window_end), so a missed pass self-heals on the next tick.
    flywheel_readout_scheduler_enabled: bool = True
    #: Seconds between passes. A 60-day retention window does not move hourly;
    #: anything faster is churn for its own sake.
    flywheel_readout_interval_seconds: int = 3600

    # Platform Console: optional comma-separated email allowlist AND-gated with
    # users.is_platform_developer (services/platform_access.py). Empty = the DB
    # flag alone decides (dev convenience); set it in production so a tampered
    # DB row alone cannot mint platform access. Comma-separated str, not a list —
    # pydantic-settings would try to JSON-parse a List[str] env value.
    platform_developer_emails: str = ""
    pos_sync_interval_seconds: int = 24 * 60 * 60   # nightly
    pos_sync_startup_delay_seconds: int = 90        # let the app settle first

    # E8-3: turn plan quotas from a meter into a limit. Off by default — we meter
    # first and enforce once the numbers have been watched for a period. Was read
    # via a bare os.getenv in usage_metering, which kept it out of Settings and
    # therefore out of every test that overrides configuration.
    enforce_usage_quotas: bool = False

    # E6-6: the public API's version lifecycle (services/api_versioning.py).
    # Both dates are UNSET, which is what makes /api/public/v1 "current" — the
    # deprecation machinery is live, it simply has nothing to announce. Setting
    # public_api_v1_deprecated_on starts emitting RFC 9745 `Deprecation` headers;
    # once public_api_v1_sunset_on passes, v1 answers 410 Gone. Never set a sunset
    # date without a deprecation date at least one release cycle earlier.
    public_api_v1_deprecated_on: Optional[date] = None
    public_api_v1_sunset_on: Optional[date] = None
    public_api_policy_url: str = "https://github.com/mercydeez/lulu-sales-intelligence-dashboard/blob/main/docs/api/VERSIONING.md"

    # Nightly wipe of generated sales so the demo never drifts into a fake all-time
    # high. Rows younger than the retention window survive so the live stream stays
    # populated right after a reset.
    demo_reset_enabled: Optional[bool] = None
    demo_reset_hour_utc: int = 22               # 02:00 Asia/Dubai (UTC+4)
    demo_reset_retain_hours: int = 48

    # One-shot / background work run from the API lifespan. In production these
    # belong in dedicated processes (backend/app/commands/*), so in a real prod
    # (demo_mode off) they resolve off and validate_security() rejects
    # migrate/seed-on-startup outright.
    run_migrations_on_startup: Optional[bool] = None
    run_seed_on_startup: Optional[bool] = None
    run_employee_seeder_on_startup: Optional[bool] = None
    run_cache_warmer: Optional[bool] = None
    run_forecast_trainer: Optional[bool] = None

    # Feature flags
    expose_api_docs: Optional[bool] = None         # /docs, /redoc, /openapi.json
    enable_signup: Optional[bool] = None
    enable_public_api: Optional[bool] = None
    enable_external_ai: Optional[bool] = None       # 3rd-party LLM — OFF unless explicit
    enable_local_ai: Optional[bool] = None          # local Ollama
    enable_data_source_connectors: Optional[bool] = None
    require_email_verification: Optional[bool] = None
    require_mfa_for_admins: Optional[bool] = None

    # Infra / least-privilege DB roles
    worker_database_url: Optional[str] = None       # diagnostics worker (worker_role)
    redis_self_hosted: bool = False                 # True => prod Redis MUST carry a password
    allow_insecure_no_rls: bool = False             # dangerous override: prod without the RLS role

    # --- E0-2 uptime monitoring + alerting (Krishna) -----------------------
    # Generic webhook alerting — provider-agnostic on purpose. Route the webhook to
    # a phone/SMS/WhatsApp via Better Stack / Healthchecks.io / PagerDuty / Twilio /
    # Slack. The URL is a SECRET and must never appear in any health/API response.
    alert_enabled: bool = False                     # master switch; stays off unless set
    alert_webhook_url: Optional[str] = None         # SECRET — POST target for alerts
    alert_webhook_timeout_seconds: int = 5          # bound so a slow webhook can't hang health
    alert_min_severity: str = "critical"            # critical | high | medium | low | info
    alert_dedup_ttl_seconds: int = 300              # suppress duplicate alerts within this window
    alert_environment: Optional[str] = None         # label in the alert; defaults to `environment`
    # Worker heartbeat freshness (the worker writes health:worker:diagnostics to Redis).
    worker_heartbeat_interval_ms: int = 30000       # informational: how often the worker beats
    worker_heartbeat_stale_seconds: int = 120       # older than this => the worker is "stale"
    # Backup manifest (E0-1 already produces it; we only READ its freshness here).
    backup_manifest_path: str = "/backups/latest.json"
    backup_stale_after_hours: int = 30

    # --- E5-1a SSO / OIDC foundation (Krishna security) --------------------
    # SSO is OFF by default. OIDC must be explicitly enabled. Provider configs
    # live per-tenant in tenant_sso_providers; client secrets live ONLY in env
    # vars named by tenant_sso_providers.client_secret_env (never in the DB/logs).
    sso_enabled: bool = False
    sso_oidc_enabled: bool = False
    sso_state_ttl_seconds: int = 600            # single-use auth state lifetime
    sso_jwks_cache_ttl_seconds: int = 3600      # in-memory JWKS/discovery cache TTL
    sso_require_verified_email: bool = True     # reject IdP emails not marked verified
    sso_default_role: str = "analyst"           # JIT default; never an admin role
    sso_trust_idp_mfa_default: bool = False     # fail-closed: local admin MFA wins
    # Comma-separated hosts a post-login return_to may point at (exact host match).
    sso_allowed_redirect_hosts: str = ""
    sso_max_return_to_length: int = 500

    # --- E5-1b SSO provider operations + managed SAML bridge (Krishna) ------
    sso_admin_config_enabled: bool = True          # tenant-admin provider mgmt endpoints
    sso_managed_saml_bridge_enabled: bool = False  # allow workos_saml (SAML->OIDC bridge) login
    sso_native_saml_enabled: bool = False          # native SAML SP — NOT implemented; stays off
    sso_live_provider_validation_enabled: bool = False   # hit discovery/JWKS during validate
    sso_provider_validation_timeout_seconds: int = 5

    # --- E5-1c SCIM enterprise provisioning (Krishna security) -------------
    # SCIM is OFF by default. Per-tenant bearer tokens (hashed at rest) authorize
    # the SCIM protocol endpoints. SCIM-provisioned users default to analyst and
    # can NEVER be admin/owner/super_admin. See docs/security/SCIM.md.
    scim_enabled: bool = False
    scim_token_ttl_days: int = 365              # default expiry for new SCIM tokens
    scim_default_role: str = "analyst"          # role for SCIM-provisioned users
    scim_allow_admin_role_mapping: bool = False # never map groups->admin unless explicit
    scim_group_mapping_enabled: bool = False    # apply group->role mappings at all
    scim_max_page_size: int = 100               # cap SCIM list `count`
    scim_deactivate_revokes_tokens: bool = True # revoke sessions on deactivate
    scim_allow_reactivation: bool = True        # allow active:false -> true
    scim_audit_enabled: bool = True             # record SCIM security events

    # --- E5-3 UAE data residency / region hosting (Krishna security) -------
    # Where tenant data physically lives. `data_region` is a free-form region id
    # (e.g. "me-central-1" AWS UAE, or "uae-north" Azure). When
    # `data_residency_required` is true, production/staging boot FAILS unless the
    # region matches the approved UAE list. See docs/runbooks/DATA_RESIDENCY.md.
    data_region: str = ""                       # e.g. "me-central-1" | "uae-north"
    data_residency_required: bool = False       # enforce UAE region at boot (prod)
    approved_data_regions: str = "me-central-1,me-central,uae-north,uae-central,uae,ae"
    backup_region: str = ""                      # region of the offsite backup target
    cross_border_transfer_allowed: bool = False  # is any egress out of region permitted
    log_retention_days: int = 30                 # documented retention for app/audit logs
    data_residency_statement_enabled: bool = True  # expose the public /residency posture

    model_config = {"env_file": ".env", "case_sensitive": False}

    @model_validator(mode="after")
    def _resolve_mode_defaults(self):
        """Resolve Optional 'auto' flags to concrete bools based on environment.

        Development/testing get convenience-on; production/staging get safe-off.
        Explicitly-set env vars (non-None) are never overridden.
        """
        is_prod = self.environment.lower() in ("production", "prod", "staging")
        dev_like = not is_prod

        def auto(current: Optional[bool], dev_default: bool, prod_default: bool) -> bool:
            if current is not None:
                return current
            return dev_default if dev_like else prod_default

        # Demo behavior — convenient in dev, off in prod unless explicitly enabled.
        self.demo_mode = auto(self.demo_mode, True, False)
        self.sample_data_enabled = auto(self.sample_data_enabled, True, self.demo_mode)
        self.live_generator_enabled = auto(self.live_generator_enabled, True, self.demo_mode)
        self.allow_demo_users = auto(self.allow_demo_users, True, False)
        # Only ever resets the demo tenant, so it tracks demo_mode in both directions.
        self.demo_reset_enabled = auto(self.demo_reset_enabled, self.demo_mode, self.demo_mode)

        # Startup work — on in dev for single-box convenience; in prod only under demo_mode.
        self.run_migrations_on_startup = auto(self.run_migrations_on_startup, True, self.demo_mode)
        self.run_seed_on_startup = auto(self.run_seed_on_startup, True, self.demo_mode)
        self.run_employee_seeder_on_startup = auto(self.run_employee_seeder_on_startup, True, self.demo_mode)
        self.run_cache_warmer = auto(self.run_cache_warmer, True, True)  # per-instance cache, safe
        # Honor the pre-existing forecast_trainer_enabled toggle as the default.
        self.run_forecast_trainer = auto(
            self.run_forecast_trainer, self.forecast_trainer_enabled, self.forecast_trainer_enabled
        )

        # Feature flags.
        self.expose_api_docs = auto(self.expose_api_docs, True, False)
        self.enable_signup = auto(self.enable_signup, True, True)
        self.enable_public_api = auto(self.enable_public_api, True, True)
        # External AI is OFF by default everywhere — must be explicitly opted into.
        self.enable_external_ai = self.enable_external_ai if self.enable_external_ai is not None else False
        self.enable_local_ai = auto(self.enable_local_ai, True, True)
        self.enable_data_source_connectors = auto(self.enable_data_source_connectors, True, False)
        self.require_email_verification = auto(self.require_email_verification, False, True)
        self.require_mfa_for_admins = auto(self.require_mfa_for_admins, False, False)
        return self

    @model_validator(mode="after")
    def _validate_api_lifecycle(self):
        """E6-6: a sunset is a promise, and a promise needs notice.

        Retiring a version without ever announcing the deprecation would 410 an
        integrator who had no warning, so the config refuses to express it.
        """
        dep, sun = self.public_api_v1_deprecated_on, self.public_api_v1_sunset_on
        if sun and not dep:
            raise ValueError(
                "PUBLIC_API_V1_SUNSET_ON is set without PUBLIC_API_V1_DEPRECATED_ON — "
                "a version must be announced as deprecated before it can be retired."
            )
        if sun and dep and sun <= dep:
            raise ValueError(
                "PUBLIC_API_V1_SUNSET_ON must be strictly after PUBLIC_API_V1_DEPRECATED_ON."
            )
        return self

    @property
    def api_docs_enabled(self) -> bool:
        """Whether interactive API docs (/docs, /redoc, /openapi.json) are served."""
        dev_like = self.environment.lower() not in ("production", "prod", "staging")
        return bool(dev_like or self.expose_api_docs)

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, v: str) -> str:
        """
        Managed Postgres providers (Render, Heroku, Railway, …) hand out
        `postgres://…` or `postgresql://…` connection strings, but SQLAlchemy's
        async engine requires the asyncpg driver (`postgresql+asyncpg://…`).
        Normalize the scheme, and drop libpq's `sslmode` query param which asyncpg
        does not accept (internal managed connections don't need it).
        """
        if v.startswith("postgres://"):
            v = "postgresql+asyncpg://" + v[len("postgres://"):]
        elif v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v[len("postgresql://"):]
        # Remove an sslmode=... query param (asyncpg uses an ssl context, not sslmode).
        v = re.sub(r"([?&])sslmode=[^&]*(&|$)", lambda m: m.group(1) if m.group(2) == "&" else "", v)
        v = re.sub(r"[?&]$", "", v)
        return v

    # =========================================================================
    # SECURITY VALIDATION
    # =========================================================================
    def validate_security(self) -> List[str]:
        """
        Validate security-critical settings.
        Returns a list of warning/error messages.
        In production, raises RuntimeError on insecure defaults.
        """
        issues: List[str] = []
        is_prod = self.environment.lower() in ("production", "prod", "staging")

        # --- JWT secret ---
        if self.jwt_secret_key.lower() in _INSECURE_SECRETS:
            msg = "CRITICAL: jwt_secret_key is using an insecure default value!"
            if is_prod:
                raise RuntimeError(
                    f"{msg} Set a strong JWT_SECRET_KEY env variable before deploying."
                )
            issues.append(msg)

        if len(self.jwt_secret_key) < 32:
            msg = "WARNING: jwt_secret_key is shorter than 32 characters — consider a longer secret."
            if is_prod:
                raise RuntimeError(msg)
            issues.append(msg)

        # --- E5-6 JWT signing algorithm / keys ---
        algo = (self.jwt_algorithm or "HS256").upper()
        if algo not in ("HS256", "RS256"):
            msg = f"CRITICAL: JWT_ALGORITHM '{self.jwt_algorithm}' is not supported (use HS256 or RS256)."
            if is_prod:
                raise RuntimeError(msg)
            issues.append(msg)
        elif algo == "RS256":
            # RS256 needs a resolvable private key + an active key id. Verify the
            # key actually loads so a bad mount fails CLOSED at boot, not at first login.
            private_present = bool((self.jwt_private_key or "").strip() or (self.jwt_private_key_path or "").strip())
            if not private_present or not (self.jwt_active_kid or "").strip():
                msg = ("CRITICAL: JWT_ALGORITHM=RS256 requires a private key "
                       "(JWT_PRIVATE_KEY or JWT_PRIVATE_KEY_PATH) and JWT_ACTIVE_KID.")
                if is_prod:
                    raise RuntimeError(msg)
                issues.append(msg)
            else:
                try:
                    from app.services.jwt_keys import KeyProvider
                    kp = KeyProvider.from_settings(self)
                    if not kp.has_signing_key():
                        raise ValueError("private key/active kid did not resolve")
                    kp.sign({"probe": 1})  # proves the PEM is a usable RS256 signer
                except Exception as e:
                    msg = f"CRITICAL: RS256 signing key failed to load/sign: {e}"
                    if is_prod:
                        raise RuntimeError(msg)
                    issues.append(msg)
            if self.jwt_allow_hs256_fallback:
                issues.append(
                    "WARNING: JWT_ALLOW_HS256_FALLBACK=true — legacy HS256 tokens are still "
                    "accepted. Turn it off after the rotation window to drop symmetric trust."
                )
        elif is_prod:
            # HS256 + a strong secret is still a VALID prod config, so this is a
            # log-only nudge (not an "issue") — it must not fail the secure-config
            # bar. RS256 is recommended to shrink the key-compromise blast radius.
            import logging
            logging.getLogger("sales_dashboard").warning(
                "JWT_ALGORITHM=HS256 in production — consider migrating to RS256 "
                "(docs/runbooks/JWT_KEY_ROTATION.md) to reduce key-compromise blast radius."
            )

        # --- App secret ---
        if self.secret_key.lower() in _INSECURE_SECRETS:
            msg = "CRITICAL: secret_key is using an insecure default value!"
            if is_prod:
                raise RuntimeError(
                    f"{msg} Set a strong SECRET_KEY env variable before deploying."
                )
            issues.append(msg)

        # --- Debug mode in production ---
        if is_prod and self.debug:
            msg = "WARNING: debug=True in a production environment. Disabling is strongly recommended."
            issues.append(msg)

        # --- Database uses default credentials ---
        if is_prod and "salespass" in self.database_url:
            msg = "CRITICAL: Database URL contains default credentials!"
            raise RuntimeError(msg)

        # --- Wildcard CORS in production ---
        if is_prod and "*" in self.cors_origins:
            raise RuntimeError(
                "CRITICAL: wildcard CORS origin is not allowed in production. "
                "List explicit origins in CORS_ORIGINS."
            )

        # --- Demo users must be disabled in production ---
        if is_prod and self.allow_demo_users:
            raise RuntimeError(
                "CRITICAL: ALLOW_DEMO_USERS must be false in production."
            )

        # --- Live synthetic generator requires demo mode (never in a real tenant) ---
        if self.live_generator_enabled and not self.demo_mode:
            msg = "LIVE_GENERATOR_ENABLED requires DEMO_MODE=true — it writes synthetic sales."
            if is_prod:
                raise RuntimeError(f"CRITICAL: {msg}")
            issues.append(f"WARNING: {msg}")

        # --- The demo reset is destructive; it must never run outside demo mode ---
        if self.demo_reset_enabled and not self.demo_mode:
            msg = "DEMO_RESET_ENABLED requires DEMO_MODE=true — it deletes generated sales."
            if is_prod:
                raise RuntimeError(f"CRITICAL: {msg}")
            issues.append(f"WARNING: {msg}")

        if self.demo_tenant_id < 1:
            raise RuntimeError("CRITICAL: DEMO_TENANT_ID must be a positive tenant id.")

        # --- Sample data requires demo mode ---
        if self.sample_data_enabled and not self.demo_mode:
            if is_prod:
                raise RuntimeError(
                    "CRITICAL: SAMPLE_DATA_ENABLED requires DEMO_MODE=true in production."
                )
            issues.append("WARNING: SAMPLE_DATA_ENABLED set without DEMO_MODE — synthetic data may load.")

        # --- Migrations/seed must not run from the API in real production ---
        if is_prod and not self.demo_mode and self.run_migrations_on_startup:
            raise RuntimeError(
                "CRITICAL: RUN_MIGRATIONS_ON_STARTUP must be false in production — "
                "run the dedicated migrate job instead."
            )
        if is_prod and not self.demo_mode and self.run_seed_on_startup:
            raise RuntimeError(
                "CRITICAL: RUN_SEED_ON_STARTUP must be false in production — "
                "run the dedicated seed job instead."
            )

        # --- RLS role required in production (tenant isolation) ---
        if is_prod and not self.use_rls_role and not self.allow_insecure_no_rls:
            raise RuntimeError(
                "CRITICAL: USE_RLS_ROLE must be true in production for Postgres-enforced "
                "tenant isolation. Set ALLOW_INSECURE_NO_RLS=true only if you fully accept the risk."
            )

        # --- Self-hosted Redis must require a password ---
        if is_prod and self.redis_self_hosted and "@" not in self.redis_url:
            raise RuntimeError(
                "CRITICAL: self-hosted Redis in production must require a password "
                "(set REDIS_PASSWORD and include it in REDIS_URL)."
            )

        # --- Least-privilege DB role URLs must not use default/dev passwords ---
        _weak = ("salespass", "changeme", "devpass", "_dev_pass")
        for label, url in (
            ("RLS_DATABASE_URL", self.rls_database_url),
            ("SAGE_DATABASE_URL", self.sage_database_url),
            ("WORKER_DATABASE_URL", self.worker_database_url),
        ):
            if is_prod and url and any(w in url for w in _weak):
                raise RuntimeError(
                    f"CRITICAL: {label} appears to use a default/development password."
                )

        # --- API docs exposure in production should be deliberate + protected ---
        if is_prod and self.expose_api_docs:
            issues.append(
                "WARNING: API docs are exposed in production (EXPOSE_API_DOCS=true) — "
                "ensure they are protected at the reverse proxy."
            )

        # --- External AI opt-in sanity ---
        if is_prod and self.enable_external_ai and not self.openai_api_key:
            issues.append(
                "WARNING: ENABLE_EXTERNAL_AI is true but no external AI key is configured."
            )

        # --- E5-3 UAE data residency guardrails ---
        if self.data_residency_required:
            approved = [r.strip().lower() for r in self.approved_data_regions.split(",") if r.strip()]
            region = (self.data_region or "").strip().lower()
            region_ok = bool(region) and any(a in region for a in approved)
            if is_prod and not region_ok:
                raise RuntimeError(
                    "CRITICAL: DATA_RESIDENCY_REQUIRED is set but DATA_REGION "
                    f"('{self.data_region or 'unset'}') is not an approved UAE region "
                    f"({self.approved_data_regions}). Set DATA_REGION or clear the requirement."
                )
            if not region_ok:
                issues.append("WARNING: data residency required but DATA_REGION is not an approved UAE region.")
            if self.backup_region:
                b = self.backup_region.strip().lower()
                if not any(a in b for a in approved):
                    msg = f"BACKUP_REGION '{self.backup_region}' is outside the approved UAE region set."
                    if is_prod:
                        raise RuntimeError(f"CRITICAL: {msg}")
                    issues.append(f"WARNING: {msg}")
            if self.cross_border_transfer_allowed:
                issues.append(
                    "WARNING: CROSS_BORDER_TRANSFER_ALLOWED=true while data residency is required."
                )
            if self.enable_external_ai:
                issues.append(
                    "WARNING: ENABLE_EXTERNAL_AI=true may send tenant data OUT of the UAE "
                    "region while data residency is required."
                )

        return issues


@lru_cache()
def get_settings() -> Settings:
    return Settings()


class RequestIDLogFilter(logging.Filter):
    """Inject the current request id onto every log record.

    Pulled from the contextvar set by RequestIDMiddleware, so logs emitted deep
    in request handling (services, queries) are correlated without passing the
    id around. Records outside a request (startup, background tasks) get '-'.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_ctx.get()
        return True


class JsonLogFormatter(logging.Formatter):
    """Render log records as one JSON object per line for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        # Correlation context (numeric ids only — never secrets), when present.
        tenant = log_tenant_ctx.get()
        user = log_user_ctx.get()
        if tenant and tenant != "-":
            payload["tenant_id"] = tenant
        if user and user != "-":
            payload["user_id"] = user
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging() -> logging.Logger:
    """Configure and return the application logger."""
    settings = get_settings()

    # Create logger
    logger = logging.getLogger("sales_dashboard")
    logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)

    # Formatter — JSON (structured) or the human-readable format string
    if settings.log_json:
        formatter: logging.Formatter = JsonLogFormatter()
    else:
        formatter = logging.Formatter(settings.log_format)
    console_handler.setFormatter(formatter)
    # Filter threads the request id onto every record (incl. the format string's
    # %(request_id)s, which would otherwise KeyError on records that lack it).
    console_handler.addFilter(RequestIDLogFilter())

    logger.addHandler(console_handler)

    return logger


# Initialize logger
logger = setup_logging()
