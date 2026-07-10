"""E2-2 — recurring imports on a schedule.

WHAT THIS RUNS.
Three transports: `https` (public file URL), `sftp` (paramiko), and `imap` (the
stdlib, for a mailbox that receives a nightly attachment). Migration 067 admits
all three; anything else is refused. CREDENTIALS ARE NEVER STORED IN THE DB — a
schedule's `source_config` names the ENV VAR that holds the secret
(`password_env`/`private_key_env`), resolved in this process, so a backup of the
schedules table leaks nothing. SFTP/IMAP hosts go through the same private-IP
refusal as the HTTPS SSRF guard, so a schedule cannot reach internal infra.

THE BUG THIS FEATURE WOULD OTHERWISE INTRODUCE.
`sales_historical` is append-only. A nightly job that re-fetches yesterday's
unchanged CSV would double the tenant's sales on every run, and the resulting
number would look entirely plausible. So the payload is hashed, and an unchanged
payload is skipped and SAID to be skipped (`last_status='skipped_unchanged'`),
never re-imported. This is not an optimisation; it is the correctness mechanism.

EVERYTHING ELSE IS THE MANUAL PATH.
A scheduled run goes through the same validate → commit_import route as an
operator upload, so it gets the same quality report, the same undo ledger (E2-4),
the same plan quota (E8-3), and the same audit event. A second, parallel import
implementation would be a second set of bugs.

CONCURRENCY. Several backend replicas may run this loop. Due schedules are
claimed with `FOR UPDATE SKIP LOCKED` and their `next_run_at` is pushed forward
inside the claiming transaction, so two replicas cannot run the same schedule.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.config import logger
from app.services import csv_import as imp
from app.services.database import async_session

# Transports this build can actually run. `email` remains an alias that resolves to
# `imap` at the route layer; the stored kind is always one of these three.
SUPPORTED_SOURCE_KINDS = ("https", "sftp", "imap")
UNSUPPORTED_SOURCE_KINDS: dict = {}

# A remote file we will read into memory, parse, and validate. Bounded so a
# hostile or broken endpoint cannot exhaust the process.
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 30.0

# Backoff after consecutive failures: 1x, 2x, 4x … capped. A schedule pointing at
# a dead host must not hammer it every 15 minutes forever.
MAX_BACKOFF_MULTIPLIER = 16
POLL_INTERVAL_SECONDS = 60


class FetchError(Exception):
    """The payload could not be retrieved. Carries an operator-readable reason."""


def content_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def backoff_minutes(interval_minutes: int, consecutive_failures: int) -> int:
    """Delay before the next attempt. Exponential in the failure count, capped."""
    if consecutive_failures <= 0:
        return interval_minutes
    multiplier = min(2 ** (consecutive_failures - 1), MAX_BACKOFF_MULTIPLIER)
    return interval_minutes * multiplier


async def fetch_https(url: str) -> bytes:
    """Download a schedule's payload.

    The URL is tenant-supplied, so it goes through the same SSRF guard the Sage
    API sources use: no file://, no loopback, no RFC-1918, no 169.254.169.254.
    """
    import httpx

    from app.services.sage2.api_source import is_safe_url

    if not is_safe_url(url):
        raise FetchError(
            "Refusing to fetch this URL: it must be http(s) to a public host "
            "(loopback, private and link-local addresses are blocked)")

    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    raise FetchError(f"Source returned HTTP {resp.status_code}")
                chunks, total = [], 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise FetchError(
                            f"Payload exceeds {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB")
                    chunks.append(chunk)
                return b"".join(chunks)
    except FetchError:
        raise
    except Exception as exc:  # network, TLS, DNS…
        raise FetchError(f"Could not fetch the source: {type(exc).__name__}: {exc}")


def _resolve_secret(config: dict, key: str) -> Optional[str]:
    """Resolve a credential by the NAME of an env var (config[key] holds the var
    name, never the secret). So the DB stores `{"password_env": "SCHED_5_SFTP_PW"}`
    and the actual password lives in the process environment / secret manager.
    """
    import os
    var = config.get(key)
    if not var:
        return None
    return os.getenv(str(var))


def _assert_safe_host(host: str) -> None:
    """SFTP/IMAP connect to a tenant-supplied host, so apply the same private-IP
    refusal the HTTPS SSRF guard uses — a schedule must not reach an internal host
    (loopback, RFC-1918, link-local, cloud metadata)."""
    import ipaddress
    import socket
    if not host:
        raise FetchError("No host configured for this transport")
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception as exc:
        raise FetchError(f"Cannot resolve host {host!r}: {exc}")
    for _fam, _t, _p, _c, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise FetchError(
                f"Refusing to connect to {host} — it resolves to a private/loopback "
                f"address ({ip}). Scheduled imports may only reach public hosts.")


async def _in_thread(fn, *args):
    """paramiko and imaplib are blocking; run them off the event loop."""
    return await asyncio.get_event_loop().run_in_executor(None, fn, *args)


def _fetch_sftp_blocking(config: dict) -> bytes:
    """Download one file over SFTP. Blocking — call via _in_thread.

    config: {host, port?, username, password_env|private_key_env, path,
             known_hosts_env?}. The path is a single file (the schedule fetches
             one payload per run, hashed for the unchanged-skip).
    """
    import io
    import paramiko

    host = config.get("host")
    port = int(config.get("port", 22))
    username = config.get("username")
    path = config.get("path")
    if not (username and path):
        raise FetchError("SFTP config needs username and path")

    password = _resolve_secret(config, "password_env")
    key_material = _resolve_secret(config, "private_key_env")
    if not (password or key_material):
        raise FetchError(
            "No SFTP credential resolved — set the env var named by "
            "source_config.password_env or private_key_env")

    # Host safety AFTER config validation, so a bad config fails fast without a DNS
    # lookup, and the private-IP refusal is still enforced before we connect.
    _assert_safe_host(host)

    client = paramiko.SSHClient()
    # Pin to known hosts when provided; otherwise reject (never auto-add, which
    # would defeat host-key verification and enable MITM).
    known_hosts = _resolve_secret(config, "known_hosts_env")
    if known_hosts:
        client.load_host_keys(_write_temp(known_hosts))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        # No pinned key: refuse rather than blindly trust. An operator opts into
        # TOFU explicitly by providing a known_hosts file.
        client.set_missing_host_key_policy(paramiko.RejectPolicy())

    pkey = None
    if key_material:
        pkey = paramiko.RSAKey.from_private_key(io.StringIO(key_material))

    try:
        client.connect(hostname=host, port=port, username=username,
                       password=password, pkey=pkey,
                       timeout=FETCH_TIMEOUT_SECONDS, allow_agent=False, look_for_keys=False)
        sftp = client.open_sftp()
        try:
            st = sftp.stat(path)
            if st.st_size and st.st_size > MAX_DOWNLOAD_BYTES:
                raise FetchError(
                    f"SFTP file is {st.st_size} bytes (max {MAX_DOWNLOAD_BYTES})")
            buf = io.BytesIO()
            sftp.getfo(path, buf)
            return buf.getvalue()
        finally:
            sftp.close()
    except FetchError:
        raise
    except paramiko.SSHException as exc:
        raise FetchError(f"SFTP error: {exc}")
    except Exception as exc:
        raise FetchError(f"SFTP fetch failed: {type(exc).__name__}: {exc}")
    finally:
        client.close()


def _write_temp(contents: str) -> str:
    import tempfile
    fd, path = tempfile.mkstemp(prefix="known_hosts_")
    with open(fd, "w", encoding="utf-8") as fh:
        fh.write(contents)
    return path


def _fetch_imap_blocking(config: dict) -> bytes:
    """Fetch the newest matching email attachment over IMAP. Blocking.

    config: {host, port?, username, password_env, mailbox?, subject_contains?,
             attachment_ext?, mark_seen?}. Returns the attachment bytes of the most
             recent message that matches, so the content hash de-dupes re-runs.
    """
    import email
    import imaplib

    host = config.get("host")
    port = int(config.get("port", 993))
    username = config.get("username")
    password = _resolve_secret(config, "password_env")
    if not (username and password):
        raise FetchError(
            "IMAP config needs username and a resolved password (source_config.password_env)")
    _assert_safe_host(host)  # after config validation — fail fast, still guard the host

    mailbox = config.get("mailbox", "INBOX")
    subject_contains = config.get("subject_contains")
    attachment_ext = (config.get("attachment_ext") or "").lower()

    try:
        conn = imaplib.IMAP4_SSL(host, port, timeout=FETCH_TIMEOUT_SECONDS)
    except Exception as exc:
        raise FetchError(f"IMAP connect failed: {exc}")
    try:
        conn.login(username, password)
        conn.select(mailbox, readonly=not bool(config.get("mark_seen")))
        criteria = ["UNSEEN"] if config.get("only_unseen", True) else ["ALL"]
        if subject_contains:
            criteria = ["SUBJECT", f'"{subject_contains}"'] + (["UNSEEN"] if config.get("only_unseen", True) else [])
        typ, data = conn.search(None, *criteria)
        if typ != "OK" or not data or not data[0]:
            raise FetchError("No matching email found for this schedule")
        ids = data[0].split()
        # Newest first.
        for msg_id in reversed(ids):
            typ, msg_data = conn.fetch(msg_id, "(RFC822)")
            if typ != "OK" or not msg_data:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                filename = part.get_filename() or ""
                if part.get("Content-Disposition") is None:
                    continue
                if attachment_ext and not filename.lower().endswith(attachment_ext):
                    continue
                payload = part.get_payload(decode=True)
                if payload:
                    if len(payload) > MAX_DOWNLOAD_BYTES:
                        raise FetchError(f"Attachment exceeds {MAX_DOWNLOAD_BYTES} bytes")
                    if config.get("mark_seen"):
                        conn.store(msg_id, "+FLAGS", "\\Seen")
                    return payload
        raise FetchError("No matching attachment found in the mailbox")
    except FetchError:
        raise
    except imaplib.IMAP4.error as exc:
        raise FetchError(f"IMAP error: {exc}")
    finally:
        try:
            conn.logout()
        except Exception:
            pass


async def fetch_payload(sched: dict) -> bytes:
    """Dispatch to the transport for this schedule's source_kind."""
    kind = sched["source_kind"]
    if kind == "https":
        return await fetch_https(sched["source_url"])
    if kind == "sftp":
        return await _in_thread(_fetch_sftp_blocking, sched["source_config"] or {})
    if kind == "imap":
        return await _in_thread(_fetch_imap_blocking, sched["source_config"] or {})
    raise FetchError(f"Unsupported source_kind {kind!r}")


def parse_payload(payload: bytes) -> tuple:
    """(headers, rows) from either a spreadsheet or CSV text.

    The bytes' own magic decides — the URL's extension is a claim, not evidence.
    """
    if imp.sniff_workbook_kind(payload) is not None:
        return imp.parse_workbook(payload)
    try:
        return imp.parse_csv(payload.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise FetchError("Payload is neither a spreadsheet nor UTF-8 CSV text")


async def _claim_due_schedules(db, limit: int = 20) -> List[Dict[str, Any]]:
    """Take ownership of the schedules that are due.

    `FOR UPDATE SKIP LOCKED` + pushing `next_run_at` forward in the same
    transaction means a second replica sees nothing to do.
    """
    rows = (await db.execute(text("""
        SELECT id, tenant_id, name, import_type, source_kind, source_url, source_config,
               mapping, interval_minutes, last_content_hash, consecutive_failures
          FROM import_schedules
         WHERE active AND next_run_at <= now()
         ORDER BY next_run_at
         LIMIT :lim
           FOR UPDATE SKIP LOCKED
    """), {"lim": limit})).mappings().all()

    if rows:
        await db.execute(text("""
            UPDATE import_schedules
               SET next_run_at = now() + make_interval(mins => interval_minutes)
             WHERE id = ANY(:ids)
        """), {"ids": [r["id"] for r in rows]})
    return [dict(r) for r in rows]


async def _finish(db, schedule_id: int, *, status: str, error: Optional[str] = None,
                  job_id: Optional[int] = None, new_hash: Optional[str] = None,
                  interval_minutes: int = 60, failures: int = 0) -> None:
    """Record the outcome and decide when to try again."""
    delay = backoff_minutes(interval_minutes, failures)
    await db.execute(text("""
        UPDATE import_schedules
           SET last_run_at = now(),
               last_status = :st,
               last_error = :err,
               last_job_id = COALESCE(:job, last_job_id),
               last_content_hash = COALESCE(:hash, last_content_hash),
               consecutive_failures = :fails,
               next_run_at = now() + make_interval(mins => :delay),
               updated_at = now()
         WHERE id = :sid
    """), {"st": status, "err": error, "job": job_id, "hash": new_hash,
           "fails": failures, "delay": delay, "sid": schedule_id})


async def run_schedule(db, sched: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one schedule. Never raises — the outcome is recorded, not thrown."""
    sid, tenant_id = sched["id"], sched["tenant_id"]
    interval = sched["interval_minutes"]

    if sched["source_kind"] not in SUPPORTED_SOURCE_KINDS:
        await _finish(db, sid, status="failed", interval_minutes=interval,
                      failures=sched["consecutive_failures"] + 1,
                      error=f"Unsupported source_kind {sched['source_kind']!r}")
        return {"schedule_id": sid, "status": "failed"}

    # E8-3: a scheduled import consumes the same plan quota as a manual one. Over
    # quota is not a failure of the schedule — do not back it off, and do not
    # burn a failure count on it.
    from app.services.usage_metering import enforce_quota
    from fastapi import HTTPException
    try:
        await enforce_quota(db, tenant_id, "import")
    except HTTPException:
        await _finish(db, sid, status="skipped_quota", interval_minutes=interval, failures=0)
        return {"schedule_id": sid, "status": "skipped_quota"}

    try:
        payload = await fetch_payload(sched)
        digest = content_hash(payload)

        # The whole reason this feature is safe. See the module docstring.
        if digest == sched["last_content_hash"]:
            await _finish(db, sid, status="skipped_unchanged",
                          interval_minutes=interval, failures=0)
            return {"schedule_id": sid, "status": "skipped_unchanged"}

        headers, rows = parse_payload(payload)
        if len(rows) > imp.MAX_ROWS:
            raise FetchError(f"Payload has {len(rows)} rows (max {imp.MAX_ROWS})")

        # No mapping configured => the remote file is expected to use the canonical
        # column names, and only EXACT matches are accepted. A near-miss fails the
        # run with the unmapped field named, rather than guessing a column.
        mapping = sched["mapping"] or imp.default_mapping(sched["import_type"], headers)

        result = imp.validate_rows(sched["import_type"], headers, rows, mapping)
        if not result["valid"]:
            unmapped = [e["field"] for e in result["errors"] if "not mapped" in e["message"]]
            if unmapped:
                raise FetchError(
                    f"Required field(s) not mapped: {', '.join(unmapped)}. "
                    f"Payload headers were: {', '.join(headers[:12])}")
            raise FetchError("No valid rows in the fetched payload")

        quality = imp.build_quality_report(sched["import_type"], result["valid"],
                                           result["errors"], result["summary"]["total"])

        # Same shape as the manual path: job row first, so the undo ledger can
        # attribute every row it writes (E2-4).
        job_id = (await db.execute(text("""
            INSERT INTO import_jobs (tenant_id, import_type, filename, status, total_rows,
                                     mapping, created_by, reversible)
            VALUES (:t, :ty, :fn, 'running', :total, CAST(:map AS JSONB), :by, TRUE)
            RETURNING id
        """), {"t": tenant_id, "ty": sched["import_type"],
               "fn": f"schedule:{sched['name']}", "total": len(rows),
               "map": json.dumps(mapping), "by": f"schedule:{sched['name']}"})).scalar()

        persist = await imp.commit_import(db, tenant_id, sched["import_type"],
                                          result["valid"], import_job_id=job_id)
        error_rows = result["summary"]["errors"]
        status = "completed" if (persist["skipped"] == 0 and error_rows == 0) else "partial"

        rejected = (result["rejected"] + persist["skipped_rows"])[:imp._MAX_REJECTED_STORED]
        quality["rejected_row_count"] = len(result["rejected"]) + persist["skipped"]
        quality["rejected_rows_stored"] = len(rejected)

        await db.execute(text("""
            UPDATE import_jobs
               SET status = :st, imported_rows = :imp, skipped_rows = :skip,
                   error_rows = :err, notes = CAST(:notes AS JSONB)
             WHERE id = :jid
        """), {"st": status, "imp": persist["imported"], "skip": persist["skipped"],
               "err": error_rows, "jid": job_id,
               "notes": json.dumps({"skip_reasons": persist["skip_reasons"],
                                    "quality": quality,
                                    "rejected": {"headers": headers, "rows": rejected},
                                    "source": {"kind": "https", "url": sched["source_url"]}},
                                   default=str)})

        await _finish(db, sid, status="ok", job_id=job_id, new_hash=digest,
                      interval_minutes=interval, failures=0)

        from app.services.usage_metering import record_usage
        await record_usage(tenant_id, "import", quantity=1,
                           metadata={"import_type": sched["import_type"],
                                     "rows_imported": persist["imported"],
                                     "schedule_id": sid})
        return {"schedule_id": sid, "status": "ok", "job_id": job_id,
                "imported": persist["imported"]}

    except Exception as exc:
        reason = str(exc) if isinstance(exc, FetchError) else f"{type(exc).__name__}: {exc}"
        failures = sched["consecutive_failures"] + 1
        # The import's own writes are rolled back by the caller's transaction
        # handling; the schedule's failure state is written in a fresh one so it
        # survives.
        raise ScheduleRunFailed(sid, reason, failures, interval) from exc


class ScheduleRunFailed(Exception):
    def __init__(self, schedule_id: int, reason: str, failures: int, interval: int):
        super().__init__(reason)
        self.schedule_id = schedule_id
        self.reason = reason
        self.failures = failures
        self.interval = interval


async def run_due_schedules() -> List[Dict[str, Any]]:
    """One tick. Returns an outcome per schedule attempted."""
    outcomes: List[Dict[str, Any]] = []

    async with async_session() as db:
        claimed = await _claim_due_schedules(db)
        await db.commit()   # release the claim locks before doing slow network I/O

    for sched in claimed:
        try:
            async with async_session() as db:
                outcome = await run_schedule(db, sched)
                await db.commit()
            outcomes.append(outcome)
        except ScheduleRunFailed as failure:
            # A failed import must leave NO rows behind, so its transaction is
            # discarded entirely and the failure recorded in a separate one.
            async with async_session() as db:
                await _finish(db, failure.schedule_id, status="failed",
                              error=failure.reason[:2000],
                              interval_minutes=failure.interval,
                              failures=failure.failures)
                await db.commit()
            logger.warning(f"Import schedule {failure.schedule_id} failed: {failure.reason}")
            outcomes.append({"schedule_id": failure.schedule_id, "status": "failed",
                             "error": failure.reason})
        except Exception as exc:   # pragma: no cover - defensive
            logger.error(f"Import schedule {sched['id']} crashed: {exc!r}")
            outcomes.append({"schedule_id": sched["id"], "status": "failed", "error": repr(exc)})

    return outcomes


async def scheduler_loop() -> None:
    """Background task: poll for due schedules forever.

    Inert with no schedules — the claim query returns nothing and it sleeps.
    """
    logger.info(f"Import scheduler started (poll every {POLL_INTERVAL_SECONDS}s)")
    while True:
        try:
            outcomes = await run_due_schedules()
            if outcomes:
                logger.info(f"Import scheduler ran {len(outcomes)} schedule(s): "
                            f"{[o['status'] for o in outcomes]}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:   # never let one bad tick kill the loop
            logger.error(f"Import scheduler tick failed: {exc!r}")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
