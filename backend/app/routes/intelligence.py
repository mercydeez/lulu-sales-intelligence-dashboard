"""
Proactive intelligence API — the Risk Radar.

  GET  /api/intelligence/risks          tenant-scoped ranked open findings (auth)
  POST /api/intelligence/scan           trigger a scan for the caller's tenant (super_admin)
  POST /api/intelligence/scan/internal  trigger an all-tenant scan (BullMQ worker, token-guarded)
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.routes.auth import get_current_user
from app.services.database import get_db
from app.services.intelligence import run_scan, run_scan_all_tenants

router = APIRouter()
settings = get_settings()


@router.get("/risks")
async def list_risks(
    severity: Optional[str] = Query(None, description="high | medium | low"),
    type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ranked, open risk findings for the caller's tenant (highest score first)."""
    tenant_id = current_user.get("tenant_id") or 1
    rows = (await db.execute(text("""
        SELECT id, type, severity, score, title, detail, store_id, item_id, metric,
               status, created_at, updated_at
        FROM risk_findings
        WHERE tenant_id = :tid AND status = 'open'
          AND (CAST(:sev AS text) IS NULL OR severity = :sev)
          AND (CAST(:typ AS text) IS NULL OR type = :typ)
        ORDER BY score DESC, updated_at DESC
        LIMIT :lim
    """), {"tid": tenant_id, "sev": severity, "typ": type, "lim": limit})).fetchall()

    findings = [{
        "id": r.id, "type": r.type, "severity": r.severity, "score": float(r.score),
        "title": r.title, "detail": r.detail, "store_id": r.store_id, "item_id": r.item_id,
        "metric": r.metric, "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    } for r in rows]

    by_sev = {"high": 0, "medium": 0, "low": 0}
    for f in findings:
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1

    return {"count": len(findings), "by_severity": by_sev, "findings": findings}


@router.post("/scan")
async def trigger_scan(current_user: dict = Depends(get_current_user)):
    """Manually run a scan for the caller's tenant (super_admin only)."""
    if current_user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="super_admin required")
    return await run_scan(current_user.get("tenant_id") or 1)


@router.post("/scan/internal")
async def trigger_scan_internal(x_internal_token: Optional[str] = Header(None)):
    """All-tenant scan, called by the BullMQ worker on a schedule. Guarded by a
    shared internal token (never exposed to browsers)."""
    if not settings.internal_api_token or x_internal_token != settings.internal_api_token:
        raise HTTPException(status_code=401, detail="invalid internal token")
    return await run_scan_all_tenants()
