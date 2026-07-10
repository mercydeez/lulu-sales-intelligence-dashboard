"""E2-1 — POS connector routes. Mounted at /api/pos.

All endpoints are tenant-admin authenticated. Connecting a real vendor is refused
(the OAuth + receipt adapter is not built); `mock` connects and syncs so the whole
flow — connect → sync → basket grain — is demoable without a real POS account.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db
from app.routes.auth import get_current_user
from app.services import pos_connectors as pos

router = APIRouter(tags=["POS Connectors"])


def _require_admin(user: dict) -> None:
    if user.get("role") not in ("super_admin", "admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin role required")


class ConnectRequest(BaseModel):
    vendor: str = Field("mock", pattern="^(mock|square|foodics|omnivore|lightspeed)$")
    redirect_uri: Optional[str] = None


class SyncRequest(BaseModel):
    window_days: Optional[int] = Field(None, ge=1, le=90)


@router.get("/vendors")
async def vendors(user: dict = Depends(get_current_user)):
    """Which POS vendors are recognised / configured / usable — honest status."""
    _require_admin(user)
    return {"vendors": pos.vendor_status()}


@router.get("/connections")
async def connections(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _require_admin(user)
    tenant_id = user.get("tenant_id") or 1
    rows = await pos.list_connections(db, tenant_id)
    for r in rows:
        for k in ("connected_at", "last_sync_at"):
            if r.get(k):
                r[k] = r[k].isoformat()
    return {"connections": rows}


@router.post("/connect", status_code=201)
async def connect(body: ConnectRequest, user: dict = Depends(get_current_user),
                  db: AsyncSession = Depends(get_db)):
    """Connect a POS vendor. `mock` connects immediately; a real vendor is refused
    (422) until its OAuth + receipt adapter is integrated."""
    _require_admin(user)
    tenant_id = user.get("tenant_id") or 1
    redirect_uri = body.redirect_uri or "https://app.local/settings/integrations"
    conn, err = await pos.begin_oauth(db, tenant_id=tenant_id, vendor=body.vendor,
                                      redirect_uri=redirect_uri, actor=user.get("email") or "admin")
    if err:
        raise HTTPException(status_code=422, detail=err)
    await db.commit()
    from app.services.security_events import record_event
    await record_event("pos_connection_created", category="audit", severity="low",
                       tenant_id=tenant_id, actor_user_id=user.get("id"),
                       actor_email=user.get("email"),
                       detail=f"POS vendor {body.vendor} connected (conn {conn['connection_id']})")
    return conn


@router.post("/connections/{connection_id}/sync")
async def sync(connection_id: int, body: SyncRequest, user: dict = Depends(get_current_user),
               db: AsyncSession = Depends(get_db)):
    """Trigger a sync now (on-demand; the nightly loop does the same unattended)."""
    _require_admin(user)
    tenant_id = user.get("tenant_id") or 1
    summary, err = await pos.sync_connection(db, tenant_id=tenant_id,
                                             connection_id=connection_id,
                                             window_days=body.window_days)
    if err:
        code = 404 if "not found" in err.lower() else 422
        raise HTTPException(status_code=code, detail=err)
    return summary


@router.get("/connections/{connection_id}/runs")
async def runs(connection_id: int, user: dict = Depends(get_current_user),
               db: AsyncSession = Depends(get_db)):
    _require_admin(user)
    tenant_id = user.get("tenant_id") or 1
    conn = await pos.get_connection(db, tenant_id, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="POS connection not found")
    rows = (await db.execute(text("""
        SELECT id, started_at, finished_at, status, window_start, window_end,
               receipts_ingested, lines_ingested, aggregates_computed, error
          FROM pos_sync_runs WHERE connection_id = :c AND tenant_id = :t
         ORDER BY started_at DESC LIMIT 50
    """), {"c": connection_id, "t": tenant_id})).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("started_at", "finished_at"):
            d[k] = d[k].isoformat() if d.get(k) else None
        for k in ("window_start", "window_end"):
            d[k] = d[k].isoformat() if d.get(k) else None
        out.append(d)
    return {"runs": out}


@router.delete("/connections/{connection_id}")
async def delete_connection(connection_id: int, user: dict = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    _require_admin(user)
    tenant_id = user.get("tenant_id") or 1
    ok = await pos.disconnect(db, tenant_id, connection_id)
    if not ok:
        raise HTTPException(status_code=404, detail="POS connection not found")
    await db.commit()
    return {"status": "disconnected", "connection_id": connection_id}
