"""
Daily Executive Briefing API (blueprint E3-1). Mounted at /api/briefing.

Tenant + accessible-store scoped (RLS via get_db). Assembles the morning brief
from data the platform already computes — no fabrication. `GET /` returns JSON for
the in-app screen; `GET /print` returns a self-contained, emailable/printable
one-pager (→ PDF), mirroring the ROI report artifact.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db
from app.services.briefing import generate_briefing, build_briefing_html
from app.routes.auth import get_current_user, get_accessible_store_ids

router = APIRouter(tags=["Briefing"])


@router.get("")
async def get_briefing(user: dict = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    """The daily executive briefing: headline movement, what changed, what to
    decide, the win, what's coming, and the cost of inaction — all in AED."""
    tenant_id = user.get("tenant_id") or 1
    allowed = get_accessible_store_ids(user)
    return await generate_briefing(db, tenant_id, allowed)


@router.get("/print")
async def print_briefing(user: dict = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    """A shareable one-pager of today's briefing (browser-printable → PDF; the
    same content you'd email an executive)."""
    tenant_id = user.get("tenant_id") or 1
    allowed = get_accessible_store_ids(user)
    briefing = await generate_briefing(db, tenant_id, allowed)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = build_briefing_html(briefing, generated)
    return HTMLResponse(html, headers={
        "Content-Disposition": f'attachment; filename="daily-briefing-{briefing["date"]}.html"'})
