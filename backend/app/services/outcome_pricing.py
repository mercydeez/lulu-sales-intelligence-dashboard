"""
Outcome-based pricing — wired to the measure loop.

The fee = base + a share of the CONFIRMED realised value, with a savings guarantee:
"save at least N× your base fee, or the value-share is waived." The realised value
comes only from improved findings whose AED value a human has confirmed — the
platform never fabricates a saving. The pure fee/guarantee math (`build_statement`)
unit-tests without a DB; the async helpers manage realizations + the period rollup.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_PLAN = {
    "base_fee_aed": 0.0, "value_share_pct": 0.0,
    "savings_guarantee_multiple": 0.0, "currency": "AED", "active": False,
}

# A conservative default window for "a detected problem that was cleared". The
# suggestion = the affected entity's real avg daily revenue × this many days. It is a
# STARTING ESTIMATE the operator must confirm/adjust — never an auto-billed amount.
RECOVERY_DAYS = 3


def _money(v) -> float:
    return round(float(v or 0), 2)


def suggest_from_daily(daily_revenue_aed: float, recovery_days: int = RECOVERY_DAYS) -> float:
    """Conservative suggested realised value from an entity's daily revenue. Pure."""
    return _money(_money(daily_revenue_aed) * recovery_days)


def build_statement(confirmed_value: float, plan: Dict) -> Dict:
    """Compute the outcome fee from confirmed realised value. Pure.

    variable = confirmed_value × value_share_pct. Guarantee: if a multiple is set and
    confirmed_value < multiple × base_fee, the variable portion is WAIVED (customer
    pays base only). Non-circular: the guarantee is measured against the base fee."""
    confirmed_value = _money(confirmed_value)
    base = _money(plan.get("base_fee_aed"))
    share = _money(plan.get("value_share_pct"))
    multiple = _money(plan.get("savings_guarantee_multiple"))

    variable_full = _money(confirmed_value * share / 100.0)
    required = _money(multiple * base) if multiple else 0.0
    met = (confirmed_value >= required) if multiple else True
    waived = bool(multiple and not met)

    variable = 0.0 if waived else variable_full
    total = _money(base + variable)

    return {
        "currency": plan.get("currency", "AED"),
        "confirmed_value_aed": confirmed_value,
        "base_fee_aed": base,
        "value_share_pct": share,
        "variable_fee_aed": variable,
        "total_fee_aed": total,
        "guarantee": {
            "multiple": multiple,
            "required_savings_aed": required,
            "met": met,
            "variable_waived": waived,
        },
        # The headline a buyer cares about: did the platform pay for itself?
        "value_to_fee_ratio": (round(confirmed_value / total, 2) if total > 0 else None),
    }


# --- async helpers ---------------------------------------------------------

async def get_plan(db: AsyncSession, tenant_id: int) -> Dict:
    row = (await db.execute(text("""
        SELECT base_fee_aed, value_share_pct, savings_guarantee_multiple, currency, active
        FROM outcome_pricing_plans WHERE tenant_id = :t
    """), {"t": tenant_id})).mappings().fetchone()
    if not row:
        return {**DEFAULT_PLAN, "exists": False}
    return {
        "base_fee_aed": _money(row["base_fee_aed"]),
        "value_share_pct": _money(row["value_share_pct"]),
        "savings_guarantee_multiple": _money(row["savings_guarantee_multiple"]),
        "currency": row["currency"], "active": bool(row["active"]), "exists": True,
    }


async def upsert_plan(db: AsyncSession, tenant_id: int, *, base_fee_aed: float,
                      value_share_pct: float, savings_guarantee_multiple: float,
                      active: bool) -> Dict:
    await db.execute(text("""
        INSERT INTO outcome_pricing_plans
            (tenant_id, base_fee_aed, value_share_pct, savings_guarantee_multiple, active)
        VALUES (:t, :base, :share, :mult, :active)
        ON CONFLICT (tenant_id) DO UPDATE SET
            base_fee_aed = :base, value_share_pct = :share,
            savings_guarantee_multiple = :mult, active = :active, updated_at = now()
    """), {"t": tenant_id, "base": base_fee_aed, "share": value_share_pct,
           "mult": savings_guarantee_multiple, "active": active})
    await db.commit()
    return await get_plan(db, tenant_id)


async def ensure_realizations(db: AsyncSession, tenant_id: int) -> None:
    """Create a pending realization row for every improved finding that doesn't have
    one yet (lazy — avoids a cross-process worker grant). Never fabricates a value."""
    await db.execute(text("""
        INSERT INTO value_realizations (tenant_id, finding_id, method, status)
        SELECT f.tenant_id, f.id, 'operator_to_confirm', 'pending'
        FROM findings f
        WHERE f.tenant_id = :t AND f.outcome_status = 'improved'
          AND NOT EXISTS (SELECT 1 FROM value_realizations v WHERE v.finding_id = f.id)
    """), {"t": tenant_id})
    await db.commit()


async def valuation_context(db: AsyncSession, tenant_id: int, entity_type: Optional[str],
                            entity_id: Optional[str]) -> Dict:
    """Real economics for a finding's entity, to GROUND the operator's confirmed value
    (not an attribution claim). Returns daily/30-day revenue (AED) + a conservative
    suggested starting figure. Suggestion is None when no entity economics exist."""
    base = "SELECT COALESCE(SUM(s.sales * it.unit_price_aed),0) AS rev30 " \
           "FROM sales_fact_view s JOIN items it ON it.id = s.item_id " \
           "WHERE s.tenant_id = :t AND s.date >= (CURRENT_DATE - 30)"
    params: Dict = {"t": tenant_id}
    basis = "tenant"
    try:
        if entity_type == "store" and entity_id and str(entity_id).isdigit():
            base += " AND s.store_id = :eid"; params["eid"] = int(entity_id); basis = "store (30d)"
        elif entity_type == "item" and entity_id and str(entity_id).isdigit():
            base += " AND s.item_id = :eid"; params["eid"] = int(entity_id); basis = "item (30d)"
        elif entity_type == "category" and entity_id:
            base += " AND it.category = :eid"; params["eid"] = str(entity_id); basis = "category (30d)"
        elif entity_type == "global" or not entity_type:
            basis = "tenant (30d)"
        else:
            return {"basis": "no entity economics", "daily_revenue_aed": None,
                    "window_revenue_aed": None, "suggested_value_aed": None, "method": None}
        rev30 = _money((await db.execute(text(base), params)).scalar() or 0)
    except Exception:
        return {"basis": "unavailable", "daily_revenue_aed": None,
                "window_revenue_aed": None, "suggested_value_aed": None, "method": None}
    daily = _money(rev30 / 30.0)
    suggestion = suggest_from_daily(daily) if daily > 0 else None
    return {
        "basis": basis,
        "daily_revenue_aed": daily,
        "window_revenue_aed": rev30,
        "suggested_value_aed": suggestion,
        "method": (f"{basis} avg daily revenue × {RECOVERY_DAYS}-day recovery window — "
                   "conservative starting estimate; confirm or adjust") if suggestion else None,
    }


async def list_realizations(db: AsyncSession, tenant_id: int) -> List[Dict]:
    await ensure_realizations(db, tenant_id)
    rows = (await db.execute(text("""
        SELECT v.id, v.finding_id, v.estimated_value_aed, v.confirmed_value_aed,
               v.status, v.note, v.confirmed_by, v.confirmed_at,
               f.title, f.entity_type, f.entity_id, f.entity_name, f.metric_before, f.metric_after
        FROM value_realizations v JOIN findings f ON f.id = v.finding_id
        WHERE v.tenant_id = :t
        ORDER BY (v.status = 'pending') DESC, v.updated_at DESC
        LIMIT 200
    """), {"t": tenant_id})).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("estimated_value_aed", "confirmed_value_aed", "metric_before", "metric_after"):
            d[k] = _money(d[k]) if d.get(k) is not None else None
        d["confirmed_at"] = d["confirmed_at"].isoformat() if d.get("confirmed_at") else None
        # Ground pending rows with real entity economics + a conservative suggestion.
        if d["status"] == "pending":
            d["valuation"] = await valuation_context(db, tenant_id, d.get("entity_type"), d.get("entity_id"))
        out.append(d)
    return out


async def set_realization(db: AsyncSession, tenant_id: int, realization_id: int, *,
                          confirmed_value_aed: Optional[float], status: str,
                          note: Optional[str], user: str) -> Optional[Dict]:
    if status not in ("confirmed", "dismissed", "pending"):
        return None
    confirmed_at = "now()" if status == "confirmed" else "NULL"
    row = (await db.execute(text(f"""
        UPDATE value_realizations
           SET confirmed_value_aed = :val, status = :st, note = :note,
               confirmed_by = :by, confirmed_at = {confirmed_at}, updated_at = now()
         WHERE id = :id AND tenant_id = :t
         RETURNING id, status, confirmed_value_aed
    """), {"val": confirmed_value_aed, "st": status, "note": note,
           "by": user if status == "confirmed" else None,
           "id": realization_id, "t": tenant_id})).mappings().fetchone()
    await db.commit()
    return dict(row) if row else None


async def confirmed_value_total(db: AsyncSession, tenant_id: int) -> Dict:
    row = (await db.execute(text("""
        SELECT COALESCE(SUM(confirmed_value_aed), 0) AS total, COUNT(*) AS n
        FROM value_realizations
        WHERE tenant_id = :t AND status = 'confirmed' AND confirmed_value_aed IS NOT NULL
    """), {"t": tenant_id})).mappings().fetchone()
    return {"confirmed_value_aed": _money(row["total"]), "confirmed_count": int(row["n"])}


async def statement(db: AsyncSession, tenant_id: int) -> Dict:
    plan = await get_plan(db, tenant_id)
    totals = await confirmed_value_total(db, tenant_id)
    stmt = build_statement(totals["confirmed_value_aed"], plan)
    stmt["confirmed_count"] = totals["confirmed_count"]
    stmt["plan_active"] = plan["active"]
    return stmt
