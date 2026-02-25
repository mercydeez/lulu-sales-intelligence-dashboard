"""
Configuration Tests — Validates Settings model defaults, types, and overrides.
"""
import pytest
from app.config import Settings, get_settings, setup_logging


class TestSettingsDefaults:
    """Ensure all default values are sensible."""

    def test_default_environment_or_env_override(self):
        s = Settings()
        # In CI, ENVIRONMENT env var is set; locally it defaults to "development"
        assert s.environment in ("development", "testing")

    def test_default_debug_is_true(self):
        s = Settings()
        assert s.debug is True

    def test_default_rate_limits(self):
        s = Settings()
        assert s.rate_limit_requests == 100
        assert s.rate_limit_window == 60

    def test_default_streaming_interval(self):
        s = Settings()
        assert s.streaming_interval_seconds == 10

    def test_default_forecast_days(self):
        s = Settings()
        assert s.forecast_days == 30

    def test_default_body_size_limit(self):
        s = Settings()
        assert s.max_body_size_mb == 10

    def test_optional_api_keys_default_none(self):
        s = Settings()
        assert s.openai_api_key is None
        assert s.deepgram_api_key is None


class TestSettingsOverride:
    """Ensure settings can be overridden via constructor."""

    def test_override_environment(self):
        s = Settings(environment="production")
        assert s.environment == "production"

    def test_override_rate_limits(self):
        s = Settings(rate_limit_requests=50, rate_limit_window=30)
        assert s.rate_limit_requests == 50
        assert s.rate_limit_window == 30

    def test_override_cors(self):
        s = Settings(cors_origins="https://example.com")
        assert s.cors_origins == "https://example.com"


class TestLoggerSetup:
    """Verify the logger is configured correctly."""

    def test_logger_has_handlers(self):
        logger = setup_logging()
        assert len(logger.handlers) >= 1

    def test_logger_name(self):
        logger = setup_logging()
        assert logger.name == "sales_dashboard"

    def test_get_settings_returns_settings(self):
        s = get_settings()
        assert isinstance(s, Settings)
