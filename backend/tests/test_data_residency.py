"""
E5-3 — UAE data residency posture + guardrails. Pure; no DB/network/secrets.
"""
from types import SimpleNamespace

from app.services import data_residency as dr


def _s(**over):
    base = dict(
        approved_data_regions="me-central-1,me-central,uae-north,uae,ae",
        data_region="", data_residency_required=False, backup_region="",
        cross_border_transfer_allowed=False, enable_external_ai=False,
        log_retention_days=30, data_residency_statement_enabled=True,
    )
    base.update(over)
    return SimpleNamespace(**base)


# --- region matching --------------------------------------------------------
def test_is_approved_region():
    approved = ["me-central", "uae-north", "uae"]
    assert dr.is_approved_region("me-central-1", approved) is True
    assert dr.is_approved_region("uae-north-1", approved) is True
    assert dr.is_approved_region("UAE-North", approved) is True     # case-insensitive
    assert dr.is_approved_region("us-east-1", approved) is False
    assert dr.is_approved_region("", approved) is False


# --- posture ----------------------------------------------------------------
def test_posture_undeclared_by_default():
    p = dr.residency_posture(_s())
    assert p["status"] == "undeclared" and p["region"] is None
    assert p["region_approved"] is False


def test_posture_in_region():
    p = dr.residency_posture(_s(data_region="me-central-1", data_residency_required=True))
    assert p["status"] == "in_region" and p["region_approved"] is True


def test_posture_non_compliant_when_required_and_wrong_region():
    p = dr.residency_posture(_s(data_region="us-east-1", data_residency_required=True))
    assert p["status"] == "non_compliant" and p["region_approved"] is False


def test_posture_out_of_region_when_declared_wrong_but_not_required():
    p = dr.residency_posture(_s(data_region="eu-west-1", data_residency_required=False))
    assert p["status"] == "out_of_region"


def test_posture_surfaces_external_ai_and_no_secrets():
    p = dr.residency_posture(_s(data_region="me-central-1", enable_external_ai=True))
    assert p["external_ai_may_leave_region"] is True
    blob = str(p).lower()
    assert "secret" not in blob and "password" not in blob and "://" not in blob


def test_posture_backup_region():
    p = dr.residency_posture(_s(data_region="me-central-1", backup_region="us-east-1"))
    assert p["backup_in_region"] is False
    p2 = dr.residency_posture(_s(data_region="me-central-1", backup_region="me-central-1"))
    assert p2["backup_in_region"] is True


# --- validate_residency -----------------------------------------------------
def test_validate_not_required_is_noop():
    errs, warns = dr.validate_residency(_s(data_region="us-east-1"))
    assert errs == [] and warns == []


def test_validate_required_bad_region_errors():
    errs, warns = dr.validate_residency(_s(data_residency_required=True, data_region="us-east-1"))
    assert "data_region_not_approved" in errs


def test_validate_required_good_region_ok():
    errs, warns = dr.validate_residency(_s(data_residency_required=True, data_region="me-central-1"))
    assert errs == []


def test_validate_backup_region_and_flags():
    errs, warns = dr.validate_residency(_s(
        data_residency_required=True, data_region="me-central-1", backup_region="eu-west-1",
        cross_border_transfer_allowed=True, enable_external_ai=True))
    assert "backup_region_not_approved" in errs
    assert "cross_border_transfer_allowed" in warns
    assert "external_ai_may_leave_region" in warns


# --- health check mapping ---------------------------------------------------
def test_health_check_states():
    assert dr.residency_health_check(_s())["status"] == "unknown"  # undeclared
    assert dr.residency_health_check(_s(data_region="me-central-1"))["status"] == "ok"
    assert dr.residency_health_check(_s(data_region="eu-west-1"))["status"] == "degraded"
    assert dr.residency_health_check(
        _s(data_region="eu-west-1", data_residency_required=True))["status"] == "unhealthy"


# --- config integration (dev warns, does not raise) -------------------------
def test_config_validate_security_residency_warns_in_dev():
    from app.config import Settings
    s = Settings(environment="development", jwt_secret_key="x" * 40, secret_key="y" * 40,
                 data_residency_required=True, data_region="us-east-1")
    issues = s.validate_security()
    assert any("residency" in i.lower() or "DATA_REGION" in i for i in issues)


def test_config_validate_security_residency_raises_in_prod():
    import pytest
    from app.config import Settings
    s = Settings(environment="production", jwt_secret_key="x" * 40, secret_key="z" * 40,
                 database_url="postgresql+asyncpg://u:strongpass@db:5432/app",
                 cors_origins="https://app.example.com", use_rls_role=True,
                 data_residency_required=True, data_region="us-east-1")
    with pytest.raises(RuntimeError):
        s.validate_security()


def test_config_validate_security_backup_region_raises_in_prod():
    # An out-of-region backup is a hard residency violation → fail closed in prod.
    import pytest
    from app.config import Settings
    s = Settings(environment="production", jwt_secret_key="x" * 40, secret_key="z" * 40,
                 database_url="postgresql+asyncpg://u:strongpass@db:5432/app",
                 cors_origins="https://app.example.com", use_rls_role=True,
                 data_residency_required=True, data_region="me-central-1",
                 backup_region="us-east-1")
    with pytest.raises(RuntimeError):
        s.validate_security()
