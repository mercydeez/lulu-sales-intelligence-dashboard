"""E2-1 — POS connector framework + a reference (`mock`) adapter, honestly gated.

The lifecycle is built end to end:

    tenant connects a POS vendor (OAuth)  ->  a nightly job pulls receipts  ->  they
    land at the BASKET grain (transactions / transaction_lines) idempotently.

Same posture as e-invoicing (einvoicing.py) and payments (payments.py):

1. A real vendor (square / foodics / omnivore / lightspeed) is REFUSED until it is in
   IMPLEMENTED_VENDORS *and* its OAuth credentials are configured. Recognising a vendor
   is not the same as being able to pull from it — the per-vendor OAuth exchange and
   receipt mapping are not built. `begin_oauth`/`sync_connection` refuse rather than
   fabricate a connection or fabricate sales.

2. OAuth CLIENT SECRETS are never stored in the DB. A connection stores the ENV-VAR
   NAME of the credential (`credential_env`); the secret is resolved in-process.

3. The connector NEVER writes sales_fact_view. Per ADR-010 the daily grain stays the
   source of truth for revenue; the basket grain is parallel. A real adapter also lands
   daily aggregates in external_sales -> sales_rollup_daily (migration 056) for revenue;
   `mock` demonstrates the basket grain only, so demo revenue is unperturbed.

The `mock` vendor exists to demo the FLOW. Its receipts are tagged is_synthetic=true,
confined to the demo tenant (E0-8), with MOCK- refs — so a demo pull can never be
mistaken for a real POS feed. It is DETERMINISTIC (no random): re-running a sync over
the same window ingests nothing new, because transactions' UNIQUE(tenant,source,ref)
makes ingestion idempotent.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings, logger
from app.services.database import async_session

MOCK_VENDOR = "mock"
# Recognised POS vendors (UAE-relevant: foodics, omnivore). Not integrated.
POS_VENDORS = {"square", "foodics", "omnivore", "lightspeed"}
ALL_VENDORS = {MOCK_VENDOR} | POS_VENDORS

# Vendors with an ACTUAL pull implementation. A vendor being recognised +
# credentialed does NOT mean we can pull from it — the OAuth exchange + receipt
# mapping is not wired. Only `mock` runs the flow. Adding a real vendor is:
# implement its oauth-exchange + receipt-fetch adapter, then add it here.
IMPLEMENTED_VENDORS = {MOCK_VENDOR}

# The source tag written into transactions.source, so a POS-ingested basket is
# distinguishable from any other writer and idempotency is scoped per vendor.
_SOURCE_PREFIX = "pos_"

# How many trailing days a sync pulls when a connection has no cursor yet.
_DEFAULT_BACKFILL_DAYS = 3


def _env(vendor: str, key: str) -> Optional[str]:
    """A vendor OAuth credential, by env-var name — never stored in the DB."""
    return os.getenv(f"{vendor.upper()}_{key}")


def is_vendor_available(vendor: str) -> bool:
    """Usable only if IMPLEMENTED and (for a real vendor) its OAuth app credentials
    are present. `mock` is always available."""
    if vendor == MOCK_VENDOR:
        return vendor in IMPLEMENTED_VENDORS
    if vendor in POS_VENDORS:
        has_creds = bool(_env(vendor, "CLIENT_ID") and _env(vendor, "CLIENT_SECRET"))
        return vendor in IMPLEMENTED_VENDORS and has_creds
    return False


def vendor_status() -> Dict[str, Dict[str, Any]]:
    """What an operator sees: which vendors are recognised, configured, usable."""
    out: Dict[str, Dict[str, Any]] = {}
    for v in sorted(ALL_VENDORS):
        implemented = v in IMPLEMENTED_VENDORS
        configured = v == MOCK_VENDOR or bool(_env(v, "CLIENT_ID") and _env(v, "CLIENT_SECRET"))
        out[v] = {
            "implemented": implemented,
            "configured": configured,
            "usable": is_vendor_available(v),
            "note": (
                "demo flow only; writes the demo-tenant basket grain, no real money"
                if v == MOCK_VENDOR
                else "recognised but not integrated — refused until the OAuth + receipt "
                     "adapter is built and certified" if not implemented
                else "configured" if configured
                else "set {V}_CLIENT_ID + {V}_CLIENT_SECRET".replace("{V}", v.upper())
            ),
        }
    return out


# ---------------------------------------------------------------------------
# OAuth connect (scaffold). `mock` connects directly; real vendors are refused.
# ---------------------------------------------------------------------------

def oauth_authorize_url(vendor: str, *, redirect_uri: str, state: str) -> str:
    """The vendor's hosted OAuth consent URL. Only `mock` is realised here; a real
    vendor's URL would be built from its documented authorize endpoint + client id.
    (Kept behind is_vendor_available at the call site, so this is not reached for an
    unintegrated vendor.)"""
    if vendor == MOCK_VENDOR:
        return (f"https://connect.mock.local/oauth/authorize?client=mock"
                f"&redirect_uri={redirect_uri}&state={state}&scope=orders:read")
    raise RuntimeError(f"{vendor} OAuth authorize URL is not integrated")


async def begin_oauth(db: AsyncSession, *, tenant_id: int, vendor: str, redirect_uri: str,
                      actor: str) -> Tuple[Optional[Dict], Optional[str]]:
    """Start a connection. For `mock`, connects immediately (demo). For a real vendor,
    refuses — the OAuth exchange is not built, and returning a live authorize URL we
    cannot complete would strand the tenant mid-flow. Returns (connection, None) or
    (None, error)."""
    if vendor not in ALL_VENDORS:
        return None, f"Unknown POS vendor {vendor!r}"
    if not is_vendor_available(vendor):
        return None, (
            f"POS vendor '{vendor}' is not available. "
            + ("It is recognised but not yet integrated (refused until its OAuth + "
               "receipt adapter is built)."
               if vendor in POS_VENDORS and vendor not in IMPLEMENTED_VENDORS
               else f"Set {vendor.upper()}_CLIENT_ID and {vendor.upper()}_CLIENT_SECRET.")
        )

    # `mock`: no real OAuth round-trip; bind to a demo account so the sync has a target.
    account_ref = f"MOCK-ACCT-{tenant_id}"
    row = (await db.execute(text("""
        INSERT INTO pos_connections (tenant_id, vendor, status, external_account_ref,
                                     scopes, connected_at, created_by)
        VALUES (:t, :v, 'connected', :acct, 'orders:read', now(), :by)
        ON CONFLICT (tenant_id, vendor) DO UPDATE
            SET status='connected', external_account_ref=EXCLUDED.external_account_ref,
                connected_at=now(), last_sync_error=NULL, updated_at=now()
        RETURNING id, status, external_account_ref
    """), {"t": tenant_id, "v": vendor, "acct": account_ref, "by": actor})).mappings().fetchone()
    return {"connection_id": row["id"], "vendor": vendor, "status": row["status"],
            "external_account_ref": row["external_account_ref"]}, None


async def get_connection(db: AsyncSession, tenant_id: int, connection_id: int) -> Optional[Dict]:
    row = (await db.execute(text("""
        SELECT id, vendor, status, external_account_ref, sync_cursor, connected_at,
               last_sync_at, last_sync_status, last_sync_error
          FROM pos_connections WHERE id = :id AND tenant_id = :t
    """), {"id": connection_id, "t": tenant_id})).mappings().fetchone()
    return dict(row) if row else None


async def list_connections(db: AsyncSession, tenant_id: int) -> List[Dict]:
    rows = (await db.execute(text("""
        SELECT id, vendor, status, external_account_ref, sync_cursor, connected_at,
               last_sync_at, last_sync_status, last_sync_error
          FROM pos_connections WHERE tenant_id = :t ORDER BY vendor
    """), {"t": tenant_id})).mappings().all()
    return [dict(r) for r in rows]


async def disconnect(db: AsyncSession, tenant_id: int, connection_id: int) -> bool:
    res = await db.execute(text("""
        UPDATE pos_connections SET status='disconnected', updated_at=now()
         WHERE id = :id AND tenant_id = :t
    """), {"id": connection_id, "t": tenant_id})
    return (res.rowcount or 0) > 0


# ---------------------------------------------------------------------------
# Sync — pull receipts and land them at the basket grain, idempotently.
# ---------------------------------------------------------------------------

async def sync_connection(db: AsyncSession, *, tenant_id: int, connection_id: int,
                          window_days: Optional[int] = None) -> Tuple[Optional[Dict], Optional[str]]:
    """Run one sync for a connection. Opens a pos_sync_runs row, pulls receipts via the
    vendor adapter, writes them to transactions/transaction_lines (idempotent), and
    closes the run ok/error. Returns (summary, None) or (None, error)."""
    conn = await get_connection(db, tenant_id, connection_id)
    if not conn:
        return None, "POS connection not found"
    if conn["status"] != "connected":
        return None, f"Connection is '{conn['status']}', not connected"

    vendor = conn["vendor"]
    today = datetime.now(timezone.utc).date()
    span = window_days or _DEFAULT_BACKFILL_DAYS
    window_start = today - timedelta(days=span - 1)
    window_end = today

    run_id = (await db.execute(text("""
        INSERT INTO pos_sync_runs (connection_id, tenant_id, window_start, window_end, status)
        VALUES (:c, :t, :ws, :we, 'running') RETURNING id
    """), {"c": connection_id, "t": tenant_id, "ws": window_start, "we": window_end})).scalar()
    await db.commit()

    try:
        receipts = await _adapter_pull(db, vendor, tenant_id=tenant_id,
                                       window_start=window_start, window_end=window_end)
        ingested, lines = await _write_receipts(db, tenant_id, vendor, receipts)
        aggregates = len({(r["store_id"], r["txn_date"]) for r in receipts})
        await db.execute(text("""
            UPDATE pos_sync_runs
               SET status='ok', finished_at=now(), receipts_ingested=:ri,
                   lines_ingested=:li, aggregates_computed=:ag
             WHERE id=:id
        """), {"ri": ingested, "li": lines, "ag": aggregates, "id": run_id})
        await db.execute(text("""
            UPDATE pos_connections
               SET last_sync_at=now(), last_sync_status='ok', last_sync_error=NULL,
                   sync_cursor=:cur, updated_at=now()
             WHERE id=:id
        """), {"cur": window_end.isoformat(), "id": connection_id})
        await db.commit()
        return {"run_id": run_id, "vendor": vendor, "status": "ok",
                "window_start": window_start.isoformat(), "window_end": window_end.isoformat(),
                "receipts_ingested": ingested, "lines_ingested": lines,
                "aggregates_computed": aggregates}, None
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        await db.execute(text("""
            UPDATE pos_sync_runs SET status='error', finished_at=now(), error=:e WHERE id=:id
        """), {"e": str(exc)[:500], "id": run_id})
        await db.execute(text("""
            UPDATE pos_connections SET last_sync_at=now(), last_sync_status='error',
                   last_sync_error=:e, status='error', updated_at=now() WHERE id=:id
        """), {"e": str(exc)[:500], "id": connection_id})
        await db.commit()
        logger.error(f"[pos] sync failed (vendor={vendor}, conn={connection_id}): {exc!r}")
        return None, f"Sync failed: {exc}"


async def _adapter_pull(db: AsyncSession, vendor: str, *, tenant_id: int,
                        window_start: date, window_end: date) -> List[Dict]:
    """Ask the vendor for its receipts in [window_start, window_end]. Only `mock` is
    implemented; a real adapter would call the vendor's Orders API with the OAuth token
    and map its response into the receipt shape below. A real vendor is refused before
    reaching here (is_vendor_available), so this is defence in depth."""
    if vendor == MOCK_VENDOR:
        return await _mock_pull(db, tenant_id, window_start, window_end)
    raise RuntimeError(f"{vendor} receipt pull is not integrated")


async def _mock_pull(db: AsyncSession, tenant_id: int, window_start: date,
                     window_end: date) -> List[Dict]:
    """A DETERMINISTIC demo pull. Builds one receipt per (store, day) over the window
    from the tenant's OWN stores/items, so every FK resolves and re-running ingests
    nothing new. Every row is is_synthetic — this is demo data, honestly labelled."""
    stores = (await db.execute(text(
        "SELECT id FROM stores WHERE tenant_id = :t ORDER BY id LIMIT 2"),
        {"t": tenant_id})).scalars().all()
    items = (await db.execute(text("""
        SELECT id, COALESCE(unit_price_aed, 5.00) AS price
          FROM items WHERE tenant_id = :t ORDER BY id LIMIT 3
    """), {"t": tenant_id})).mappings().all()
    if not stores or not items:
        return []  # nothing to attribute a mock basket to; a real tenant has stores/items

    receipts: List[Dict] = []
    day = window_start
    while day <= window_end:
        for store_id in stores:
            # Deterministic line composition: item i gets quantity (i+1).
            lines = []
            for i, it in enumerate(items):
                qty = Decimal(i + 1)
                price = Decimal(str(it["price"]))
                lines.append({"item_id": it["id"], "qty": qty,
                              "unit_price_aed": price, "discount_aed": Decimal("0.00")})
            receipts.append({
                "txn_ref": f"MOCK-{store_id}-{day.isoformat()}",
                "store_id": store_id,
                "txn_time": datetime(day.year, day.month, day.day, 12, 0, tzinfo=timezone.utc),
                "txn_date": day,
                "payment_method": "card",
                "register_id": "R1",
                "lines": lines,
            })
        day += timedelta(days=1)
    return receipts


async def _write_receipts(db: AsyncSession, tenant_id: int, vendor: str,
                          receipts: List[Dict]) -> Tuple[int, int]:
    """Idempotently write receipts to the basket grain. Returns (receipts, lines) that
    were NEW (a replay of the same window inserts nothing, via UNIQUE(tenant,source,ref))."""
    source = f"{_SOURCE_PREFIX}{vendor}"
    is_synthetic = vendor == MOCK_VENDOR
    receipts_written = 0
    lines_written = 0
    for r in receipts:
        total = sum((ln["qty"] * ln["unit_price_aed"] - ln["discount_aed"]) for ln in r["lines"])
        discount_total = sum(ln["discount_aed"] for ln in r["lines"])
        txn_id = (await db.execute(text("""
            INSERT INTO transactions (tenant_id, store_id, txn_time, txn_date, source, txn_ref,
                                      register_id, payment_method, status, total_aed,
                                      discount_total_aed, is_synthetic)
            VALUES (:t, :s, :tt, :td, :src, :ref, :reg, :pm, 'completed', :tot, :disc, :syn)
            ON CONFLICT (tenant_id, source, txn_ref) DO NOTHING
            RETURNING id
        """), {"t": tenant_id, "s": r["store_id"], "tt": r["txn_time"], "td": r["txn_date"],
               "src": source, "ref": r["txn_ref"], "reg": r.get("register_id"),
               "pm": r.get("payment_method"), "tot": total, "disc": discount_total,
               "syn": is_synthetic})).scalar()
        if txn_id is None:
            continue  # already ingested — idempotent skip
        receipts_written += 1
        for line_no, ln in enumerate(r["lines"], start=1):
            line_total = ln["qty"] * ln["unit_price_aed"] - ln["discount_aed"]
            await db.execute(text("""
                INSERT INTO transaction_lines (transaction_id, line_no, item_id, qty,
                                               unit_price_aed, discount_aed, line_total_aed)
                VALUES (:tx, :ln, :it, :q, :up, :disc, :lt)
            """), {"tx": txn_id, "ln": line_no, "it": ln["item_id"], "q": ln["qty"],
                   "up": ln["unit_price_aed"], "disc": ln["discount_aed"], "lt": line_total})
            lines_written += 1
    return receipts_written, lines_written


# ---------------------------------------------------------------------------
# Nightly loop — runs in the singletons container (exactly one process).
# ---------------------------------------------------------------------------

async def sync_all_connected(db: AsyncSession) -> Dict[str, Any]:
    """Sync every connected connection whose vendor is implemented. Real-vendor
    connections cannot exist (begin_oauth refuses them), so in practice this syncs the
    mock demo connections; the guard is defence in depth."""
    rows = (await db.execute(text("""
        SELECT id, tenant_id, vendor FROM pos_connections WHERE status = 'connected'
    """))).mappings().all()
    synced, skipped, failed = 0, 0, 0
    for row in rows:
        if row["vendor"] not in IMPLEMENTED_VENDORS:
            skipped += 1
            continue
        summary, err = await sync_connection(db, tenant_id=row["tenant_id"],
                                             connection_id=row["id"])
        if err:
            failed += 1
        else:
            synced += 1
    return {"connections": len(rows), "synced": synced, "skipped": skipped, "failed": failed}


async def pos_sync_loop() -> None:
    """Background task (singletons container). Pulls once shortly after start, then
    every settings.pos_sync_interval_seconds."""
    settings = get_settings()
    interval = settings.pos_sync_interval_seconds
    logger.info(f"POS connector sync started (every {interval // 3600}h)")
    # Let the app settle before the first pull.
    await asyncio.sleep(settings.pos_sync_startup_delay_seconds)
    while True:
        try:
            async with async_session() as db:
                result = await sync_all_connected(db)
            if result["connections"]:
                logger.info(f"[pos] sync pass: {result}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[pos] sync loop error: {exc!r}")
        await asyncio.sleep(interval)
