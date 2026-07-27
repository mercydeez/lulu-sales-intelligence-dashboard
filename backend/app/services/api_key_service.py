"""
Per-tenant API-key service (B4/B5).

Mints and verifies the keys that authenticate the public REST API and the
embeddable AI assistant. A key looks like `lsk_<prefix>_<secret>`; only its
SHA-256 hash is persisted. SHA-256 (not bcrypt) is the right primitive here:
the secret is 256 bits of CSPRNG entropy, so there's nothing to brute-force,
and verification has to be fast enough to run on every public request.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

KEY_LABEL = "lsk"  # app secret key prefix


def hash_key(full_key: str) -> str:
    return hashlib.sha256(full_key.encode("utf-8")).hexdigest()


def generate_key() -> Dict[str, str]:
    """Mint a new key. Returns the plaintext (shown once), the display prefix,
    and the stored hash."""
    prefix = secrets.token_hex(4)            # 8 hex chars, non-secret
    secret = secrets.token_urlsafe(32)       # ~43 chars, the secret
    full_key = f"{KEY_LABEL}_{prefix}_{secret}"
    return {
        "full_key": full_key,
        "key_prefix": f"{KEY_LABEL}_{prefix}",
        "key_hash": hash_key(full_key),
    }


async def create_key(
    db: AsyncSession,
    tenant_id: int,
    name: str,
    scopes: Optional[List[str]] = None,
    created_by: Optional[int] = None,
    expires_in_days: Optional[int] = None,
) -> Dict:
    """Create a key for a tenant and return it including the one-time plaintext.

    expires_in_days: optional finite lifetime (1..3650). None => never expires,
    preserving the historical default."""
    minted = generate_key()
    expires_at = None
    if expires_in_days is not None:
        days = max(1, min(int(expires_in_days), 3650))
        expires_at = datetime.now(timezone.utc) + timedelta(days=days)
    row = (await db.execute(text("""
        INSERT INTO tenant_api_keys (tenant_id, name, key_prefix, key_hash, scopes, created_by, expires_at)
        VALUES (:tenant_id, :name, :prefix, :hash, :scopes, :created_by, :expires_at)
        RETURNING id, created_at
    """), {
        "tenant_id": tenant_id,
        "name": name,
        "prefix": minted["key_prefix"],
        "hash": minted["key_hash"],
        "scopes": scopes or ["read"],
        "created_by": created_by,
        "expires_at": expires_at,
    })).fetchone()
    await db.commit()
    return {
        "id": row.id,
        "name": name,
        "key_prefix": minted["key_prefix"],
        "api_key": minted["full_key"],   # shown ONCE — never retrievable again
        "scopes": scopes or ["read"],
        "expires_at": expires_at.isoformat() if expires_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def list_keys(db: AsyncSession, tenant_id: int) -> List[Dict]:
    rows = (await db.execute(text("""
        SELECT id, name, key_prefix, scopes, last_used_at, request_count,
               revoked_at, expires_at, created_at
        FROM tenant_api_keys
        WHERE tenant_id = :tenant_id
        ORDER BY created_at DESC
    """), {"tenant_id": tenant_id})).fetchall()
    now = datetime.now(timezone.utc)
    return [{
        "id": r.id,
        "name": r.name,
        "key_prefix": r.key_prefix,
        "scopes": list(r.scopes) if r.scopes else [],
        "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
        "request_count": int(r.request_count or 0),
        "revoked": r.revoked_at is not None,
        "expires_at": r.expires_at.isoformat() if r.expires_at else None,
        "expired": bool(r.expires_at is not None and r.expires_at <= now),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]


async def revoke_key(db: AsyncSession, tenant_id: int, key_id: int) -> bool:
    """Revoke a key (tenant-scoped so one tenant can't revoke another's)."""
    res = await db.execute(text("""
        UPDATE tenant_api_keys
        SET revoked_at = CURRENT_TIMESTAMP
        WHERE id = :id AND tenant_id = :tenant_id AND revoked_at IS NULL
    """), {"id": key_id, "tenant_id": tenant_id})
    await db.commit()
    return (res.rowcount or 0) > 0


async def tenant_for_key(db: AsyncSession, full_key: str) -> Optional[int]:
    """Resolve an API key to its (active) tenant id WITHOUT side effects.

    Used by services/database.resolve_request_tenant to bind the RLS tenant GUC
    before the request's DB session opens. Must run on the owner session: under
    RLS the request session is scoped to a tenant we don't know yet, so a
    cross-tenant key lookup would be filtered out.
    """
    if not full_key or not full_key.startswith(f"{KEY_LABEL}_"):
        return None
    row = (await db.execute(text("""
        SELECT k.tenant_id
        FROM tenant_api_keys k
        JOIN tenants t ON t.id = k.tenant_id
        WHERE k.key_hash = :hash AND k.revoked_at IS NULL AND t.status = 'active'
          AND (k.expires_at IS NULL OR k.expires_at > CURRENT_TIMESTAMP)
    """), {"hash": hash_key(full_key)})).fetchone()
    return row.tenant_id if row else None


async def authenticate(db: AsyncSession, full_key: str) -> Optional[Dict]:
    """Resolve a plaintext key to its (active) tenant + scopes, or None. Updates
    last_used_at / request_count as a side effect on success."""
    if not full_key or not full_key.startswith(f"{KEY_LABEL}_"):
        return None
    row = (await db.execute(text("""
        SELECT k.id, k.tenant_id, k.scopes, t.status AS tenant_status
        FROM tenant_api_keys k
        JOIN tenants t ON t.id = k.tenant_id
        WHERE k.key_hash = :hash AND k.revoked_at IS NULL
          AND (k.expires_at IS NULL OR k.expires_at > CURRENT_TIMESTAMP)
    """), {"hash": hash_key(full_key)})).fetchone()
    if not row or row.tenant_status != "active":
        return None
    await db.execute(text("""
        UPDATE tenant_api_keys
        SET last_used_at = :now, request_count = request_count + 1
        WHERE id = :id
    """), {"now": datetime.now(timezone.utc), "id": row.id})
    await db.commit()
    return {
        "key_id": row.id,
        "tenant_id": row.tenant_id,
        "scopes": list(row.scopes) if row.scopes else [],
    }
