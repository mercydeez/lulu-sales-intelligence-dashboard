"""
CSV import API (real-data ingestion). Mounted at /api/imports.

Flow: analyze (detect headers) → validate (map + check every row) → commit (persist).
The retailer's CSV text is sent in the JSON body (the frontend reads the file with
FileReader). Operator-gated, tenant-scoped. Commits run in one transaction, are
audited, and metered as `import` usage. Units-vs-AED is enforced by the validators.
"""
import json
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.services.database import async_session
from app.services import csv_import as imp
from app.routes.auth import get_current_user
from app.config import logger

router = APIRouter(tags=["Imports"])


def _require_operator(user: dict) -> None:
    role = user.get("role")
    perms = user.get("permissions", {}) or {}
    if role in ("super_admin", "admin", "regional_manager", "store_manager") or perms.get("can_manage_inventory"):
        return
    raise HTTPException(status_code=403, detail="Operator role required")


class AnalyzeRequest(BaseModel):
    csv_text: str = Field(..., max_length=8_000_000)


class ImportRequest(BaseModel):
    import_type: str
    mapping: Dict[str, str]
    csv_text: str = Field(..., max_length=8_000_000)
    filename: Optional[str] = None


@router.get("/types")
async def list_types(user: dict = Depends(get_current_user)):
    """Supported import types + their canonical field schemas (drives the mapper UI)."""
    _require_operator(user)
    return {"types": [imp.schema_for(t) for t in imp.import_types()]}


@router.get("/sample/{import_type}", response_class=PlainTextResponse)
async def download_sample(import_type: str, user: dict = Depends(get_current_user)):
    """A ready-made UAE sample CSV to try the wizard before using real data."""
    _require_operator(user)
    csv = imp.sample_csv(import_type)
    if csv is None:
        raise HTTPException(status_code=404, detail="No sample for that type")
    return PlainTextResponse(csv, media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="sample-{import_type}.csv"'})


@router.post("/analyze")
async def analyze(body: AnalyzeRequest, user: dict = Depends(get_current_user)):
    """Detect the CSV's headers and return a small sample for the mapping step."""
    _require_operator(user)
    headers, rows = imp.parse_csv(body.csv_text, sample=5)
    if not headers:
        raise HTTPException(status_code=422, detail="No CSV header row found")
    _, all_rows = imp.parse_csv(body.csv_text)
    if len(all_rows) > imp.MAX_ROWS:
        raise HTTPException(status_code=413, detail=f"Too many rows (max {imp.MAX_ROWS})")
    return {"headers": headers, "sample": rows, "row_count": len(all_rows)}


@router.post("/validate")
async def validate(body: ImportRequest, user: dict = Depends(get_current_user)):
    """Validate every row against the canonical schema; return counts + sample errors."""
    _require_operator(user)
    if body.import_type not in imp.import_types():
        raise HTTPException(status_code=422, detail="Unknown import type")
    headers, rows = imp.parse_csv(body.csv_text)
    if len(rows) > imp.MAX_ROWS:
        raise HTTPException(status_code=413, detail=f"Too many rows (max {imp.MAX_ROWS})")
    result = imp.validate_rows(body.import_type, headers, rows, body.mapping)
    return {"summary": result["summary"], "errors": result["errors"]}


@router.post("/commit")
async def commit(body: ImportRequest, user: dict = Depends(get_current_user)):
    """Validate then persist the rows into the canonical tables (tenant-scoped)."""
    _require_operator(user)
    if body.import_type not in imp.import_types():
        raise HTTPException(status_code=422, detail="Unknown import type")
    tenant_id = user.get("tenant_id") or 1
    headers, rows = imp.parse_csv(body.csv_text)
    if len(rows) > imp.MAX_ROWS:
        raise HTTPException(status_code=413, detail=f"Too many rows (max {imp.MAX_ROWS})")
    result = imp.validate_rows(body.import_type, headers, rows, body.mapping)
    if not result["valid"]:
        raise HTTPException(status_code=422,
                            detail="No valid rows to import — fix the errors and retry")

    async with async_session() as session:
        try:
            persist = await imp.commit_import(session, tenant_id, body.import_type, result["valid"])
            error_rows = result["summary"]["errors"]
            status = ("completed" if (persist["skipped"] == 0 and error_rows == 0)
                      else "partial")
            job = (await session.execute(text("""
                INSERT INTO import_jobs (tenant_id, import_type, filename, status,
                    total_rows, imported_rows, skipped_rows, error_rows, mapping, notes, created_by)
                VALUES (:t, :ty, :fn, :st, :total, :imp, :skip, :err,
                        CAST(:map AS JSONB), CAST(:notes AS JSONB), :by)
                RETURNING id
            """), {"t": tenant_id, "ty": body.import_type, "fn": body.filename, "st": status,
                   "total": len(rows), "imp": persist["imported"], "skip": persist["skipped"],
                   "err": error_rows, "map": json.dumps(body.mapping),
                   "notes": json.dumps({"skip_reasons": persist["skip_reasons"]}),
                   "by": user.get("email")})).fetchone()
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"CSV import commit failed (tenant {tenant_id}): {e}")
            raise HTTPException(status_code=500, detail="Import failed — no rows were written")

    from app.services.security_events import record_event
    await record_event("data_imported", category="audit", severity="low",
                       tenant_id=tenant_id, actor_user_id=user.get("id"),
                       actor_email=user.get("email"),
                       detail=f"Imported {persist['imported']} {body.import_type} row(s)",
                       evidence={"import_type": body.import_type, "imported": persist["imported"],
                                 "skipped": persist["skipped"], "job_id": job.id})
    from app.services.usage_metering import record_usage
    await record_usage(tenant_id, "import", quantity=persist["imported"],
                       metadata={"import_type": body.import_type})
    from app.services.notifications import notify
    await notify(tenant_id, type="export", severity="low",
                 title=f"Import completed: {persist['imported']} {body.import_type} rows",
                 link="/imports", metadata={"job_id": job.id})
    from app.services.webhook_service import dispatch_event_background
    dispatch_event_background(tenant_id, "import.completed",
                             {"job_id": job.id, "import_type": body.import_type,
                              "imported": persist["imported"], "skipped": persist["skipped"]})

    return {"job_id": job.id, "status": status, **persist,
            "total_rows": len(rows), "error_rows": result["summary"]["errors"]}


@router.get("")
async def list_jobs(user: dict = Depends(get_current_user)):
    """Import history for the tenant."""
    _require_operator(user)
    tenant_id = user.get("tenant_id") or 1
    async with async_session() as session:
        rows = (await session.execute(text("""
            SELECT id, import_type, filename, status, total_rows, imported_rows,
                   skipped_rows, error_rows, created_by, created_at
            FROM import_jobs WHERE tenant_id = :t ORDER BY created_at DESC LIMIT 100
        """), {"t": tenant_id})).mappings().all()
    return {"jobs": [{**dict(r), "created_at": r["created_at"].isoformat() if r["created_at"] else None}
                     for r in rows]}
