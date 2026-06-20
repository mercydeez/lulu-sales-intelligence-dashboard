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

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import logger
from app.services.forecast_service import reorder_suggestions

def _emit(tenant_id: int, event: str, data: Dict) -> None:
    """Fire a signed webhook for a procurement domain event (best-effort,
    fire-and-forget — never blocks or fails the operation)."""
    try:
        from app.services.webhook_service import dispatch_event_background
        dispatch_event_background(tenant_id, event, data)
    except Exception as e:  # pragma: no cover - webhooks are best-effort
        logger.debug(f"webhook emit skipped ({event}): {e}")


async def _log_event(db: AsyncSession, tenant_id: int, event_type: str,
                     entity_type: str, entity_id: Optional[int],
                     entity_ref: Optional[str], summary: str,
                     actor: Optional[int] = None,
                     metadata: Optional[Dict] = None) -> None:
    """Append an audit event WITHIN the caller's transaction (atomic with the
    action). Best-effort: a logging failure never breaks the operation."""
    try:
        await db.execute(text("""
            INSERT INTO procurement_events
                (tenant_id, event_type, entity_type, entity_id, entity_ref,
                 actor_user_id, summary, metadata)
            VALUES (:t, :et, :ent, :eid, :ref, :actor, :summary, CAST(:meta AS jsonb))
        """), {
            "t": tenant_id, "et": event_type, "ent": entity_type, "eid": entity_id,
            "ref": entity_ref, "actor": actor, "summary": summary,
            "meta": json.dumps(metadata or {}),
        })
    except Exception as e:  # pragma: no cover - audit is best-effort
        logger.warning(f"procurement audit log failed ({event_type}): {e}")


async def list_events(db: AsyncSession, tenant_id: int, limit: int = 50,
                      entity_type: Optional[str] = None,
                      entity_id: Optional[int] = None) -> List[Dict]:
    """The audit timeline — most recent procurement events first."""
    where = ["e.tenant_id = :t"]
    params: Dict = {"t": tenant_id, "limit": max(1, min(limit, 200))}
    if entity_type:
        where.append("e.entity_type = :ent")
        params["ent"] = entity_type
    if entity_id is not None:
        where.append("e.entity_id = :eid")
        params["eid"] = entity_id
    rows = (await db.execute(text(f"""
        SELECT e.id, e.event_type, e.entity_type, e.entity_id, e.entity_ref,
               e.summary, e.metadata, e.created_at,
               u.first_name, u.last_name
        FROM procurement_events e
        LEFT JOIN users u ON u.id = e.actor_user_id
        WHERE {' AND '.join(where)}
        ORDER BY e.created_at DESC, e.id DESC
        LIMIT :limit
    """), params)).fetchall()
    return [{
        "id": r.id, "event_type": r.event_type, "entity_type": r.entity_type,
        "entity_id": r.entity_id, "entity_ref": r.entity_ref, "summary": r.summary,
        "metadata": r.metadata,
        "actor": (f"{r.first_name} {r.last_name}".strip() if r.first_name else "System"),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]


PRICE_TOLERANCE_PCT = 0.01  # 1% unit-cost tolerance in the 3-way match
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
# Approval policy
# ---------------------------------------------------------------------------
async def get_approval_rule(db: AsyncSession, tenant_id: int) -> Dict:
    """The tenant's auto-approve threshold (0 = never auto-approve)."""
    row = (await db.execute(text(
        "SELECT auto_approve_under FROM approval_rules WHERE tenant_id = :t"
    ), {"t": tenant_id})).fetchone()
    return {"auto_approve_under": float(row.auto_approve_under) if row else 0.0}


async def set_approval_rule(db: AsyncSession, tenant_id: int, auto_approve_under: float) -> Dict:
    await db.execute(text("""
        INSERT INTO approval_rules (tenant_id, auto_approve_under, updated_at)
        VALUES (:t, :a, CURRENT_TIMESTAMP)
        ON CONFLICT (tenant_id) DO UPDATE
            SET auto_approve_under = EXCLUDED.auto_approve_under, updated_at = CURRENT_TIMESTAMP
    """), {"t": tenant_id, "a": max(0.0, auto_approve_under)})
    await db.commit()
    return {"auto_approve_under": max(0.0, auto_approve_under)}


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
    await _log_event(db, tenant_id, "supplier.created", "supplier", row.id, name,
                     f"Supplier '{name}' added")
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

    auto_under = (await get_approval_rule(db, tenant_id))["auto_approve_under"]
    created = []
    auto_approved = 0
    for supplier_id, lines in grouped.items():
        po = await _create_po(db, tenant_id, supplier_id, lines,
                              source="forecast_reorder", created_by=created_by)
        await _log_event(db, tenant_id, "po.created", "purchase_order", po["po_id"],
                         po["po_number"],
                         f"PO {po['po_number']} created from forecast for "
                         f"{po['line_count']} item(s) — AED {po['total_amount']:,.0f}",
                         actor=created_by, metadata={"total": po["total_amount"]})
        # Auto-approve low-value POs per the tenant's policy.
        if auto_under > 0 and po["total_amount"] < auto_under:
            await db.execute(text("""
                UPDATE purchase_orders
                SET status = 'approved', approved_by = :by, approved_at = :now
                WHERE id = :id
            """), {"by": created_by, "now": datetime.now(timezone.utc), "id": po["po_id"]})
            po["status"] = "approved"
            auto_approved += 1
            await _log_event(db, tenant_id, "po.approved", "purchase_order", po["po_id"],
                             po["po_number"],
                             f"PO {po['po_number']} auto-approved (under AED {auto_under:,.0f})",
                             actor=created_by)
        created.append(po)

    await db.commit()
    for po in created:
        _emit(tenant_id, "purchase_order.created", po)
        if po["status"] == "approved":
            _emit(tenant_id, "purchase_order.approved", po)
    msg = f"Created {len(created)} draft PO(s) from forecast."
    if auto_approved:
        msg = (f"Created {len(created)} PO(s) from forecast — {auto_approved} auto-approved "
               f"(under AED {auto_under:,.0f}).")
    return {
        "created": created,
        "auto_approved": auto_approved,
        "skipped_no_supplier": skipped_no_supplier,
        "skipped_already_open": skipped_already_open,
        "message": msg,
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


async def pending_approvals(db: AsyncSession, tenant_id: int) -> Dict:
    """POs awaiting a human decision (draft / pending_approval) — the approval
    inbox. Returns the list plus a summary (count + total value at stake)."""
    rows = (await db.execute(text("""
        SELECT po.id, po.po_number, po.status, po.total_amount, po.currency,
               po.source, po.created_at, s.name AS supplier_name,
               COUNT(l.id) AS line_count
        FROM purchase_orders po
        JOIN suppliers s ON s.id = po.supplier_id
        LEFT JOIN purchase_order_lines l ON l.po_id = po.id
        WHERE po.tenant_id = :t AND po.status IN ('draft', 'pending_approval')
        GROUP BY po.id, s.name ORDER BY po.total_amount DESC
    """), {"t": tenant_id})).fetchall()
    items = [{
        "id": r.id, "po_number": r.po_number, "status": r.status,
        "total_amount": float(r.total_amount), "currency": r.currency,
        "source": r.source, "supplier_name": r.supplier_name,
        "line_count": int(r.line_count or 0),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]
    return {
        "count": len(items),
        "total_value": round(sum(i["total_amount"] for i in items), 2),
        "currency": items[0]["currency"] if items else "AED",
        "purchase_orders": items,
    }


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
    await _log_event(db, tenant_id, "goods.received", "goods_receipt", receipt_id,
                     receipt_number,
                     f"Goods receipt {receipt_number} recorded — PO #{po_id} now "
                     f"{po_status.replace('_', ' ')}", actor=user_id)
    await db.commit()
    _emit(tenant_id, "goods.received", {
        "po_id": po_id, "receipt_number": receipt_number, "po_status": po_status,
    })
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
    await _log_event(db, tenant_id, f"po.{new_status}", "purchase_order", po_id, None,
                     f"PO #{po_id} → {new_status.replace('_', ' ')}", actor=user_id)
    await db.commit()
    if new_status in ("approved", "sent", "received"):
        _emit(tenant_id, f"purchase_order.{new_status}", {"po_id": po_id, "status": new_status})
    return {"po_id": po_id, "status": new_status}


# ---------------------------------------------------------------------------
# Supplier invoices + 3-way match
# ---------------------------------------------------------------------------
async def record_invoice(db: AsyncSession, tenant_id: int, po_id: int,
                         invoice_number: str, lines: List[Dict],
                         notes: Optional[str] = None) -> Dict:
    """Record a supplier invoice against a PO. `lines` is
    [{item_id, quantity, unit_cost}]. The amount is derived from the lines."""
    po = (await db.execute(text(
        "SELECT supplier_id FROM purchase_orders WHERE id = :id AND tenant_id = :t"
    ), {"id": po_id, "t": tenant_id})).fetchone()
    if not po:
        raise ValueError("Purchase order not found")
    if not lines:
        raise ValueError("An invoice needs at least one line")

    amount = sum(float(l["unit_cost"]) * int(l["quantity"]) for l in lines)
    inv_id = (await db.execute(text("""
        INSERT INTO supplier_invoices (tenant_id, po_id, supplier_id, invoice_number, invoice_amount)
        VALUES (:t, :po, :s, :num, :amt) RETURNING id
    """), {"t": tenant_id, "po": po_id, "s": po.supplier_id,
           "num": invoice_number, "amt": amount})).scalar()
    for l in lines:
        qty, cost = int(l["quantity"]), float(l["unit_cost"])
        await db.execute(text("""
            INSERT INTO supplier_invoice_lines (invoice_id, item_id, quantity, unit_cost, line_total)
            VALUES (:inv, :i, :q, :c, :lt)
        """), {"inv": inv_id, "i": l["item_id"], "q": qty, "c": cost, "lt": qty * cost})
    if notes:
        await db.execute(text("UPDATE supplier_invoices SET notes = :n WHERE id = :id"),
                         {"n": notes, "id": inv_id})
    await _log_event(db, tenant_id, "invoice.recorded", "supplier_invoice", inv_id,
                     invoice_number,
                     f"Invoice {invoice_number} recorded against PO #{po_id} — AED {amount:,.0f}")
    await db.commit()
    return {"invoice_id": inv_id, "po_id": po_id, "invoice_number": invoice_number,
            "invoice_amount": round(amount, 2), "status": "received"}


async def three_way_match(db: AsyncSession, tenant_id: int, invoice_id: int) -> Dict:
    """Compare ORDERED (PO) vs RECEIVED (goods receipts) vs INVOICED for each item
    and flag quantity/price variances. Persists the match result on the invoice."""
    inv = (await db.execute(text(
        "SELECT id, po_id FROM supplier_invoices WHERE id = :id AND tenant_id = :t"
    ), {"id": invoice_id, "t": tenant_id})).fetchone()
    if not inv:
        raise ValueError("Invoice not found")

    ordered_rows = (await db.execute(text("""
        SELECT l.item_id, i.name AS item_name, SUM(l.quantity) AS ordered_qty,
               SUM(l.received_qty) AS received_qty, MAX(l.unit_cost) AS po_unit_cost
        FROM purchase_order_lines l JOIN items i ON i.id = l.item_id
        WHERE l.po_id = :po GROUP BY l.item_id, i.name
    """), {"po": inv.po_id})).fetchall()
    ordered = {r.item_id: r for r in ordered_rows}

    inv_rows = (await db.execute(text("""
        SELECT item_id, SUM(quantity) AS inv_qty, MAX(unit_cost) AS inv_unit_cost
        FROM supplier_invoice_lines WHERE invoice_id = :id GROUP BY item_id
    """), {"id": invoice_id})).fetchall()
    invoiced = {r.item_id: r for r in inv_rows}

    result_lines = []
    overall_ok = True
    for item_id in set(ordered) | set(invoiced):
        o = ordered.get(item_id)
        v = invoiced.get(item_id)
        ordered_qty = int(o.ordered_qty) if o else 0
        received_qty = int(o.received_qty) if o else 0
        inv_qty = int(v.inv_qty) if v else 0
        po_cost = float(o.po_unit_cost) if o else None
        inv_cost = float(v.inv_unit_cost) if v else None

        # Pay for what was received; price must match the PO within tolerance.
        qty_match = inv_qty == received_qty and received_qty > 0
        price_match = (po_cost is not None and inv_cost is not None
                       and abs(po_cost - inv_cost) <= max(0.01, po_cost * PRICE_TOLERANCE_PCT))
        on_po = o is not None
        line_ok = qty_match and price_match and on_po
        if not line_ok:
            overall_ok = False
        result_lines.append({
            "item_id": item_id,
            "item_name": o.item_name if o else (f"item {item_id} (not on PO)"),
            "ordered_qty": ordered_qty, "received_qty": received_qty, "invoiced_qty": inv_qty,
            "po_unit_cost": po_cost, "invoice_unit_cost": inv_cost,
            "qty_match": qty_match, "price_match": price_match, "ok": line_ok,
        })

    match_status = "matched" if overall_ok else "exception"
    new_status = "matched" if overall_ok else "exception"
    await db.execute(text(
        "UPDATE supplier_invoices SET match_status = :m, status = :s WHERE id = :id"
    ), {"m": match_status, "s": new_status, "id": invoice_id})
    await _log_event(db, tenant_id,
                     "invoice.match_exception" if match_status == "exception" else "invoice.matched",
                     "supplier_invoice", invoice_id, None,
                     f"Invoice #{invoice_id} 3-way match: {match_status}"
                     + (f" ({len([l for l in result_lines if not l['ok']])} variance(s))"
                        if match_status == "exception" else ""))
    await db.commit()
    if match_status == "exception":
        _emit(tenant_id, "invoice.match_exception",
              {"invoice_id": invoice_id, "po_id": inv.po_id})
    return {
        "invoice_id": invoice_id, "po_id": inv.po_id, "match_status": match_status,
        "exceptions": [l for l in result_lines if not l["ok"]],
        "lines": sorted(result_lines, key=lambda x: x["item_id"]),
    }


async def list_invoices(db: AsyncSession, tenant_id: int, po_id: Optional[int] = None) -> List[Dict]:
    where = "tenant_id = :t"
    params: Dict = {"t": tenant_id}
    if po_id:
        where += " AND po_id = :po"
        params["po"] = po_id
    rows = (await db.execute(text(f"""
        SELECT id, po_id, invoice_number, invoice_amount, currency, status,
               match_status, created_at
        FROM supplier_invoices WHERE {where} ORDER BY created_at DESC
    """), params)).fetchall()
    return [{
        "id": r.id, "po_id": r.po_id, "invoice_number": r.invoice_number,
        "invoice_amount": float(r.invoice_amount), "currency": r.currency,
        "status": r.status, "match_status": r.match_status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]
