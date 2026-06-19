from pydantic_settings import BaseSettings
from pydantic import field_validator
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
    
    # Redis
    redis_url: str = "redis://localhost:6379"
    
    # Application
    environment: str = "development"
    debug: bool = True
    secret_key: str = "your-secret-key-change-in-production"
    
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
    
    # API Keys (optional - for AI features)
    openai_api_key: Optional[str] = None
    deepgram_api_key: Optional[str] = None

    # Local LLM via Ollama (preferred provider when configured — zero paid keys)
    ollama_url: Optional[str] = None  # e.g. http://ollama:11434
    ollama_model: str = "llama3.2"
    
    # Streaming - 10 seconds for fast real-time updates
    streaming_interval_seconds: int = 10
    
    # Predictions
    forecast_days: int = 30
    
    # Rate Limiting
    rate_limit_requests: int = 100  # requests per minute
    rate_limit_window: int = 60  # seconds
    
    # Logging
    log_level: str = "INFO"
    log_format: str = "%(asctime)s | %(levelname)-8s | %(name)s | req=%(request_id)s | %(message)s"
    log_json: bool = False  # emit one JSON object per line (structured logging)
    
    model_config = {"env_file": ".env", "case_sensitive": False}

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
