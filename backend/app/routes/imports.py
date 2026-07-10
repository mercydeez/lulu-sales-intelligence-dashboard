"""
Spreadsheet import API (real-data ingestion). Mounted at /api/imports.

Flow: analyze (detect headers) → validate (map + check every row) → commit (persist).
A CSV arrives as `csv_text`; an Excel workbook arrives base64-encoded as `file_b64`
(E1-3 — UAE reality: it's rarely a CSV). Both are parsed into the SAME
(headers, rows) shape, so validate/commit never learn which it was.

Operator-gated, tenant-scoped. Commits run in one transaction, are audited, and
metered as `import` usage. Units-vs-AED is enforced by the validators.
"""
import base64
import json
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field, model_validator
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


# Base64 inflates ~33%, so this caps a raw workbook near 8 MB — comfortably inside
# BodySizeLimitMiddleware's 10 MB default while covering a 50k-row sheet (xlsx is
# zip-compressed).
_MAX_B64 = 11_000_000


class _SourceMixin(BaseModel):
    """A CSV body OR a base64 workbook — exactly one of them."""
    csv_text: Optional[str] = Field(None, max_length=8_000_000)
    file_b64: Optional[str] = Field(None, max_length=_MAX_B64)

    @model_validator(mode="after")
    def _exactly_one_source(self):
        if not self.csv_text and not self.file_b64:
            raise ValueError("Provide csv_text or file_b64")
        return self


class AnalyzeRequest(_SourceMixin):
    pass


class ImportRequest(_SourceMixin):
    import_type: str
    mapping: Dict[str, str]
    filename: Optional[str] = None


def _parse_source(body: _SourceMixin, sample: Optional[int] = None) -> Tuple[List[str], List[Dict[str, str]]]:
    """Turn either body shape into the one (headers, rows) contract.

    The file's own magic bytes decide the format — a client-declared type is never
    trusted, and a mislabelled .csv renamed to .xlsx fails loudly instead of
    producing mojibake rows.
    """
    if body.file_b64:
        try:
            data = base64.b64decode(body.file_b64, validate=True)
        except Exception:
            raise HTTPException(status_code=422, detail="file_b64 is not valid base64")
        if imp.sniff_workbook_kind(data) is None:
            raise HTTPException(
                status_code=422,
                detail="Not a recognised Excel file. Upload .xlsx or .xls, or send CSV text.",
            )
        try:
            return imp.parse_workbook(data, sample=sample)
        except ValueError as e:
            # Row-limit / corrupt-container errors are the caller's problem, not a 500.
            code = 413 if "row limit" in str(e).lower() or "exceeds" in str(e).lower() else 422
            raise HTTPException(status_code=code, detail=str(e))
    return imp.parse_csv(body.csv_text or "", sample=sample)


@router.get("/types")
async def list_types(user: dict = Depends(get_current_user)):
    """Supported import types + their canonical field schemas (drives the mapper UI)."""
    _require_operator(user)
    return {"types": [imp.schema_for(t) for t in imp.import_types()]}


_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/sample/{import_type}")
async def download_sample(
    import_type: str,
    format: str = Query("csv", pattern="^(csv|xlsx)$"),
    user: dict = Depends(get_current_user),
):
    """A ready-made UAE sample to try the wizard before using real data.

    `?format=xlsx` builds the workbook from the same sample text, so the Excel and
    CSV samples can never drift apart (E1-3)."""
    _require_operator(user)
    if format == "xlsx":
        blob = imp.sample_xlsx(import_type)
        if blob is None:
            raise HTTPException(status_code=404, detail="No sample for that type")
        return Response(blob, media_type=_XLSX_MEDIA, headers={
            "Content-Disposition": f'attachment; filename="sample-{import_type}.xlsx"'})

    csv = imp.sample_csv(import_type)
    if csv is None:
        raise HTTPException(status_code=404, detail="No sample for that type")
    return PlainTextResponse(csv, media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="sample-{import_type}.csv"'})


@router.post("/analyze")
async def analyze(body: AnalyzeRequest, user: dict = Depends(get_current_user)):
    """Detect the file's headers and return a small sample for the mapping step."""
    _require_operator(user)
    headers, rows = _parse_source(body, sample=5)
    if not headers:
        raise HTTPException(status_code=422, detail="No header row found")
    _, all_rows = _parse_source(body)
    if len(all_rows) > imp.MAX_ROWS:
        raise HTTPException(status_code=413, detail=f"Too many rows (max {imp.MAX_ROWS})")
    return {"headers": headers, "sample": rows, "row_count": len(all_rows)}


@router.post("/validate")
async def validate(body: ImportRequest, user: dict = Depends(get_current_user)):
    """Validate every row against the canonical schema; return counts + sample errors."""
    _require_operator(user)
    if body.import_type not in imp.import_types():
        raise HTTPException(status_code=422, detail="Unknown import type")
    headers, rows = _parse_source(body)
    if len(rows) > imp.MAX_ROWS:
        raise HTTPException(status_code=413, detail=f"Too many rows (max {imp.MAX_ROWS})")
    result = imp.validate_rows(body.import_type, headers, rows, body.mapping)
    # E1-5: the scorecard is built from the FULL error/valid sets, not the capped
    # `errors` slice we return — otherwise a 10,000-error file would grade like a
    # 200-error one.
    quality = imp.build_quality_report(body.import_type, result["valid"],
                                       result["errors"], result["summary"]["total"])
    return {"summary": result["summary"], "errors": result["errors"], "quality": quality}


@router.post("/commit")
async def commit(body: ImportRequest, user: dict = Depends(get_current_user)):
    """Validate then persist the rows into the canonical tables (tenant-scoped)."""
    _require_operator(user)
    if body.import_type not in imp.import_types():
        raise HTTPException(status_code=422, detail="Unknown import type")
    tenant_id = user.get("tenant_id") or 1
    headers, rows = _parse_source(body)
    if len(rows) > imp.MAX_ROWS:
        raise HTTPException(status_code=413, detail=f"Too many rows (max {imp.MAX_ROWS})")
    result = imp.validate_rows(body.import_type, headers, rows, body.mapping)
    if not result["valid"]:
        raise HTTPException(status_code=422,
                            detail="No valid rows to import — fix the errors and retry")

    # Same pure builder as /validate, so the preview scorecard equals the persisted one.
    quality = imp.build_quality_report(body.import_type, result["valid"],
                                       result["errors"], result["summary"]["total"])

    async with async_session() as session:
        try:
            persist = await imp.commit_import(session, tenant_id, body.import_type, result["valid"])
            error_rows = result["summary"]["errors"]
            status = ("completed" if (persist["skipped"] == 0 and error_rows == 0)
                      else "partial")

            # Unresolved rows come from two places with different shapes: rows that
            # failed VALIDATION (bad date, negative units) and rows that failed
            # RESOLUTION at commit (store/item name not in the catalogue). The
            # operator wants one file with both.
            rejected = (result["rejected"] + persist["skipped_rows"])[:imp._MAX_REJECTED_STORED]
            quality["rejected_row_count"] = len(result["rejected"]) + persist["skipped"]
            quality["rejected_rows_stored"] = len(rejected)

            job = (await session.execute(text("""
                INSERT INTO import_jobs (tenant_id, import_type, filename, status,
                    total_rows, imported_rows, skipped_rows, error_rows, mapping, notes, created_by)
                VALUES (:t, :ty, :fn, :st, :total, :imp, :skip, :err,
                        CAST(:map AS JSONB), CAST(:notes AS JSONB), :by)
                RETURNING id
            """), {"t": tenant_id, "ty": body.import_type, "fn": body.filename, "st": status,
                   "total": len(rows), "imp": persist["imported"], "skip": persist["skipped"],
                   "err": error_rows, "map": json.dumps(body.mapping),
                   "notes": json.dumps({
                       "skip_reasons": persist["skip_reasons"],
                       "quality": quality,
                       "rejected": {"headers": headers, "rows": rejected},
                   }, default=str),
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
                              "imported": persist["imported"], "skipped": persist["skipped"],
                              "quality_grade": quality["scorecard"]["grade"],
                              "quality_pct": quality["scorecard"]["overall_pct"]})

    # `skipped_rows` is the raw payload for the download endpoint — not part of the
    # HTTP response (it can be 5,000 rows).
    persist.pop("skipped_rows", None)
    return {"job_id": job.id, "status": status, **persist,
            "total_rows": len(rows), "error_rows": result["summary"]["errors"],
            "quality": quality}


@router.get("")
async def list_jobs(user: dict = Depends(get_current_user)):
    """Import history for the tenant."""
    _require_operator(user)
    tenant_id = user.get("tenant_id") or 1
    async with async_session() as session:
        rows = (await session.execute(text("""
            SELECT id, import_type, filename, status, total_rows, imported_rows,
                   skipped_rows, error_rows, created_by, created_at,
                   -- so the UI knows whether to offer the download, without
                   -- shipping the whole rejected payload in the list response.
                   COALESCE(jsonb_array_length(notes -> 'rejected' -> 'rows'), 0) AS rejected_rows,
                   notes -> 'quality' -> 'scorecard' AS scorecard
            FROM import_jobs WHERE tenant_id = :t ORDER BY created_at DESC LIMIT 100
        """), {"t": tenant_id})).mappings().all()
    return {"jobs": [{**dict(r), "created_at": r["created_at"].isoformat() if r["created_at"] else None}
                     for r in rows]}


@router.get("/{job_id}/unresolved.csv", response_class=PlainTextResponse)
async def download_unresolved(job_id: int, user: dict = Depends(get_current_user)):
    """The rows we could not use, as CSV — the operator's own columns plus why each
    one failed (E1-5). Fix them in place and re-upload just this file.

    Trust: the product admits what it can't see. A silent skip is a lie of omission.
    """
    _require_operator(user)
    tenant_id = user.get("tenant_id") or 1
    async with async_session() as session:
        row = (await session.execute(text("""
            SELECT filename, notes FROM import_jobs
             WHERE id = :id AND tenant_id = :t
        """), {"id": job_id, "t": tenant_id})).mappings().fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Import job not found")

    notes = row["notes"] or {}
    if isinstance(notes, str):
        notes = json.loads(notes)
    rejected = (notes.get("rejected") or {})
    rows_out = rejected.get("rows") or []
    if not rows_out:
        raise HTTPException(status_code=404, detail="This import had no unresolved rows")

    csv_text = imp.rejected_rows_csv(rejected.get("headers") or [], rows_out)
    return PlainTextResponse(csv_text, media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="unresolved-job-{job_id}.csv"'})
