"""
SCIM 2.0 provisioning service (E5-1c).

Pragmatic, pilot-ready SCIM foundation for enterprise IdPs (Azure AD / Okta /
WorkOS): per-tenant bearer-token auth (hashed at rest), user lifecycle
(create/read/list/update/patch/deactivate), and minimal group support.

Security model (see docs/security/SCIM.md):
  * SCIM is OFF by default (settings.scim_enabled).
  * Tokens are stored HASHED (sha256) with a display prefix; the raw token is
    shown ONCE at creation/rotation and never logged or returned again.
  * Token verification is tenant-scoped and constant-time (hmac.compare_digest).
  * SCIM-provisioned users default to `analyst` and can NEVER be
    admin/owner/super_admin (role from the SCIM body is ignored; group role
    mapping is off by default and clamped).
  * Deprovisioning DEACTIVATES (status=inactive) — never hard-deletes — and can
    revoke active sessions; the last active super_admin cannot be deactivated.
  * Every query is tenant-scoped; cross-tenant access fails safely.

Security-critical decisions are pure functions (unit-tested without DB/network);
async functions orchestrate the DB.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings, logger
from app.services.sso import clamp_jit_role  # reuse the "never admin" role clamp

SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCIM_LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
SCIM_PATCHOP_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
SCIM_SPC_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"

TOKEN_PREFIX = "scim_"


class SCIMError(Exception):
    """SCIM failure carrying an HTTP status + SCIM error body."""

    def __init__(self, status: int, detail: str, scim_type: Optional[str] = None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.scim_type = scim_type

    def body(self) -> Dict[str, Any]:
        return scim_error(self.status, self.detail, self.scim_type)


# ===========================================================================
# Pure helpers (no DB / no network)
# ===========================================================================
def generate_scim_token() -> Tuple[str, str]:
    """Return (raw_token, prefix). Raw shown ONCE; prefix stored for display."""
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return raw, raw[:12]


def hash_scim_token(raw: str) -> str:
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()


def verify_scim_token(raw: str, stored_hash: str) -> bool:
    """Constant-time comparison of a raw token against a stored hash."""
    return hmac.compare_digest(hash_scim_token(raw or ""), stored_hash or "")


def parse_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def status_to_active(status: Optional[str]) -> bool:
    return (status or "").lower() == "active"


def active_to_status(active: bool) -> str:
    return "active" if active else "inactive"


_FILTER_RE = re.compile(r'^\s*userName\s+eq\s+"([^"]+)"\s*$', re.IGNORECASE)


def parse_username_filter(filter_str: Optional[str]) -> Optional[str]:
    """Support the one filter IdPs actually use: userName eq "email"."""
    if not filter_str:
        return None
    m = _FILTER_RE.match(filter_str)
    return m.group(1).lower() if m else None


def scim_error(status: int, detail: str, scim_type: Optional[str] = None) -> Dict[str, Any]:
    out = {"schemas": [SCIM_ERROR_SCHEMA], "status": str(status), "detail": detail}
    if scim_type:
        out["scimType"] = scim_type
    return out


def scim_user_resource(user: Dict[str, Any], external: Optional[Dict[str, Any]],
                       base_url: str) -> Dict[str, Any]:
    """Shape a local user (+ SCIM link) as a SCIM User. Exposes SCIM fields only
    — never password_hash, permissions, or internal columns."""
    uid = str(user["id"])
    email = user["email"]
    res = {
        "schemas": [SCIM_USER_SCHEMA],
        "id": uid,
        "userName": (external or {}).get("scim_user_name") or email,
        "active": status_to_active(user.get("status")),
        "name": {
            "givenName": user.get("first_name"),
            "familyName": user.get("last_name"),
            "formatted": " ".join(x for x in [user.get("first_name"), user.get("last_name")] if x),
        },
        "displayName": " ".join(x for x in [user.get("first_name"), user.get("last_name")] if x) or email,
        "emails": [{"value": email, "primary": True, "type": "work"}],
        "meta": {
            "resourceType": "User",
            "location": f"{base_url}/Users/{uid}",
        },
    }
    if external and external.get("external_id"):
        res["externalId"] = external["external_id"]
    return res


def scim_group_resource(group: Dict[str, Any], members: List[Dict[str, Any]], base_url: str) -> Dict[str, Any]:
    gid = str(group["id"])
    return {
        "schemas": [SCIM_GROUP_SCHEMA],
        "id": gid,
        "displayName": group["display_name"],
        "externalId": group.get("external_id"),
        "members": [{"value": str(m["user_id"])} for m in members],
        "meta": {"resourceType": "Group", "location": f"{base_url}/Groups/{gid}"},
    }


def scim_list_response(resources: List[Dict[str, Any]], total: int,
                       start_index: int, items_per_page: int) -> Dict[str, Any]:
    return {
        "schemas": [SCIM_LIST_SCHEMA],
        "totalResults": total,
        "startIndex": start_index,
        "itemsPerPage": items_per_page,
        "Resources": resources,
    }


def service_provider_config() -> Dict[str, Any]:
    return {
        "schemas": [SCIM_SPC_SCHEMA],
        "documentationUri": "https://retail-iq/docs/security/SCIM.md",
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": get_settings().scim_max_page_size},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [{
            "type": "oauthbearertoken", "name": "OAuth Bearer Token",
            "description": "Tenant-scoped SCIM bearer token (hashed at rest).",
        }],
        "meta": {"resourceType": "ServiceProviderConfig"},
    }


def user_schema() -> Dict[str, Any]:
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Schema"],
        "id": SCIM_USER_SCHEMA,
        "name": "User",
        "description": "SCIM core User (subset: userName, name, emails, active, externalId)",
        "attributes": [
            {"name": "userName", "type": "string", "required": True, "uniqueness": "server"},
            {"name": "active", "type": "boolean", "required": False},
            {"name": "name", "type": "complex", "required": False},
            {"name": "emails", "type": "complex", "multiValued": True, "required": False},
            {"name": "externalId", "type": "string", "required": False},
        ],
        "meta": {"resourceType": "Schema"},
    }


def resource_types(base_url: str) -> List[Dict[str, Any]]:
    return [{
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
        "id": "User", "name": "User", "endpoint": "/Users",
        "schema": SCIM_USER_SCHEMA,
        "meta": {"resourceType": "ResourceType", "location": f"{base_url}/ResourceTypes/User"},
    }, {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
        "id": "Group", "name": "Group", "endpoint": "/Groups",
        "schema": SCIM_GROUP_SCHEMA,
        "meta": {"resourceType": "ResourceType", "location": f"{base_url}/ResourceTypes/Group"},
    }]


def extract_user_fields(scim_body: Dict[str, Any]) -> Dict[str, Any]:
    """Map a SCIM User body to safe local fields. Role is NEVER taken from SCIM."""
    user_name = (scim_body.get("userName") or "").strip().lower()
    name = scim_body.get("name") or {}
    emails = scim_body.get("emails") or []
    primary_email = None
    for e in emails:
        if isinstance(e, dict) and e.get("primary"):
            primary_email = e.get("value")
            break
    if not primary_email and emails and isinstance(emails[0], dict):
        primary_email = emails[0].get("value")
    email = (primary_email or user_name or "").strip().lower()
    return {
        "user_name": user_name,
        "email": email,
        "given_name": (name.get("givenName") or (scim_body.get("displayName") or email).split(" ")[0] or "SCIM")[:100],
        "family_name": (name.get("familyName") or "User")[:100],
        "external_id": scim_body.get("externalId"),
        "active": bool(scim_body.get("active", True)),
    }


def apply_patch_ops(current: Dict[str, Any], patch_body: Dict[str, Any]) -> Dict[str, Any]:
    """Apply a SCIM PatchOp to a small mutable view {active, given_name, family_name}.
    Supports the operations IdPs actually send (replace active / name)."""
    ops = patch_body.get("Operations") or []
    out = dict(current)
    for op in ops:
        if not isinstance(op, dict):
            continue
        operation = (op.get("op") or "").lower()
        if operation not in ("replace", "add"):
            continue
        path = (op.get("path") or "").lower()
        value = op.get("value")
        if path == "active":
            out["active"] = _coerce_bool(value)
        elif path == "" and isinstance(value, dict):
            if "active" in value:
                out["active"] = _coerce_bool(value["active"])
            nm = value.get("name") or {}
            if nm.get("givenName"):
                out["given_name"] = str(nm["givenName"])[:100]
            if nm.get("familyName"):
                out["family_name"] = str(nm["familyName"])[:100]
        elif path == "name.givenname":
            out["given_name"] = str(value)[:100]
        elif path == "name.familyname":
            out["family_name"] = str(value)[:100]
    return out


def _coerce_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes")


# ===========================================================================
# Async DB orchestration
# ===========================================================================
def _require_enabled() -> None:
    if not get_settings().scim_enabled:
        raise SCIMError(401, "SCIM is not enabled", "invalidValue")


async def resolve_tenant_id(session: AsyncSession, tenant_slug: str) -> Optional[int]:
    row = (await session.execute(text("SELECT id FROM tenants WHERE slug = :slug"),
                                 {"slug": tenant_slug})).mappings().first()
    return row["id"] if row else None


async def authenticate_scim(session: AsyncSession, tenant_slug: str,
                            authorization: Optional[str]) -> Tuple[int, Dict[str, Any]]:
    """Authenticate a SCIM request for a tenant. Returns (tenant_id, token_row).
    Raises SCIMError(401) for disabled/missing/invalid/revoked/expired/cross-tenant
    — never revealing whether the tenant exists."""
    _require_enabled()
    raw = parse_bearer(authorization)
    if not raw:
        raise SCIMError(401, "Missing or malformed bearer token")

    tenant_id = await resolve_tenant_id(session, tenant_slug)
    token_hash = hash_scim_token(raw)
    # Candidate tokens: only this tenant's active tokens. If the tenant doesn't
    # exist we still run a comparison to avoid a tenant-existence timing signal.
    rows = []
    if tenant_id is not None:
        rows = (await session.execute(text("""
            SELECT * FROM tenant_scim_tokens
            WHERE tenant_id = :tid AND revoked_at IS NULL
              AND (expires_at IS NULL OR expires_at > now())
        """), {"tid": tenant_id})).mappings().all()

    match = None
    for r in rows:
        if verify_scim_token(raw, r["token_hash"]):
            match = r
            break
    if match is None:
        # constant-ish dummy compare so the no-match path does work too
        hmac.compare_digest(token_hash, token_hash)
        await _audit(session, "scim_token_auth_failed", tenant_id=tenant_id,
                     detail=f"SCIM auth failed for slug='{tenant_slug}'", severity="medium")
        raise SCIMError(401, "Invalid SCIM token")

    await session.execute(text(
        "UPDATE tenant_scim_tokens SET last_used_at = now() WHERE id = :id"), {"id": match["id"]})
    await session.commit()
    return tenant_id, dict(match)


async def _audit(session, event_type, *, tenant_id=None, user_id=None, detail=None,
                 severity="low", category="audit"):
    if not get_settings().scim_audit_enabled:
        return
    try:
        from app.services.security_events import record_event
        await record_event(event_type, severity=severity, category=category,
                           tenant_id=tenant_id, actor_user_id=user_id, detail=detail)
    except Exception:
        logger.debug("scim audit event failed (non-fatal)")


# --- Users -----------------------------------------------------------------
async def _load_user(session, tenant_id, user_id) -> Optional[Dict[str, Any]]:
    return (await session.execute(text("""
        SELECT id, email, first_name, last_name, role, status FROM users
        WHERE id = :id AND tenant_id = :tid
    """), {"id": user_id, "tid": tenant_id})).mappings().first()


async def _load_external(session, tenant_id, user_id) -> Optional[Dict[str, Any]]:
    r = (await session.execute(text("""
        SELECT * FROM scim_external_users WHERE tenant_id = :tid AND user_id = :uid
    """), {"tid": tenant_id, "uid": user_id})).mappings().first()
    return dict(r) if r else None


async def list_users(session, tenant_id, username_filter, start_index, count) -> Tuple[List[Dict], int]:
    params = {"tid": tenant_id}
    where = "eu.tenant_id = :tid"
    if username_filter:
        where += " AND lower(eu.scim_user_name) = :un"
        params["un"] = username_filter
    total = (await session.execute(text(
        f"SELECT COUNT(*) AS n FROM scim_external_users eu WHERE {where}"), params)).mappings().first()["n"]
    params["off"] = max(0, start_index - 1)
    params["lim"] = count
    rows = (await session.execute(text(f"""
        SELECT eu.*, u.email, u.first_name, u.last_name, u.role, u.status, u.id AS uid
        FROM scim_external_users eu JOIN users u ON u.id = eu.user_id
        WHERE {where} ORDER BY eu.id OFFSET :off LIMIT :lim
    """), params)).mappings().all()
    return [dict(r) for r in rows], int(total)


async def get_user_resource(session, tenant_id, user_id, base_url) -> Dict[str, Any]:
    user = await _load_user(session, tenant_id, user_id)
    if not user:
        raise SCIMError(404, "User not found", "notFound")
    external = await _load_external(session, tenant_id, user_id)
    return scim_user_resource(dict(user), external, base_url)


async def create_user(session, tenant_id, scim_body, base_url) -> Tuple[Dict[str, Any], int]:
    """Create (or link) a SCIM user. Always analyst; never admin. Returns (resource, http_status)."""
    f = extract_user_fields(scim_body)
    if not f["email"]:
        raise SCIMError(400, "userName/email is required", "invalidValue")

    # Duplicate SCIM userName in this tenant -> 409.
    existing_scim = (await session.execute(text(
        "SELECT user_id FROM scim_external_users WHERE tenant_id = :tid AND lower(scim_user_name) = :un"
    ), {"tid": tenant_id, "un": f["user_name"] or f["email"]})).mappings().first()
    if existing_scim:
        raise SCIMError(409, "User already exists", "uniqueness")

    # Existing LOCAL user with this email in the SAME tenant -> link it (idempotent).
    local = (await session.execute(text(
        "SELECT id FROM users WHERE tenant_id = :tid AND lower(email) = :em"
    ), {"tid": tenant_id, "em": f["email"]})).mappings().first()

    from app.services.auth_service import get_password_hash
    role = clamp_jit_role(get_settings().scim_default_role)  # analyst; never admin
    if local:
        user_id = local["id"]
    else:
        unusable_pw = get_password_hash("scim-no-password-" + secrets.token_urlsafe(24))
        status = active_to_status(f["active"])
        new = (await session.execute(text("""
            INSERT INTO users (email, password_hash, first_name, last_name, role, status,
                               tenant_id, email_verified)
            VALUES (:em, :pw, :fn, :ln, CAST(:role AS user_role), CAST(:status AS user_status), :tid, TRUE)
            RETURNING id
        """), {"em": f["email"], "pw": unusable_pw, "fn": f["given_name"], "ln": f["family_name"],
               "role": role, "status": status, "tid": tenant_id})).mappings().first()
        user_id = new["id"]

    import json
    await session.execute(text("""
        INSERT INTO scim_external_users (tenant_id, user_id, external_id, scim_user_name, raw_profile, last_synced_at)
        VALUES (:tid, :uid, :ext, :un, CAST(:profile AS jsonb), now())
        ON CONFLICT (tenant_id, scim_user_name) DO UPDATE SET last_synced_at = now(), updated_at = now()
    """), {"tid": tenant_id, "uid": user_id, "ext": f["external_id"],
           "un": f["user_name"] or f["email"],
           "profile": json.dumps({k: scim_body.get(k) for k in ("userName", "externalId", "active")})})
    await session.commit()
    await _audit(session, "scim_user_created", tenant_id=tenant_id, user_id=user_id,
                detail=f"SCIM provisioned '{role}' user {f['email']}")
    return await get_user_resource(session, tenant_id, user_id, base_url), 201


async def replace_user(session, tenant_id, user_id, scim_body, base_url) -> Dict[str, Any]:
    """PUT: update safe fields (name, active). Role/tenant are NEVER changed via SCIM."""
    user = await _load_user(session, tenant_id, user_id)
    if not user:
        raise SCIMError(404, "User not found", "notFound")
    f = extract_user_fields(scim_body)
    if not f["active"]:
        await _deactivate(session, tenant_id, user_id, user)
    else:
        await _set_status(session, tenant_id, user_id, "active")
    await session.execute(text("""
        UPDATE users SET first_name = :fn, last_name = :ln, updated_at = now()
        WHERE id = :id AND tenant_id = :tid
    """), {"fn": f["given_name"], "ln": f["family_name"], "id": user_id, "tid": tenant_id})
    await session.commit()
    await _audit(session, "scim_user_updated", tenant_id=tenant_id, user_id=user_id,
                detail=f"SCIM PUT update for user {user_id}")
    return await get_user_resource(session, tenant_id, user_id, base_url)


async def patch_user(session, tenant_id, user_id, patch_body, base_url) -> Dict[str, Any]:
    user = await _load_user(session, tenant_id, user_id)
    if not user:
        raise SCIMError(404, "User not found", "notFound")
    view = apply_patch_ops({
        "active": status_to_active(user["status"]),
        "given_name": user["first_name"], "family_name": user["last_name"],
    }, patch_body)
    if not view["active"]:
        await _deactivate(session, tenant_id, user_id, user)
    else:
        if not get_settings().scim_allow_reactivation and user["status"] != "active":
            raise SCIMError(400, "Reactivation is disabled", "invalidValue")
        await _set_status(session, tenant_id, user_id, "active")
        await _audit(session, "scim_user_reactivated", tenant_id=tenant_id, user_id=user_id,
                    detail=f"SCIM reactivated user {user_id}")
    await session.execute(text("""
        UPDATE users SET first_name = :fn, last_name = :ln, updated_at = now()
        WHERE id = :id AND tenant_id = :tid
    """), {"fn": view["given_name"], "ln": view["family_name"], "id": user_id, "tid": tenant_id})
    await session.commit()
    await _audit(session, "scim_user_updated", tenant_id=tenant_id, user_id=user_id,
                detail=f"SCIM PATCH update for user {user_id}")
    return await get_user_resource(session, tenant_id, user_id, base_url)


async def delete_user(session, tenant_id, user_id) -> None:
    """SCIM DELETE = DEACTIVATE (never hard delete)."""
    user = await _load_user(session, tenant_id, user_id)
    if not user:
        raise SCIMError(404, "User not found", "notFound")
    await _deactivate(session, tenant_id, user_id, user)
    await session.commit()


async def _set_status(session, tenant_id, user_id, status) -> None:
    await session.execute(text(
        "UPDATE users SET status = CAST(:st AS user_status), updated_at = now() "
        "WHERE id = :id AND tenant_id = :tid"), {"st": status, "id": user_id, "tid": tenant_id})


async def _deactivate(session, tenant_id, user_id, user) -> None:
    # Guard: never deactivate the last active super_admin in the tenant.
    if (user.get("role") or "").lower() == "super_admin":
        n = (await session.execute(text(
            "SELECT COUNT(*) AS n FROM users WHERE tenant_id = :tid AND role = 'super_admin' AND status = 'active'"
        ), {"tid": tenant_id})).mappings().first()["n"]
        if int(n) <= 1:
            raise SCIMError(400, "Cannot deactivate the last active administrator", "mutability")
    await _set_status(session, tenant_id, user_id, "inactive")
    if get_settings().scim_deactivate_revokes_tokens:
        try:
            from app.services.auth_service import revoke_user_sessions
            await revoke_user_sessions(user_id)
        except Exception:
            logger.debug("scim deactivate: session revoke unavailable (non-fatal)")
    await _audit(session, "scim_user_deactivated", tenant_id=tenant_id, user_id=user_id,
                detail=f"SCIM deactivated user {user_id}")


# --- SCIM admin tokens -----------------------------------------------------
async def create_scim_token(session, tenant_id, name, created_by, expires_days=None,
                            scopes="scim:read scim:write", rotated_from=None) -> Dict[str, Any]:
    raw, prefix = generate_scim_token()
    ttl = expires_days if expires_days is not None else get_settings().scim_token_ttl_days
    expires = (datetime.now(timezone.utc) + timedelta(days=ttl)) if ttl and ttl > 0 else None
    row = (await session.execute(text("""
        INSERT INTO tenant_scim_tokens (tenant_id, name, token_hash, token_prefix, scopes,
                                        created_by_user_id, rotated_from_token_id, expires_at)
        VALUES (:tid, :name, :hash, :prefix, :scopes, :by, :rot, :exp)
        RETURNING id, name, token_prefix, scopes, created_at, expires_at
    """), {"tid": tenant_id, "name": name[:200], "hash": hash_scim_token(raw), "prefix": prefix,
           "scopes": scopes, "by": created_by, "rot": rotated_from, "exp": expires})).mappings().first()
    await session.commit()
    return {"row": dict(row), "raw_token": raw}  # raw returned ONCE


async def list_scim_tokens(session, tenant_id) -> List[Dict[str, Any]]:
    rows = (await session.execute(text("""
        SELECT id, name, token_prefix, scopes, created_by_user_id, last_used_at,
               expires_at, revoked_at, created_at
        FROM tenant_scim_tokens WHERE tenant_id = :tid ORDER BY id DESC
    """), {"tid": tenant_id})).mappings().all()
    return [dict(r) for r in rows]  # metadata only — never the hash or raw value


async def _get_token(session, tenant_id, token_id) -> Optional[Dict[str, Any]]:
    r = (await session.execute(text(
        "SELECT * FROM tenant_scim_tokens WHERE id = :id AND tenant_id = :tid"
    ), {"id": token_id, "tid": tenant_id})).mappings().first()
    return dict(r) if r else None


async def revoke_scim_token(session, tenant_id, token_id, revoked_by) -> Dict[str, Any]:
    tok = await _get_token(session, tenant_id, token_id)
    if not tok:
        raise SCIMError(404, "Token not found", "notFound")
    await session.execute(text("""
        UPDATE tenant_scim_tokens SET revoked_at = COALESCE(revoked_at, now()),
               revoked_by_user_id = :by, updated_at = now()
        WHERE id = :id AND tenant_id = :tid
    """), {"by": revoked_by, "id": token_id, "tid": tenant_id})
    await session.commit()
    return {"id": token_id, "revoked": True}


async def rotate_scim_token(session, tenant_id, token_id, rotated_by) -> Dict[str, Any]:
    tok = await _get_token(session, tenant_id, token_id)
    if not tok:
        raise SCIMError(404, "Token not found", "notFound")
    await revoke_scim_token(session, tenant_id, token_id, rotated_by)
    created = await create_scim_token(session, tenant_id, name=tok["name"] + " (rotated)",
                                      created_by=rotated_by, scopes=tok["scopes"], rotated_from=token_id)
    return created


# --- SCIM groups (minimal; role mapping OFF by default, never grants admin) --
def role_mapping_is_safe(requested_role: Optional[str]) -> bool:
    """A group->role mapping is safe only if it doesn't grant a privileged role.
    Admin mapping additionally requires the explicit env flag."""
    if not requested_role:
        return True
    clamped = clamp_jit_role(requested_role)
    if clamped != (requested_role or "").lower():
        # requested a privileged role -> only allowed if explicitly permitted
        return bool(get_settings().scim_allow_admin_role_mapping)
    return True


async def _group_members(session, tenant_id, group_id) -> List[Dict[str, Any]]:
    rows = (await session.execute(text(
        "SELECT user_id FROM scim_group_memberships WHERE tenant_id = :tid AND group_id = :gid ORDER BY user_id"
    ), {"tid": tenant_id, "gid": group_id})).mappings().all()
    return [dict(r) for r in rows]


async def list_groups(session, tenant_id, start_index, count, base_url) -> Dict[str, Any]:
    total = (await session.execute(text(
        "SELECT COUNT(*) AS n FROM scim_groups WHERE tenant_id = :tid"), {"tid": tenant_id})).mappings().first()["n"]
    rows = (await session.execute(text(
        "SELECT * FROM scim_groups WHERE tenant_id = :tid ORDER BY id OFFSET :off LIMIT :lim"
    ), {"tid": tenant_id, "off": max(0, start_index - 1), "lim": count})).mappings().all()
    resources = []
    for g in rows:
        resources.append(scim_group_resource(dict(g), await _group_members(session, tenant_id, g["id"]), base_url))
    return scim_list_response(resources, int(total), start_index, len(resources))


async def get_group_resource(session, tenant_id, group_id, base_url) -> Dict[str, Any]:
    g = (await session.execute(text(
        "SELECT * FROM scim_groups WHERE id = :gid AND tenant_id = :tid"
    ), {"gid": group_id, "tid": tenant_id})).mappings().first()
    if not g:
        raise SCIMError(404, "Group not found", "notFound")
    return scim_group_resource(dict(g), await _group_members(session, tenant_id, group_id), base_url)


async def create_group(session, tenant_id, scim_body, base_url) -> Tuple[Dict[str, Any], int]:
    name = (scim_body.get("displayName") or "").strip()
    if not name:
        raise SCIMError(400, "displayName is required", "invalidValue")
    dup = (await session.execute(text(
        "SELECT id FROM scim_groups WHERE tenant_id = :tid AND display_name = :n"
    ), {"tid": tenant_id, "n": name})).mappings().first()
    if dup:
        raise SCIMError(409, "Group already exists", "uniqueness")
    g = (await session.execute(text("""
        INSERT INTO scim_groups (tenant_id, display_name, external_id) VALUES (:tid, :n, :ext)
        RETURNING id, display_name, external_id
    """), {"tid": tenant_id, "n": name, "ext": scim_body.get("externalId")})).mappings().first()
    # members (if provided) — tenant-scoped only.
    await _apply_members(session, tenant_id, g["id"], scim_body.get("members") or [])
    await session.commit()
    await _audit(session, "scim_group_created", tenant_id=tenant_id, detail=f"SCIM group '{name}' created")
    return await get_group_resource(session, tenant_id, g["id"], base_url), 201


async def patch_group(session, tenant_id, group_id, patch_body, base_url) -> Dict[str, Any]:
    g = (await session.execute(text(
        "SELECT id FROM scim_groups WHERE id = :gid AND tenant_id = :tid"
    ), {"gid": group_id, "tid": tenant_id})).mappings().first()
    if not g:
        raise SCIMError(404, "Group not found", "notFound")
    for op in (patch_body.get("Operations") or []):
        if not isinstance(op, dict):
            continue
        operation = (op.get("op") or "").lower()
        path = (op.get("path") or "").lower()
        value = op.get("value")
        if path == "members" or (path == "" and isinstance(value, dict) and "members" in value):
            members = value if isinstance(value, list) else (value or {}).get("members", [])
            if operation in ("add", "replace"):
                if operation == "replace":
                    await session.execute(text(
                        "DELETE FROM scim_group_memberships WHERE tenant_id = :tid AND group_id = :gid"),
                        {"tid": tenant_id, "gid": group_id})
                await _apply_members(session, tenant_id, group_id, members)
            elif operation == "remove":
                for m in (members or []):
                    uid = _member_uid(m)
                    if uid is not None:
                        await session.execute(text(
                            "DELETE FROM scim_group_memberships WHERE tenant_id = :tid AND group_id = :gid AND user_id = :uid"),
                            {"tid": tenant_id, "gid": group_id, "uid": uid})
    await session.commit()
    await _audit(session, "scim_group_updated", tenant_id=tenant_id, detail=f"SCIM group {group_id} updated")
    return await get_group_resource(session, tenant_id, group_id, base_url)


async def delete_group(session, tenant_id, group_id) -> None:
    g = (await session.execute(text(
        "SELECT id FROM scim_groups WHERE id = :gid AND tenant_id = :tid"
    ), {"gid": group_id, "tid": tenant_id})).mappings().first()
    if not g:
        raise SCIMError(404, "Group not found", "notFound")
    await session.execute(text("DELETE FROM scim_groups WHERE id = :gid AND tenant_id = :tid"),
                          {"gid": group_id, "tid": tenant_id})
    await session.commit()
    await _audit(session, "scim_group_deleted", tenant_id=tenant_id, detail=f"SCIM group {group_id} deleted")


def _member_uid(m: Any) -> Optional[int]:
    val = m.get("value") if isinstance(m, dict) else m
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


async def _apply_members(session, tenant_id, group_id, members) -> None:
    """Add members — ONLY users that belong to this tenant (cross-tenant ignored)."""
    for m in (members or []):
        uid = _member_uid(m)
        if uid is None:
            continue
        belongs = (await session.execute(text(
            "SELECT 1 FROM users WHERE id = :uid AND tenant_id = :tid"), {"uid": uid, "tid": tenant_id})).first()
        if not belongs:
            await _audit(session, "scim_cross_tenant_access_blocked", tenant_id=tenant_id,
                        detail=f"SCIM group member {uid} not in tenant — ignored", severity="medium")
            continue
        await session.execute(text("""
            INSERT INTO scim_group_memberships (tenant_id, group_id, user_id) VALUES (:tid, :gid, :uid)
            ON CONFLICT (group_id, user_id) DO NOTHING
        """), {"tid": tenant_id, "gid": group_id, "uid": uid})
