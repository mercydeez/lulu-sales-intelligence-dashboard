"""
UAE data residency posture + guardrails (E5-3).

Retail IQ targets in-country hosting (AWS me-central-1 / Azure UAE North) for
pilots with residency requirements (B2G hard requirement; enterprise soft one).
This module is the single, honest source of the residency POSTURE the app reports
and the pure checks the startup validator + /health use. It fabricates nothing:
it reports what the operator configured (region, backup region, cross-border
policy, external-AI caveat) — never a claim the deployment can't back.

No secrets are ever exposed here. Region ids and booleans only.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.config import get_settings


def _approved_list(settings) -> List[str]:
    return [r.strip().lower() for r in (settings.approved_data_regions or "").split(",") if r.strip()]


def normalize_region(region: str) -> str:
    return (region or "").strip().lower()


def is_approved_region(region: str, approved: List[str]) -> bool:
    """A region is approved if it contains any approved token (so 'me-central-1'
    matches 'me-central', and 'uae-north-1' matches 'uae-north'/'uae')."""
    r = normalize_region(region)
    if not r:
        return False
    return any(a in r for a in approved)


def residency_posture(settings=None) -> Dict[str, Any]:
    """Safe, public-shareable residency posture. No secrets."""
    s = settings or get_settings()
    approved = _approved_list(s)
    region = s.data_region or None
    region_ok = is_approved_region(s.data_region, approved)
    backup_region = s.backup_region or None
    backup_ok = (not s.backup_region) or is_approved_region(s.backup_region, approved)
    external_ai = bool(getattr(s, "enable_external_ai", False))

    # Overall verdict is honest about what's actually configured.
    if s.data_residency_required and not region_ok:
        status = "non_compliant"
    elif not s.data_region:
        status = "undeclared"
    elif region_ok:
        status = "in_region"
    else:
        status = "out_of_region"

    return {
        "status": status,
        "residency_required": bool(s.data_residency_required),
        "region": region,
        "region_approved": region_ok,
        "approved_regions": approved,
        "backup_region": backup_region,
        "backup_in_region": backup_ok,
        "cross_border_transfer_allowed": bool(s.cross_border_transfer_allowed),
        # External AI (3rd-party LLM) can send data outside the region when enabled.
        "external_ai_enabled": external_ai,
        "external_ai_may_leave_region": external_ai,
        "log_retention_days": int(s.log_retention_days),
        "statement": (
            "Tenant data is hosted in the configured region"
            + (f" ({region})" if region else " (region not declared)")
            + ". "
            + ("Backups are kept in-region. " if backup_ok and backup_region else "")
            + ("No cross-border transfer is permitted. " if not s.cross_border_transfer_allowed else "")
            + ("Note: external AI is enabled and may process data outside the region. "
               if external_ai else "")
        ).strip(),
    }


def validate_residency(settings=None) -> Tuple[List[str], List[str]]:
    """Return (errors, warnings) for the residency config. Errors are only
    surfaced when residency is required. Pure — mirrors the config validator so
    tests can assert without booting the app."""
    s = settings or get_settings()
    errors: List[str] = []
    warnings: List[str] = []
    if not s.data_residency_required:
        return errors, warnings

    approved = _approved_list(s)
    if not is_approved_region(s.data_region, approved):
        errors.append("data_region_not_approved")
    if s.backup_region and not is_approved_region(s.backup_region, approved):
        errors.append("backup_region_not_approved")
    if s.cross_border_transfer_allowed:
        warnings.append("cross_border_transfer_allowed")
    if bool(getattr(s, "enable_external_ai", False)):
        warnings.append("external_ai_may_leave_region")
    return errors, warnings


def residency_health_check(settings=None) -> Dict[str, Any]:
    """Compact residency entry for /health/deep. 'ok' when not required or the
    region is approved; 'degraded' when declared-but-out-of-region; 'unhealthy'
    when required-but-non-compliant. No secrets."""
    p = residency_posture(settings)
    if p["status"] == "non_compliant":
        status = "unhealthy"
    elif p["status"] in ("out_of_region",):
        status = "degraded"
    elif p["status"] == "undeclared":
        status = "unknown"
    else:
        status = "ok"
    return {
        "status": status,
        "residency_status": p["status"],
        "region": p["region"],
        "region_approved": p["region_approved"],
        "backup_in_region": p["backup_in_region"],
        "cross_border_transfer_allowed": p["cross_border_transfer_allowed"],
        "external_ai_may_leave_region": p["external_ai_may_leave_region"],
    }
