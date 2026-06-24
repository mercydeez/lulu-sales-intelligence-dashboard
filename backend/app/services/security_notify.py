"""
Security alert dispatch — the "Google emailed me about a sign-in" behavior.

When a security event at/above SECURITY_ALERT_MIN_SEVERITY is recorded, this sends
an email (stdlib smtplib, run off the event loop) and/or posts to an incoming
webhook (Slack/Discord/Teams). Everything is env-gated and best-effort: with no
SMTP host / webhook configured it is a silent no-op, and a delivery failure never
affects the request that triggered it. No paid service or extra dependency —
configure SMTP_* with e.g. a Gmail app password to turn it on.
"""
from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Dict

from app.config import get_settings, logger

_SEV_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _should_alert(severity: str) -> bool:
    s = get_settings()
    threshold = _SEV_RANK.get((s.security_alert_min_severity or "high").lower(), 3)
    return _SEV_RANK.get((severity or "info").lower(), 0) >= threshold


def _send_email_sync(subject: str, body: str) -> None:
    """Blocking SMTP send (run via asyncio.to_thread). No-op if SMTP unconfigured."""
    s = get_settings()
    if not s.smtp_host or not s.security_alert_email_to:
        logger.info(f"🛡️📧 [security-alert email skipped — SMTP not configured] {subject}")
        return
    sender = s.security_alert_email_from or s.smtp_user or "security@retaildemo.app"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = s.security_alert_email_to
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as server:
        if s.smtp_use_tls:
            server.starttls()
        if s.smtp_user and s.smtp_password:
            server.login(s.smtp_user, s.smtp_password)
        server.send_message(msg)
    logger.info(f"🛡️📧 Security alert emailed to {s.security_alert_email_to}: {subject}")


def _send_to_sync(to: str, subject: str, body: str) -> None:
    """Send an email to a SPECIFIC recipient (e.g. password reset). No-op + log
    when SMTP isn't configured, so the flow works end-to-end without a mail server."""
    s = get_settings()
    if not s.smtp_host:
        logger.info(f"📧 [email skipped — SMTP not configured] to={to} :: {subject}\n{body}")
        return
    sender = s.security_alert_email_from or s.smtp_user or "no-reply@retaildemo.app"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as server:
        if s.smtp_use_tls:
            server.starttls()
        if s.smtp_user and s.smtp_password:
            server.login(s.smtp_user, s.smtp_password)
        server.send_message(msg)
    logger.info(f"📧 Email sent to {to}: {subject}")


async def send_email(to: str, subject: str, body: str) -> None:
    """Async wrapper — runs the blocking SMTP send off the event loop. Never raises."""
    try:
        await asyncio.to_thread(_send_to_sync, to, subject, body)
    except Exception as e:
        logger.warning(f"send_email failed for {to}: {e}")


async def _post_webhook(text: str) -> None:
    s = get_settings()
    if not s.security_alert_webhook_url:
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(s.security_alert_webhook_url, json={"text": text})
    except Exception as e:
        logger.warning(f"Security alert webhook failed: {e}")


async def dispatch(event: Dict) -> None:
    """Fire email + webhook for a qualifying security event. Never raises."""
    try:
        sev = event.get("severity", "info")
        if not _should_alert(sev):
            return
        et = event.get("event_type", "security_event")
        detail = event.get("detail") or et
        ip = event.get("ip_address") or "unknown"
        when = event.get("occurred_at", "")
        product = get_settings().product_name

        subject = f"[{product} Security] {sev.upper()}: {et}"
        body = (
            f"A {sev}-severity security event was detected on your {product} workspace.\n\n"
            f"Event:   {et}\n"
            f"Detail:  {detail}\n"
            f"Source IP: {ip}\n"
            f"When:    {when}\n\n"
            f"If this wasn't you or your team, review the Security page and rotate "
            f"affected credentials.\n"
        )
        text = f":shield: *{product} Security* — *{sev.upper()}* `{et}`\n{detail}\n_IP {ip} · {when}_"

        await asyncio.gather(
            asyncio.to_thread(_send_email_sync, subject, body),
            _post_webhook(text),
            return_exceptions=True,
        )
    except Exception as e:
        logger.debug(f"security_notify.dispatch skipped: {e}")
