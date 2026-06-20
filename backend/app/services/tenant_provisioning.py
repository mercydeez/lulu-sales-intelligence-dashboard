"""
Self-serve tenant provisioning (go-to-market onboarding).

Turns a signup into a working, isolated workspace: a new tenant + its owner
(super_admin) and — optionally — a sample dataset so the dashboard shows value
immediately instead of an empty trial. No billing is involved; new tenants start
on a `trial` plan. Pairs with the invite flow so the owner can add teammates.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from sqlalchemy import text

from app.services.database import async_session
from app.services.auth_service import get_password_hash, validate_password_strength
from app.config import logger

TRIAL_DAYS = 14
SAMPLE_ITEMS = [
    ("Basmati Rice 5kg", "Rice & Grains", 32.00),
    ("Olive Oil 1L", "Condiments", 28.50),
    ("Fresh Milk 2L", "Dairy", 9.75),
    ("Arabic Bread", "Bakery", 4.25),
    ("Mineral Water 12pk", "Beverages", 15.00),
    ("Chicken Breast 1kg", "Meat & Poultry", 24.00),
    ("Cheddar 500g", "Dairy", 19.50),
    ("Dates 1kg", "Snacks", 21.00),
]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug[:48] or "tenant"


async def _unique_slug(session, base: str) -> str:
    slug = base
    for _ in range(50):
        exists = (await session.execute(
            text("SELECT 1 FROM tenants WHERE slug = :s"), {"s": slug})).fetchone()
        if not exists:
            return slug
        slug = f"{base}-{secrets.token_hex(2)}"
    return f"{base}-{secrets.token_hex(4)}"


async def email_exists(email: str) -> bool:
    async with async_session() as session:
        row = (await session.execute(
            text("SELECT 1 FROM users WHERE lower(email) = lower(:e)"), {"e": email})).fetchone()
        return row is not None


async def seed_sample_data(session, tenant_id: int, days: int = 120) -> None:
    """Give a fresh tenant a realistic starter dataset (2 stores × 8 items ×
    `days` of weekly-seasonal sales) so forecasts/inventory work on day one."""
    s1 = (await session.execute(text(
        "INSERT INTO stores (name, location, tenant_id) VALUES (:n, :l, :t) RETURNING id"),
        {"n": "Main Store", "l": "HQ", "t": tenant_id})).scalar()
    s2 = (await session.execute(text(
        "INSERT INTO stores (name, location, tenant_id) VALUES (:n, :l, :t) RETURNING id"),
        {"n": "Branch Store", "l": "Downtown", "t": tenant_id})).scalar()

    for name, category, price in SAMPLE_ITEMS:
        await session.execute(text(
            "INSERT INTO items (name, category, unit_price_aed, tenant_id) "
            "VALUES (:n, :c, :p, :t)"),
            {"n": name, "c": category, "p": price, "t": tenant_id})

    # Deterministic weekly seasonality + weekend bump, generated in-DB.
    await session.execute(text("""
        INSERT INTO sales_historical (date, store_id, item_id, sales, tenant_id)
        SELECT d::date, st.id, it.id,
            GREATEST(0, ROUND(
                (15 + (it.id % 7) * 6)
                * (1 + 0.30 * sin(2 * pi() * EXTRACT(doy FROM d) / 7))
                + CASE WHEN EXTRACT(dow FROM d) IN (5, 6)
                       THEN (15 + (it.id % 7) * 6) * 0.4 ELSE 0 END
            ))::int,
            :tid
        FROM generate_series(CURRENT_DATE - make_interval(days => :days),
                             CURRENT_DATE - INTERVAL '1 day', INTERVAL '1 day') AS d
        CROSS JOIN stores st
        CROSS JOIN items it
        WHERE st.tenant_id = :tid AND it.tenant_id = :tid
    """), {"tid": tenant_id, "days": days})


async def create_tenant_with_owner(
    company: str,
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    seed_demo: bool = True,
) -> Tuple[Optional[int], Optional[str]]:
    """Provision a new tenant + owner. Returns (user_id, error)."""
    ok, msg = validate_password_strength(password)
    if not ok:
        return None, msg
    if await email_exists(email):
        return None, "An account with this email already exists"

    async with async_session() as session:
        try:
            slug = await _unique_slug(session, _slugify(company))
            trial_ends = datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS)
            tenant_id = (await session.execute(text("""
                INSERT INTO tenants (slug, name, plan, status, brand_name, trial_ends_at)
                VALUES (:slug, :name, 'trial', 'active', :name, :trial)
                RETURNING id
            """), {"slug": slug, "name": company or slug, "trial": trial_ends})).scalar()

            user_id = (await session.execute(text("""
                INSERT INTO users (email, password_hash, first_name, last_name,
                                   role, status, job_title, department, tenant_id)
                VALUES (:email, :pw, :first, :last, 'super_admin', 'active',
                        'Owner', 'Executive', :tid)
                RETURNING id
            """), {
                "email": email, "pw": get_password_hash(password),
                "first": first_name, "last": last_name, "tid": tenant_id,
            })).scalar()

            if seed_demo:
                await seed_sample_data(session, tenant_id)

            await session.commit()
            logger.info(f"Provisioned tenant {tenant_id} ({slug}) for {email}")
            return user_id, None
        except Exception as e:
            await session.rollback()
            logger.error(f"Tenant provisioning failed: {e}")
            return None, "Could not create account. Please try again."


async def invite_user(
    tenant_id: int,
    email: str,
    first_name: str,
    last_name: str,
    role: str = "analyst",
) -> Tuple[Optional[Dict], Optional[str]]:
    """Invite a teammate into a tenant. Creates an active user with a generated
    temporary password and `must_change_password`. Returns (invite, error).
    The temp password is returned once so the admin can share it (a production
    build would email a magic link instead)."""
    valid_roles = {"super_admin", "admin", "regional_manager", "store_manager", "analyst", "viewer"}
    if role not in valid_roles:
        return None, f"Invalid role. One of: {sorted(valid_roles)}"
    if await email_exists(email):
        return None, "A user with this email already exists"

    # A strong temp password that satisfies the strength policy.
    temp_password = f"Lulu-{secrets.token_urlsafe(10)}-9!"
    async with async_session() as session:
        try:
            user_id = (await session.execute(text("""
                INSERT INTO users (email, password_hash, first_name, last_name,
                                   role, status, tenant_id, must_change_password)
                VALUES (:email, :pw, :first, :last, :role, 'active', :tid, TRUE)
                RETURNING id
            """), {
                "email": email, "pw": get_password_hash(temp_password),
                "first": first_name, "last": last_name, "role": role, "tid": tenant_id,
            })).scalar()
            await session.commit()
            return {
                "user_id": user_id,
                "email": email,
                "role": role,
                "temporary_password": temp_password,
                "must_change_password": True,
            }, None
        except Exception as e:
            await session.rollback()
            logger.error(f"User invite failed: {e}")
            return None, "Could not invite user. Please try again."
