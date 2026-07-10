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

    # E8-3: check the plan quota BEFORE parsing/validating a possibly-huge file —
    # refusing after ten seconds of work is the same 429 with a worse experience.
    from app.services.usage_metering import enforce_quota
    from app.services.database import async_session
    async with async_session() as _s:
        await enforce_quota(_s, tenant_id, "import")

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
            # E2-4: the job row is created FIRST, so every canonical row this import
            # writes can carry its id and be recorded in the undo ledger. It is
            # marked reversible up front and lives in the same transaction — if the
            # import fails, the job row rolls back with it and never existed.
            job = (await session.execute(text("""
                INSERT INTO import_jobs (tenant_id, import_type, filename, status,
                    total_rows, mapping, created_by, reversible)
                VALUES (:t, :ty, :fn, 'running', :total, CAST(:map AS JSONB), :by, TRUE)
                RETURNING id
            """), {"t": tenant_id, "ty": body.import_type, "fn": body.filename,
                   "total": len(rows), "map": json.dumps(body.mapping),
                   "by": user.get("email")})).fetchone()

            persist = await imp.commit_import(session, tenant_id, body.import_type,
                                              result["valid"], import_job_id=job.id)
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

            await session.execute(text("""
                UPDATE import_jobs
                   SET status = :st, imported_rows = :imp, skipped_rows = :skip,
                       error_rows = :err, notes = CAST(:notes AS JSONB)
                 WHERE id = :jid AND tenant_id = :t
            """), {"st": status, "imp": persist["imported"], "skip": persist["skipped"],
                   "err": error_rows, "jid": job.id, "t": tenant_id,
                   "notes": json.dumps({
                       "skip_reasons": persist["skip_reasons"],
                       "quality": quality,
                       "rejected": {"headers": headers, "rows": rejected},
                   }, default=str)})
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
    # ONE import job, not one per row. The plan limit is "20 imports/month"; metering
    # rows here made a single 5,000-row CSV read as 5,000 imports and would have
    # bricked the free tier the moment enforcement was switched on (E8-3).
    await record_usage(tenant_id, "import", quantity=1,
                       metadata={"import_type": body.import_type,
                                 "rows_imported": persist["imported"]})
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
                   notes -> 'quality' -> 'scorecard' AS scorecard,
                   -- E2-4: the UI must not offer an Undo button for a job that
                   -- cannot be undone (pre-ledger, or already reversed).
                   reversible, rolled_back_at
            FROM import_jobs WHERE tenant_id = :t ORDER BY created_at DESC LIMIT 100
        """), {"t": tenant_id})).mappings().all()
    return {"jobs": [{**dict(r),
                      "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                      "rolled_back_at": r["rolled_back_at"].isoformat() if r["rolled_back_at"] else None,
                      "can_rollback": bool(r["reversible"]) and r["rolled_back_at"] is None}
                     for r in rows]}


# ---------------------------------------------------------------------------
# E2-2 — recurring imports on a schedule.
#
# Route order matters: `/schedules` is a literal and must be declared before any
# `/{job_id}` route that could otherwise capture it.
# ---------------------------------------------------------------------------

class ScheduleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    import_type: str
    source_kind: str = "https"
    # https: the file URL. sftp/imap: a human locator (e.g. "sftp://host/path");
    # the real connection details live in source_config.
    source_url: str = Field("", max_length=2000)
    # sftp: {host, port?, username, password_env|private_key_env, path, known_hosts_env?}
    # imap: {host, port?, username, password_env, mailbox?, subject_contains?, attachment_ext?, mark_seen?}
    # Credentials are referenced by ENV-VAR NAME (…_env), never the secret itself.
    source_config: Dict[str, object] = Field(default_factory=dict)
    mapping: Dict[str, str] = Field(default_factory=dict)
    interval_minutes: int = Field(1440, ge=15, le=10080)
    active: bool = True


@router.get("/schedules")
async def list_schedules(user: dict = Depends(get_current_user)):
    """Recurring imports configured for this tenant (E2-2)."""
    _require_operator(user)
    tenant_id = user.get("tenant_id") or 1
    async with async_session() as session:
        rows = (await session.execute(text("""
            SELECT id, name, import_type, source_kind, source_url, interval_minutes,
                   active, next_run_at, last_run_at, last_status, last_error,
                   last_job_id, consecutive_failures, created_by, created_at
              FROM import_schedules
             WHERE tenant_id = :t
             ORDER BY created_at DESC
        """), {"t": tenant_id})).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("next_run_at", "last_run_at", "created_at"):
            d[k] = d[k].isoformat() if d.get(k) else None
        out.append(d)
    from app.services import import_scheduler as sched
    return {"schedules": out, "supported_source_kinds": list(sched.SUPPORTED_SOURCE_KINDS)}


@router.post("/schedules", status_code=201)
async def create_schedule(body: ScheduleCreate, user: dict = Depends(get_current_user)):
    """Create a recurring import.

    Answers 501 for a transport this build cannot run, rather than storing a
    schedule that would never fire. The URL is fetched by our servers, so it is
    validated against the SSRF guard here, at creation, and again at every run.
    """
    _require_operator(user)
    tenant_id = user.get("tenant_id") or 1
    from app.services import import_scheduler as sched

    if body.import_type not in imp.import_types():
        raise HTTPException(status_code=422, detail="Unknown import type")

    # `email` is a friendly alias the UI may send; the stored transport is `imap`.
    kind = "imap" if body.source_kind == "email" else body.source_kind
    config = dict(body.source_config or {})

    if kind in sched.UNSUPPORTED_SOURCE_KINDS:
        raise HTTPException(
            status_code=501,
            detail={"error": "source_kind_not_implemented", "source_kind": kind,
                    "message": sched.UNSUPPORTED_SOURCE_KINDS[kind],
                    "supported": list(sched.SUPPORTED_SOURCE_KINDS)})
    if kind not in sched.SUPPORTED_SOURCE_KINDS:
        raise HTTPException(status_code=422, detail=f"Unknown source_kind {kind!r}")

    if kind == "https":
        from app.services.sage2.api_source import is_safe_url
        if not is_safe_url(body.source_url):
            raise HTTPException(
                status_code=422,
                detail="source_url must be http(s) to a public host — loopback, private "
                       "and link-local addresses are refused")
    else:
        # sftp/imap: validate config now, and refuse a private/loopback host up front
        # (checked again at every run) so the schedule can't reach internal infra.
        host = config.get("host")
        if not host or not config.get("username"):
            raise HTTPException(status_code=422,
                                detail=f"{kind} requires source_config.host and .username")
        if kind == "sftp" and not config.get("path"):
            raise HTTPException(status_code=422, detail="sftp requires source_config.path")
        if kind == "sftp" and not (config.get("password_env") or config.get("private_key_env")):
            raise HTTPException(status_code=422,
                                detail="sftp requires source_config.password_env or .private_key_env")
        if kind == "imap" and not config.get("password_env"):
            raise HTTPException(status_code=422,
                                detail="imap requires source_config.password_env")
        try:
            sched._assert_safe_host(str(host))
        except sched.FetchError as e:
            raise HTTPException(status_code=422, detail=str(e))

    async with async_session() as session:
        try:
            row = (await session.execute(text("""
                INSERT INTO import_schedules (tenant_id, name, import_type, source_kind,
                    source_url, source_config, mapping, interval_minutes, active, created_by)
                VALUES (:t, :n, :ty, :sk, :url, CAST(:cfg AS JSONB), CAST(:map AS JSONB), :iv, :act, :by)
                RETURNING id, next_run_at
            """), {"t": tenant_id, "n": body.name, "ty": body.import_type,
                   "sk": kind, "url": body.source_url or "",
                   "cfg": json.dumps(config),
                   "map": json.dumps(body.mapping), "iv": body.interval_minutes,
                   "act": body.active, "by": user.get("email")})).mappings().fetchone()
            await session.commit()
        except Exception as e:
            await session.rollback()
            if "import_schedules_tenant_id_name_key" in str(e):
                raise HTTPException(status_code=409,
                                    detail="A schedule with that name already exists")
            logger.error(f"Create import schedule failed (tenant {tenant_id}): {e}")
            raise HTTPException(status_code=500, detail="Could not create the schedule")

    return {"id": row["id"], "next_run_at": row["next_run_at"].isoformat()}


@router.delete("/schedules/{schedule_id}", status_code=204)
async def delete_schedule(schedule_id: int, user: dict = Depends(get_current_user)):
    _require_operator(user)
    tenant_id = user.get("tenant_id") or 1
    async with async_session() as session:
        res = await session.execute(text(
            "DELETE FROM import_schedules WHERE id = :sid AND tenant_id = :t"),
            {"sid": schedule_id, "t": tenant_id})
        await session.commit()
    if not res.rowcount:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return Response(status_code=204)


@router.post("/schedules/{schedule_id}/run-now")
async def run_schedule_now(schedule_id: int, user: dict = Depends(get_current_user)):
    """Run one schedule immediately, without waiting for its next tick.

    Goes through exactly the same code the background loop uses — including the
    unchanged-payload skip, so pressing this twice cannot double-import.
    """
    _require_operator(user)
    tenant_id = user.get("tenant_id") or 1
    from app.services import import_scheduler as sched

    async with async_session() as session:
        row = (await session.execute(text("""
            SELECT id, tenant_id, name, import_type, source_kind, source_url, source_config,
                   mapping, interval_minutes, last_content_hash, consecutive_failures
              FROM import_schedules WHERE id = :sid AND tenant_id = :t
        """), {"sid": schedule_id, "t": tenant_id})).mappings().fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Schedule not found")

    try:
        async with async_session() as session:
            outcome = await sched.run_schedule(session, dict(row))
            await session.commit()
        return outcome
    except sched.ScheduleRunFailed as failure:
        async with async_session() as session:
            await sched._finish(session, failure.schedule_id, status="failed",
                                error=failure.reason[:2000],
                                interval_minutes=failure.interval,
                                failures=failure.failures)
            await session.commit()
        raise HTTPException(status_code=502,
                            detail={"error": "schedule_run_failed", "message": failure.reason})


@router.get("/{job_id}/rollback")
async def rollback_preview(job_id: int, user: dict = Depends(get_current_user)):
    """Can this import be undone, and if not, why not? (E2-4)"""
    _require_operator(user)
    tenant_id = user.get("tenant_id") or 1
    from app.services import import_rollback as rb
    async with async_session() as session:
        status = await rb.rollback_status(session, tenant_id, job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Import job not found")
    return status


@router.post("/{job_id}/rollback")
async def rollback_job(job_id: int, user: dict = Depends(get_current_user)):
    """Undo every row this import wrote. All-or-nothing (E2-4).

    Refuses — rather than approximating — when the job predates the undo ledger,
    when it has already been reversed, or when newer data now references rows the
    import created.
    """
    _require_operator(user)
    tenant_id = user.get("tenant_id") or 1
    from app.services import import_rollback as rb

    async with async_session() as session:
        try:
            result = await rb.rollback_import(session, tenant_id, job_id,
                                              user=user.get("email") or "operator")
            await session.commit()
        except rb.RollbackRefused as refusal:
            await session.rollback()
            code = 404 if refusal.reason == "not_found" else 409
            raise HTTPException(status_code=code,
                                detail={"error": refusal.reason, "message": refusal.detail})
        except Exception as e:
            await session.rollback()
            logger.error(f"Import rollback failed (tenant {tenant_id}, job {job_id}): {e}")
            raise HTTPException(status_code=500,
                                detail="Rollback failed — nothing was changed")

    from app.services.security_events import record_event
    await record_event("import_rolled_back", category="audit", severity="medium",
                       tenant_id=tenant_id, actor_user_id=user.get("id"),
                       actor_email=user.get("email"),
                       detail=f"Import job {job_id} rolled back",
                       evidence=result)
    return result


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
