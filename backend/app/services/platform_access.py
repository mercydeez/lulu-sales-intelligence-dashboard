"""Platform-operator boundary (Platform Console) — who may operate ACROSS tenants.

WHY THIS EXISTS. `super_admin` is a TENANT role: every self-signup owner is created
super_admin for their own workspace (services/tenant_provisioning.py). It therefore
cannot double as "the platform team" — yet the cross-tenant surfaces need exactly
that boundary. This module provides it as a per-user flag + optional env allowlist:

    usable = users.is_platform_developer  AND  (allowlist empty OR email in allowlist)

Fail-closed on both sides: no flag -> refused regardless of role; allowlist set but
email absent -> refused even with the flag (defence in depth — a tampered DB row
alone cannot mint platform access where PLATFORM_DEVELOPER_EMAILS is configured).
Every refusal is recorded as a security event.

WHO GETS IT (the access policy, also documented in docs/product/PLATFORM_CONSOLE.md):
platform developers only — the vendor's own engineers. Not tenant admins, not
support, not customers. Grants are a migration/operator action, never self-service.
"""
from __future__ import annotations

from typing import Set

from fastapi import Depends, HTTPException

from app.config import get_settings
from app.auth_deps import get_current_user


def developer_allowlist() -> Set[str]:
    """The PLATFORM_DEVELOPER_EMAILS allowlist, lowercased. Empty set = allowlist
    not configured (the DB flag alone then decides)."""
    raw = get_settings().platform_developer_emails or ""
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_platform_developer(user: dict) -> bool:
    """Pure check — used by routes and testable without FastAPI plumbing."""
    if not user or not user.get("is_platform_developer"):
        return False
    allow = developer_allowlist()
    if allow:
        return (user.get("email") or "").lower() in allow
    return True


async def require_platform_developer(current_user: dict = Depends(get_current_user)) -> dict:
    """FastAPI dependency for Platform Console routes. 403s (and records a security
    event) for anyone who is not a platform developer — including tenant super_admins."""
    if is_platform_developer(current_user):
        return current_user
    # Best-effort audit; the refusal itself must never depend on the event write.
    try:
        from app.services.security_events import record_event
        await record_event(
            "platform_access_denied", category="threat", severity="medium",
            tenant_id=current_user.get("tenant_id"),
            actor_user_id=current_user.get("id"),
            actor_email=current_user.get("email"),
            detail="Platform Console access refused: not a platform developer",
        )
    except Exception:  # noqa: BLE001
        pass
    raise HTTPException(status_code=403, detail="Platform developer access required")
