"""Single-use, expiring auth tokens (password reset, email verify, invites).

Backed by the `auth_tokens` table (migration 036). The raw token is never stored —
only its SHA-256 hash. Single-use is enforced atomically at consume time so a
replayed token matches no row.
"""
import hashlib
from typing import Optional

from sqlalchemy import text

from app.services.database import async_session


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def issue_token(
    token_type: str,
    raw_token: str,
    *,
    ttl_minutes: int,
    user_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
    email: Optional[str] = None,
    role: Optional[str] = None,
    invited_by: Optional[int] = None,
) -> None:
    """Persist a single-use token record. `raw_token` is hashed before storage."""
    async with async_session() as s:
        await s.execute(
            text(
                """
                INSERT INTO auth_tokens
                    (token_hash, token_type, user_id, tenant_id, email, role, invited_by, expires_at)
                VALUES
                    (:h, :t, :uid, :tid, :em, :role, :inv,
                     now() + make_interval(mins => :ttl))
                ON CONFLICT (token_hash) DO NOTHING
                """
            ),
            {
                "h": hash_token(raw_token),
                "t": token_type,
                "uid": user_id,
                "tid": tenant_id,
                "em": email,
                "role": role,
                "inv": invited_by,
                "ttl": ttl_minutes,
            },
        )
        await s.commit()


async def consume_token(token_type: str, raw_token: str) -> Optional[dict]:
    """Atomically mark the token used and return its payload, or None if it is
    unknown / already used / expired / the wrong type. Single-use guaranteed."""
    async with async_session() as s:
        res = await s.execute(
            text(
                """
                UPDATE auth_tokens
                   SET used_at = now()
                 WHERE token_hash = :h
                   AND token_type = :t
                   AND used_at IS NULL
                   AND expires_at > now()
             RETURNING user_id, tenant_id, email, role, invited_by
                """
            ),
            {"h": hash_token(raw_token), "t": token_type},
        )
        row = res.fetchone()
        await s.commit()
    if not row:
        return None
    return {
        "user_id": row[0],
        "tenant_id": row[1],
        "email": row[2],
        "role": row[3],
        "invited_by": row[4],
    }
