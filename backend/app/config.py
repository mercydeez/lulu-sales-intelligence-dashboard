from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional, List
import logging
import sys
import secrets
import warnings


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
    
    # Request Body Size Limit (MB)
    max_body_size_mb: int = 10
    
    # API Keys (optional - for AI features)
    openai_api_key: Optional[str] = None
    deepgram_api_key: Optional[str] = None
    
    # Streaming - 10 seconds for fast real-time updates
    streaming_interval_seconds: int = 10
    
    # Predictions
    forecast_days: int = 30
    
    # Rate Limiting
    rate_limit_requests: int = 100  # requests per minute
    rate_limit_window: int = 60  # seconds
    
    # Logging
    log_level: str = "INFO"
    log_format: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    
    class Config:
        env_file = ".env"
        case_sensitive = False

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
    
    # Formatter
    formatter = logging.Formatter(settings.log_format)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(console_handler)
    
    return logger


# Initialize logger
logger = setup_logging()
