"""
Security Tests — Validates that insecure defaults are caught and
production deployments are blocked when configuration is weak.
"""
import pytest
from app.config import Settings, _INSECURE_SECRETS


# =============================================================================
# 1. Insecure default detection
# =============================================================================

class TestInsecureDefaults:
    """Verify the known-bad secrets list is comprehensive."""

    def test_known_defaults_are_listed(self):
        assert "your-secret-key-change-in-production" in _INSECURE_SECRETS
        assert "super-secret-change-in-production-2026" in _INSECURE_SECRETS
        assert "" in _INSECURE_SECRETS

    def test_empty_string_is_insecure(self):
        assert "" in _INSECURE_SECRETS


# =============================================================================
# 2. Development environment — warnings but no crash
# =============================================================================

class TestDevSecurityValidation:

    def test_dev_with_defaults_returns_warnings(self, test_settings):
        """Development mode with default-ish keys should warn, not crash."""
        s = Settings(
            environment="development",
            jwt_secret_key="super-secret-change-in-production-2026",
            secret_key="your-secret-key-change-in-production",
        )
        issues = s.validate_security()
        assert len(issues) >= 2
        assert any("jwt_secret_key" in i for i in issues)
        assert any("secret_key" in i for i in issues)

    def test_dev_with_strong_keys_no_issues(self, test_settings):
        issues = test_settings.validate_security()
        assert issues == []

    def test_dev_short_jwt_key_warns(self):
        s = Settings(
            environment="development",
            jwt_secret_key="short-key",  # < 32 chars
            secret_key="a-strong-enough-app-secret-key-for-dev",
        )
        issues = s.validate_security()
        assert any("shorter than 32" in i for i in issues)


# =============================================================================
# 3. Production environment — must fail-fast on insecure config
# =============================================================================

class TestProdSecurityValidation:

    def test_prod_insecure_jwt_raises(self):
        s = Settings(
            environment="production",
            jwt_secret_key="super-secret-change-in-production-2026",
            secret_key="a-very-strong-production-secret-key-for-the-app",
            database_url="postgresql+asyncpg://produser:securepass@db:5432/proddb",
        )
        with pytest.raises(RuntimeError, match="jwt_secret_key"):
            s.validate_security()

    def test_prod_insecure_secret_key_raises(self):
        s = Settings(
            environment="production",
            jwt_secret_key="a-very-strong-production-secret-that-is-adequately-long",
            secret_key="your-secret-key-change-in-production",
            database_url="postgresql+asyncpg://produser:securepass@db:5432/proddb",
        )
        with pytest.raises(RuntimeError, match="secret_key"):
            s.validate_security()

    def test_prod_short_jwt_key_raises(self):
        s = Settings(
            environment="production",
            jwt_secret_key="too-short",
            secret_key="a-very-strong-production-secret-key-for-the-app",
            database_url="postgresql+asyncpg://produser:securepass@db:5432/proddb",
        )
        with pytest.raises(RuntimeError):
            s.validate_security()

    def test_prod_default_db_credentials_raises(self):
        s = Settings(
            environment="production",
            jwt_secret_key="a-very-strong-production-secret-that-is-adequately-long",
            secret_key="a-very-strong-production-secret-key-for-the-app",
            database_url="postgresql+asyncpg://salesuser:salespass@db:5432/salesdb",
        )
        with pytest.raises(RuntimeError, match="default credentials"):
            s.validate_security()

    def test_prod_debug_true_warns(self, production_settings):
        s = Settings(
            environment="production",
            debug=True,
            jwt_secret_key="a-very-strong-production-secret-that-is-adequately-long",
            secret_key="another-strong-production-secret-key-for-the-app-layer",
            database_url="postgresql+asyncpg://produser:str0ng@db:5432/proddb",
        )
        issues = s.validate_security()
        assert any("debug=True" in i for i in issues)

    def test_prod_secure_config_passes(self, production_settings):
        issues = production_settings.validate_security()
        assert issues == []


# =============================================================================
# 4. Staging treated like production
# =============================================================================

class TestStagingSecurity:

    def test_staging_insecure_jwt_raises(self):
        s = Settings(
            environment="staging",
            jwt_secret_key="super-secret-change-in-production-2026",
            secret_key="a-very-strong-staging-secret-key-for-the-app",
            database_url="postgresql+asyncpg://stguser:securepass@db:5432/stgdb",
        )
        with pytest.raises(RuntimeError, match="jwt_secret_key"):
            s.validate_security()
