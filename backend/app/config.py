from pydantic_settings import BaseSettings
from pydantic import field_validator, model_validator
from functools import lru_cache
from typing import Optional, List
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

    # Redis
    redis_url: str = "redis://localhost:6379"
    
    # Application
    environment: str = "development"
    debug: bool = True
    secret_key: str = "your-secret-key-change-in-production"

    # Product branding — single source of truth for the product name. The final
    # name is TBD, so this is a provisional placeholder; change it here (or via
    # the PRODUCT_NAME env var) and it propagates everywhere on the backend.
    product_name: str = "Retail IQ"
    
    # JWT
    jwt_secret_key: str = "super-secret-change-in-production-2026"
    
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
    
    # Rate Limiting
    rate_limit_requests: int = 100  # requests per minute
    rate_limit_window: int = 60  # seconds
    
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
