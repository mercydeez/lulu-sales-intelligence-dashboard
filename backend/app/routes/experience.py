"""
Role Experience API (Experience API v2 — Sage Copilot). Mounted at /api/experience.

Returns the caller's resolved experience config — persona pack, assistant mode,
homepage layout/zones, KPI descriptors, navigation manifest, quick actions, AI
display context, capabilities, decision scope — so the frontend renders the
entire role experience from configuration instead of duplicated pages or
hardcoded role checks.

Security: `resolve_config` strips the persona's server-only prompt fragment, so
no system-prompt text is ever returned here; AI authorization stays server-side
in `routes/ai.py`. `capabilities` are rendering hints only.
"""
from fastapi import APIRouter, Depends

from app.routes.auth import get_current_user, get_accessible_store_ids
from app.services.role_experience import resolve_config

router = APIRouter(tags=["Experience"])


@router.get("")
async def get_experience(user: dict = Depends(get_current_user)):
    """The caller's role experience config (server-driven UI, v2)."""
    cfg = resolve_config(user.get("role"))
    allowed = get_accessible_store_ids(user) or []
    cfg["context"] = {
        "accessible_store_count": len(allowed),
    }
    return cfg
