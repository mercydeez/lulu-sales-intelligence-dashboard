"""
Production fail-closed configuration tests.

Verifies that production/staging reject unsafe combinations while development
keeps convenience defaults. Pairs with test_config.py (defaults/overrides) and
test_security.py (secret validation).
"""
import pytest
from app.config import Settings


def _prod(**overrides):
    """Build a production Settings that is otherwise SECURE, so each test
    isolates the single unsafe knob it is exercising."""
    base = dict(
        environment="production",
        debug=False,
        jwt_secret_key="a-very-strong-production-secret-that-is-adequately-long",
        secret_key="another-strong-production-secret-key-for-the-app-layer",
        database_url="postgresql+asyncpg://produser:str0ng_Pr0d_P@ss!@db.prod:5432/proddb",
        redis_url="redis://redis.prod:6379/0",
        use_rls_role=True,
        rls_database_url="postgresql+asyncpg://app_rw:str0ng_App_RW_P@ss!@db.prod:5432/proddb",
    )
    base.update(overrides)
    return Settings(**base)


class TestAutoResolution:
    """Optional 'auto' flags resolve by environment."""

    def test_dev_enables_convenience(self):
        s = Settings(environment="development")
        assert s.demo_mode is True
        assert s.sample_data_enabled is True
        assert s.live_generator_enabled is True
        assert s.run_migrations_on_startup is True
        assert s.allow_demo_users is True

    def test_prod_disables_demo_by_default(self):
        s = _prod()
        assert s.demo_mode is False
        assert s.sample_data_enabled is False
        assert s.live_generator_enabled is False
        assert s.allow_demo_users is False
        assert s.run_migrations_on_startup is False
        assert s.run_seed_on_startup is False
        assert s.enable_data_source_connectors is False
        assert s.expose_api_docs is False

    def test_external_ai_off_by_default_even_in_dev(self):
        assert Settings(environment="development").enable_external_ai is False
        assert _prod().enable_external_ai is False

    def test_explicit_override_is_honored(self):
        s = Settings(environment="production", demo_mode=True,
                     jwt_secret_key="a-very-strong-production-secret-that-is-adequately-long",
                     secret_key="another-strong-production-secret-key-for-the-app-layer",
                     database_url="postgresql+asyncpg://u:str0ngp@db:5432/d",
                     use_rls_role=True)
        assert s.demo_mode is True


class TestProdSecureConfigPasses:
    def test_secure_prod_has_no_issues(self):
        assert _prod().validate_security() == []


class TestProdFailsClosed:
    def test_wildcard_cors_rejected(self):
        with pytest.raises(RuntimeError, match="wildcard CORS"):
            _prod(cors_origins="*").validate_security()

    def test_demo_users_rejected(self):
        with pytest.raises(RuntimeError, match="ALLOW_DEMO_USERS"):
            _prod(allow_demo_users=True).validate_security()

    def test_generator_without_demo_rejected(self):
        with pytest.raises(RuntimeError, match="LIVE_GENERATOR_ENABLED"):
            _prod(live_generator_enabled=True, demo_mode=False).validate_security()

    def test_sample_data_without_demo_rejected(self):
        with pytest.raises(RuntimeError, match="SAMPLE_DATA_ENABLED"):
            _prod(sample_data_enabled=True, demo_mode=False).validate_security()

    def test_migrations_on_startup_rejected(self):
        with pytest.raises(RuntimeError, match="RUN_MIGRATIONS_ON_STARTUP"):
            _prod(run_migrations_on_startup=True).validate_security()

    def test_seed_on_startup_rejected(self):
        with pytest.raises(RuntimeError, match="RUN_SEED_ON_STARTUP"):
            _prod(run_seed_on_startup=True).validate_security()

    def test_rls_off_rejected(self):
        with pytest.raises(RuntimeError, match="USE_RLS_ROLE"):
            _prod(use_rls_role=False).validate_security()

    def test_insecure_override_is_retired_and_no_longer_bypasses_rls(self):
        # Ruling #2 (20 Jul 2026): the escape hatch was DELETED. The override no
        # longer bypasses anything — with the RLS role OFF, production is rejected
        # regardless of the old flag (the flag used to make this pass).
        with pytest.raises(RuntimeError, match="USE_RLS_ROLE|REMOVED"):
            _prod(use_rls_role=False, allow_insecure_no_rls=True).validate_security()
        # And even WITH the RLS role on, leaving the retired flag set is itself a
        # hard error, so a stale env var cannot linger and mislead an operator
        # into thinking they still have a bypass.
        with pytest.raises(RuntimeError, match="RETIRED"):
            _prod(use_rls_role=True, allow_insecure_no_rls=True).validate_security()

    def test_self_hosted_redis_without_password_rejected(self):
        with pytest.raises(RuntimeError, match="Redis"):
            _prod(redis_self_hosted=True, redis_url="redis://redis.prod:6379/0").validate_security()

    def test_self_hosted_redis_with_password_ok(self):
        assert _prod(redis_self_hosted=True,
                     redis_url="redis://:str0ngRedisPass@redis.prod:6379/0").validate_security() == []

    def test_default_role_password_rejected(self):
        with pytest.raises(RuntimeError, match="WORKER_DATABASE_URL"):
            _prod(worker_database_url="postgresql+asyncpg://worker:salespass@db:5432/d").validate_security()


class TestDemoModeProdAllowsStartupWork:
    """A DEMO deployment in a prod-env (e.g. Render free tier) may run startup
    seed/migrations on its single box — gated by DEMO_MODE."""

    def test_demo_prod_permits_migrations_and_generator(self):
        s = _prod(demo_mode=True, run_migrations_on_startup=True,
                  run_seed_on_startup=True, live_generator_enabled=True,
                  sample_data_enabled=True)
        # Demo users still must not be enabled even in a demo-prod box.
        assert s.validate_security() == []


class TestDevelopmentPermitsLocalDefaults:
    def test_dev_defaults_validate_clean(self):
        s = Settings(environment="development",
                     jwt_secret_key="a-strong-enough-dev-secret-key-32-characters",
                     secret_key="another-strong-enough-dev-secret-key-32chars")
        assert s.validate_security() == []


class TestStagingBehavesLikeProduction:
    def test_staging_rls_off_rejected(self):
        with pytest.raises(RuntimeError, match="USE_RLS_ROLE"):
            Settings(environment="staging",
                     jwt_secret_key="a-very-strong-staging-secret-that-is-adequately-long",
                     secret_key="another-strong-staging-secret-key-for-the-app-layer",
                     database_url="postgresql+asyncpg://u:str0ngp@db:5432/d",
                     use_rls_role=False).validate_security()


class TestDocsExposureFollowsFlag:
    def test_prod_docs_off_by_default(self):
        assert _prod().api_docs_enabled is False

    def test_prod_docs_on_when_flag_set(self):
        assert _prod(expose_api_docs=True).api_docs_enabled is True

    def test_dev_docs_always_on(self):
        assert Settings(environment="development").api_docs_enabled is True
