"""
Role Experience API (blueprint Wave 1). Mounted at /api/experience.

Returns the caller's resolved experience config — persona pack, homepage zones,
KPI descriptors, navigation manifest, decision scope — so the frontend renders
role-specific surfaces from configuration instead of duplicated pages.
"""
from fastapi import APIRouter, Depends

from app.routes.auth import get_current_user, get_accessible_store_ids
from app.services.role_experience import resolve_config

router = APIRouter(tags=["Experience"])


@router.get("")
async def get_experience(user: dict = Depends(get_current_user)):
    """The caller's role experience config (server-driven UI)."""
    cfg = resolve_config(user.get("role"))
    allowed = get_accessible_store_ids(user) or []
    cfg["context"] = {
        "accessible_store_count": len(allowed),
    }
    return cfg
