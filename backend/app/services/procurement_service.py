"""
Procure-to-pay service (Part III-E) — the system of record that turns the
forecasting engine's reorder signal into action.

The flagship flow is generate_draft_pos_from_reorder(): take the B1.7
forecast-driven reorder suggestions, map each item to its preferred supplier,
group into one draft PO per supplier (respecting MOQ), and persist them for
approval. Everything is tenant-scoped. Money movement (invoice/payment) is
deliberately out of scope.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import logger
from app.services.forecast_service import reorder_suggestions

OPEN_STATUSES = ("draft", "pending_approval", "approved", "sent", "partially_received")
STATUS_TRANSITIONS = {
    "draft": {"pending_approval", "approved", "cancelled"},
    "pending_approval": {"approved", "cancelled"},
    "approved": {"sent", "cancelled"},
    "sent": {"partially_received", "received", "cancelled"},
    "partially_received": {"received", "cancelled"},
    "received": set(),
    "cancelled": set(),
}
RECEIVABLE_STATUSES = ("approved", "sent", "partially_received")


# ---------------------------------------------------------------------------
# Suppliers + catalog
# ---------------------------------------------------------------------------
async def list_suppliers(db: AsyncSession, tenant_id: int) -> List[Dict]:
    rows = (await db.execute(text("""
        SELECT s.id, s.name, s.contact_email, s.contact_phone, s.lead_time_days,
               s.status, COUNT(ps.id) AS catalog_items
        FROM suppliers s
        LEFT JOIN product_suppliers ps ON ps.supplier_id = s.id
        WHERE s.tenant_id = :t
        GROUP BY s.id ORDER BY s.name
    """), {"t": tenant_id})).fetchall()
    return [{
        "id": r.id, "name": r.name, "contact_email": r.contact_email,
        "contact_phone": r.contact_phone, "lead_time_days": r.lead_time_days,
        "status": r.status, "catalog_items": int(r.catalog_items or 0),
    } for r in rows]


async def create_supplier(db: AsyncSession, tenant_id: int, name: str,
                          contact_email: Optional[str] = None,
                          contact_phone: Optional[str] = None,
                          lead_time_days: int = 7) -> Dict:
    row = (await db.execute(text("""
        INSERT INTO suppliers (tenant_id, name, contact_email, contact_phone, lead_time_days)
        VALUES (:t, :name, :email, :phone, :lt)
        RETURNING id, created_at
    """), {"t": tenant_id, "name": name, "email": contact_email,
           "phone": contact_phone, "lt": lead_time_days})).fetchone()
    await db.commit()
    return {"id": row.id, "name": name, "lead_time_days": lead_time_days, "status": "active"}


# ---------------------------------------------------------------------------
# Forecast → draft purchase orders
# ---------------------------------------------------------------------------
async def generate_draft_pos_from_reorder(
    db: AsyncSession,
    tenant_id: int,
    allowed: Optional[Sequence[int]] = None,
    lead_time_days: int = 7,
    cover_target_days: int = 7,
    created_by: Optional[int] = None,
) -> Dict:
    """Forecast → action: pull the reorder suggestions, aggregate the needed
    quantity per item across stores, map each item to its preferred supplier,
    and create one draft PO per supplier. Items already on an open PO are skipped
    so repeated runs don't duplicate orders."""
    reorder = await reorder_suggestions(
        db, tenant_id=tenant_id, allowed=allowed,
        lead_time_days=lead_time_days, cover_target_days=cover_target_days,
        limit=500, scan=500,
    )
    suggestions = reorder.get("suggestions", [])
    if not suggestions:
        return {"created": [], "skipped_no_supplier": [], "skipped_already_open": [],
                "message": "No items currently need reordering."}

    # Aggregate recommended qty per item across stores; keep the worst cover.
    by_item: Dict[int, Dict] = {}
    for s in suggestions:
        it = by_item.setdefault(s["item_id"], {
            "item_id": s["item_id"], "item_name": s.get("item_name"),
            "qty": 0, "days_of_cover": s.get("days_of_cover"),
        })
        it["qty"] += int(s.get("recommended_order_qty") or 0)
        if s.get("days_of_cover") is not None:
            it["days_of_cover"] = min(it["days_of_cover"], s["days_of_cover"])

    # Items already on an open PO — don't reorder them again.
    open_item_rows = (await db.execute(text("""
        SELECT DISTINCT l.item_id
        FROM purchase_order_lines l
        JOIN purchase_orders po ON po.id = l.po_id
        WHERE po.tenant_id = :t AND po.status = ANY(:statuses)
    """), {"t": tenant_id, "statuses": list(OPEN_STATUSES)})).fetchall()
    already_open = {r.item_id for r in open_item_rows}

    # Map each item to its preferred supplier + cost/MOQ.
    grouped: Dict[int, List[Dict]] = {}
    skipped_no_supplier: List[Dict] = []
    skipped_already_open: List[Dict] = []
    for item_id, info in by_item.items():
        if info["qty"] <= 0:
            continue
        if item_id in already_open:
            skipped_already_open.append(info)
            continue
        sup = (await db.execute(text("""
            SELECT supplier_id, unit_cost, moq FROM product_suppliers
            WHERE tenant_id = :t AND item_id = :i
            ORDER BY is_preferred DESC, unit_cost ASC LIMIT 1
        """), {"t": tenant_id, "i": item_id})).fetchone()
        if not sup:
            skipped_no_supplier.append(info)
            continue
        qty = max(int(info["qty"]), int(sup.moq or 1))
        grouped.setdefault(sup.supplier_id, []).append({
            **info, "quantity": qty, "unit_cost": float(sup.unit_cost or 0),
        })

    created = []
    for supplier_id, lines in grouped.items():
        po = await _create_po(db, tenant_id, supplier_id, lines,
                              source="forecast_reorder", created_by=created_by)
        created.append(po)

    await db.commit()
    return {
        "created": created,
        "skipped_no_supplier": skipped_no_supplier,
        "skipped_already_open": skipped_already_open,
        "message": f"Created {len(created)} draft PO(s) from forecast.",
    }


async def _create_po(db: AsyncSession, tenant_id: int, supplier_id: int,
                     lines: List[Dict], source: str = "manual",
                     created_by: Optional[int] = None) -> Dict:
    """Insert a draft PO + its lines, compute the total, and stamp a PO number."""
    total = sum(l["quantity"] * l["unit_cost"] for l in lines)
    po_id = (await db.execute(text("""
        INSERT INTO purchase_orders (tenant_id, supplier_id, po_number, status,
                                     total_amount, source, created_by)
        VALUES (:t, :s, :num, 'draft', :total, :src, :by)
        RETURNING id
    """), {"t": tenant_id, "s": supplier_id, "num": f"PO-TMP-{tenant_id}",
           "total": total, "src": source, "by": created_by})).scalar()
    po_number = f"PO-{tenant_id:02d}-{po_id:05d}"
    await db.execute(text("UPDATE purchase_orders SET po_number = :n WHERE id = :id"),
                     {"n": po_number, "id": po_id})
    for l in lines:
        await db.execute(text("""
            INSERT INTO purchase_order_lines (po_id, item_id, quantity, unit_cost,
                                              line_total, days_of_cover)
            VALUES (:po, :i, :q, :c, :lt, :doc)
        """), {"po": po_id, "i": l["item_id"], "q": l["quantity"],
               "c": l["unit_cost"], "lt": l["quantity"] * l["unit_cost"],
               "doc": l.get("days_of_cover")})
    return {"po_id": po_id, "po_number": po_number, "supplier_id": supplier_id,
            "status": "draft", "total_amount": round(total, 2), "line_count": len(lines)}


# ---------------------------------------------------------------------------
# Read + workflow
# ---------------------------------------------------------------------------
async def list_purchase_orders(db: AsyncSession, tenant_id: int,
                               status: Optional[str] = None) -> List[Dict]:
    where = "po.tenant_id = :t"
    params: Dict = {"t": tenant_id}
    if status:
        where += " AND po.status = :st"
        params["st"] = status
    rows = (await db.execute(text(f"""
        SELECT po.id, po.po_number, po.status, po.total_amount, po.currency,
               po.source, po.created_at, po.approved_at, s.name AS supplier_name,
               COUNT(l.id) AS line_count
        FROM purchase_orders po
        JOIN suppliers s ON s.id = po.supplier_id
        LEFT JOIN purchase_order_lines l ON l.po_id = po.id
        WHERE {where}
        GROUP BY po.id, s.name ORDER BY po.created_at DESC
    """), params)).fetchall()
    return [{
        "id": r.id, "po_number": r.po_number, "status": r.status,
        "total_amount": float(r.total_amount), "currency": r.currency,
        "source": r.source, "supplier_name": r.supplier_name,
        "line_count": int(r.line_count or 0),
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "approved_at": r.approved_at.isoformat() if r.approved_at else None,
    } for r in rows]


async def get_purchase_order(db: AsyncSession, tenant_id: int, po_id: int) -> Optional[Dict]:
    po = (await db.execute(text("""
        SELECT po.*, s.name AS supplier_name FROM purchase_orders po
        JOIN suppliers s ON s.id = po.supplier_id
        WHERE po.id = :id AND po.tenant_id = :t
    """), {"id": po_id, "t": tenant_id})).fetchone()
    if not po:
        return None
    lines = (await db.execute(text("""
        SELECT l.id, l.item_id, i.name AS item_name, l.quantity, l.unit_cost,
               l.line_total, l.days_of_cover, l.received_qty
        FROM purchase_order_lines l JOIN items i ON i.id = l.item_id
        WHERE l.po_id = :id ORDER BY l.id
    """), {"id": po_id})).fetchall()
    receipts = (await db.execute(text("""
        SELECT id, receipt_number, status, received_at
        FROM goods_receipts WHERE po_id = :id AND tenant_id = :t ORDER BY id
    """), {"id": po_id, "t": tenant_id})).fetchall()
    return {
        "id": po.id, "po_number": po.po_number, "status": po.status,
        "supplier_id": po.supplier_id, "supplier_name": po.supplier_name,
        "total_amount": float(po.total_amount), "currency": po.currency,
        "source": po.source, "notes": po.notes,
        "created_at": po.created_at.isoformat() if po.created_at else None,
        "approved_at": po.approved_at.isoformat() if po.approved_at else None,
        "lines": [{
            "id": l.id, "item_id": l.item_id, "item_name": l.item_name,
            "quantity": l.quantity, "unit_cost": float(l.unit_cost),
            "line_total": float(l.line_total),
            "received_qty": l.received_qty,
            "days_of_cover": float(l.days_of_cover) if l.days_of_cover is not None else None,
        } for l in lines],
        "receipts": [{
            "id": r.id, "receipt_number": r.receipt_number, "status": r.status,
            "received_at": r.received_at.isoformat() if r.received_at else None,
        } for r in receipts],
    }


async def receive_po(db: AsyncSession, tenant_id: int, po_id: int,
                     lines: Optional[List[Dict]] = None,
                     user_id: Optional[int] = None) -> Dict:
    """Record a goods receipt against a PO. `lines` is [{po_line_id, received_qty}];
    omit it to receive everything still outstanding. Increments per-line received
    quantity and moves the PO to 'partially_received' or 'received'."""
    po = (await db.execute(text(
        "SELECT status FROM purchase_orders WHERE id = :id AND tenant_id = :t"
    ), {"id": po_id, "t": tenant_id})).fetchone()
    if not po:
        raise ValueError("Purchase order not found")
    if po.status not in RECEIVABLE_STATUSES:
        raise ValueError(f"Cannot receive a PO in status '{po.status}'")

    po_lines = (await db.execute(text(
        "SELECT id, item_id, quantity, received_qty FROM purchase_order_lines WHERE po_id = :id"
    ), {"id": po_id})).fetchall()
    line_map = {l.id: l for l in po_lines}

    if lines:
        receive = {int(x["po_line_id"]): int(x["received_qty"]) for x in lines}
    else:  # receive all outstanding
        receive = {l.id: (l.quantity - l.received_qty) for l in po_lines
                   if l.quantity > l.received_qty}
    receive = {k: v for k, v in receive.items() if v > 0}
    if not receive:
        raise ValueError("Nothing left to receive")

    for plid, qty in receive.items():
        if plid not in line_map:
            raise ValueError(f"PO line {plid} is not on this purchase order")
        remaining = line_map[plid].quantity - line_map[plid].received_qty
        if qty > remaining:
            raise ValueError(
                f"Over-receipt on line {plid}: {qty} exceeds {remaining} outstanding")

    receipt_id = (await db.execute(text("""
        INSERT INTO goods_receipts (tenant_id, po_id, receipt_number, received_by)
        VALUES (:t, :po, :num, :by) RETURNING id
    """), {"t": tenant_id, "po": po_id, "num": f"GRN-TMP-{tenant_id}", "by": user_id})).scalar()
    receipt_number = f"GRN-{tenant_id:02d}-{receipt_id:05d}"
    await db.execute(text("UPDATE goods_receipts SET receipt_number = :n WHERE id = :id"),
                     {"n": receipt_number, "id": receipt_id})

    for plid, qty in receive.items():
        await db.execute(text("""
            INSERT INTO goods_receipt_lines (receipt_id, po_line_id, item_id, received_qty)
            VALUES (:r, :pl, :i, :q)
        """), {"r": receipt_id, "pl": plid, "i": line_map[plid].item_id, "q": qty})
        await db.execute(text(
            "UPDATE purchase_order_lines SET received_qty = received_qty + :q WHERE id = :id"
        ), {"q": qty, "id": plid})

    refreshed = (await db.execute(text(
        "SELECT quantity, received_qty FROM purchase_order_lines WHERE po_id = :id"
    ), {"id": po_id})).fetchall()
    fully = all(l.received_qty >= l.quantity for l in refreshed)
    po_status = "received" if fully else "partially_received"
    await db.execute(text("UPDATE goods_receipts SET status = :s WHERE id = :id"),
                     {"s": "complete" if fully else "partial", "id": receipt_id})
    await db.execute(text("""
        UPDATE purchase_orders
        SET status = :s, received_at = CASE WHEN :fully THEN :now ELSE received_at END
        WHERE id = :id
    """), {"s": po_status, "fully": fully, "now": datetime.now(timezone.utc), "id": po_id})
    await db.commit()
    return {
        "receipt_id": receipt_id, "receipt_number": receipt_number,
        "po_id": po_id, "po_status": po_status,
        "lines_received": [{"po_line_id": k, "qty": v} for k, v in receive.items()],
    }


async def transition_status(db: AsyncSession, tenant_id: int, po_id: int,
                            new_status: str, user_id: Optional[int] = None,
                            approval_threshold: Optional[float] = None) -> Dict:
    """Move a PO along its lifecycle, validating the transition. Approving a PO
    over `approval_threshold` is rejected (a higher authority must approve)."""
    po = (await db.execute(text(
        "SELECT status, total_amount FROM purchase_orders WHERE id = :id AND tenant_id = :t"
    ), {"id": po_id, "t": tenant_id})).fetchone()
    if not po:
        raise ValueError("Purchase order not found")
    if new_status not in STATUS_TRANSITIONS.get(po.status, set()):
        raise ValueError(f"Cannot move PO from '{po.status}' to '{new_status}'")
    if (new_status == "approved" and approval_threshold is not None
            and float(po.total_amount) > approval_threshold):
        raise ValueError(
            f"PO total {float(po.total_amount):.2f} exceeds approval threshold "
            f"{approval_threshold:.2f} — escalate to a higher authority")

    stamp = {
        "approved": ("approved_at", "approved_by"),
        "sent": ("sent_at", None),
        "received": ("received_at", None),
    }.get(new_status)
    sets = ["status = :st"]
    params: Dict = {"st": new_status, "id": po_id, "t": tenant_id,
                    "now": datetime.now(timezone.utc)}
    if stamp:
        sets.append(f"{stamp[0]} = :now")
        if stamp[1]:
            sets.append(f"{stamp[1]} = :uid")
            params["uid"] = user_id
    await db.execute(text(
        f"UPDATE purchase_orders SET {', '.join(sets)} WHERE id = :id AND tenant_id = :t"
    ), params)
    await db.commit()
    return {"po_id": po_id, "status": new_status}
