"""
ROI / value API (the AED number that closes a pilot). Mounted at /api/roi.

Tenant-scoped (RLS via get_db). Returns only honest, derivable AED metrics; fields
that need un-imported data are null with a `needs` hint, never fabricated.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db
from app.services.roi import roi_summary, build_report_html, build_report_csv
from app.auth_deps import get_current_user, get_accessible_store_ids

router = APIRouter(tags=["ROI"])


@router.get("/summary")
async def get_roi_summary(user: dict = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    """Cash-in-inventory, dead-stock AED, estimated stockout loss, GMROI, days of
    supply — computed from the tenant's real inventory + sales."""
    tenant_id = user.get("tenant_id") or 1
    return await roi_summary(db, tenant_id, get_accessible_store_ids(user))


async def _company_name(db: AsyncSession, tenant_id: int) -> str:
    row = (await db.execute(text("""
        SELECT COALESCE(
            (SELECT legal_name FROM tenant_billing_profile WHERE tenant_id = :t),
            (SELECT name FROM tenants WHERE id = :t)) AS name
    """), {"t": tenant_id})).fetchone()
    return (row.name if row and row.name else "Your company")


@router.get("/report")
async def roi_report(fmt: str = Query("html", pattern="^(html|csv)$"),
                     user: dict = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    """A shareable inventory-value report for the buyer's finance team. `html` is a
    self-contained, browser-printable one-pager (→ PDF); `csv` for spreadsheets."""
    tenant_id = user.get("tenant_id") or 1
    summary = await roi_summary(db, tenant_id, get_accessible_store_ids(user))
    if fmt == "csv":
        return PlainTextResponse(build_report_csv(summary), media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="inventory-value.csv"'})
    company = await _company_name(db, tenant_id)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    html = build_report_html(summary, company, generated)
    return HTMLResponse(html, headers={
        "Content-Disposition": 'attachment; filename="inventory-value-summary.html"'})
