"""
Sage Copilot feed API (SAGE_COPILOT_ARCHITECTURE §3.3, Phase 2). Mounted at
/api/ai/copilot.

The proactive layer: one LLM-free, role-scoped composition of what the platform
already knows — briefing verdict, the decisions that need the caller, risks,
opportunities, forecast and recommended actions. Auth is plain get_current_user
(not the AI-chat gate): every section is data the caller can already fetch from
/api/briefing, /api/decisions and /api/roi under the same store scoping.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db
from app.services.sage_copilot import generate_feed
from app.services.role_experience import decision_scope_for
from app.auth_deps import get_current_user, get_accessible_store_ids

router = APIRouter(tags=["Sage Copilot"])


@router.get("/feed")
async def get_feed(user: dict = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)):
    """The copilot feed: business health, top decisions, risks, opportunities,
    forecast and recommended actions — composed from existing grounded engines,
    scoped by the caller's role config (chain / region / store)."""
    tenant_id = user.get("tenant_id") or 1
    allowed = get_accessible_store_ids(user)
    scope = decision_scope_for(user.get("role"))
    return await generate_feed(db, tenant_id, user.get("role"), allowed, scope=scope)
