"""Operations Copilot — READ tools.

Purpose-built, parameterised, tenant-scoped queries — NOT free-form SQL, and the
LLM never sees these as callable tools (the graph calls them; the model only
receives their results as structured evidence). Every function takes the
server-verified auth context and re-checks tenant + store scope, so a compromised
or confused caller cannot widen its own reach.

The DB-touching functions are deliberately thin. The value-bearing, safety-
critical logic — turning rows into EvidenceItems — is a PURE function
(`build_inventory_evidence`) that is unit-tested without a database.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.operations.contracts import EvidenceItem, SourceType

# Columns pulled from the findings table — the same projection decision_center uses.
_FINDING_COLS = ("id, tenant_id, rule, category, severity, title, detail, evidence, "
                 "entity_type, entity_id, entity_name, metric_value, status, "
                 "recommended_action, action_type, detected_at, updated_at")


def finding_evidence(finding: Dict) -> Dict:
    """The finding's evidence blob as a dict (it may arrive as a JSON string)."""
    ev = finding.get("evidence")
    if isinstance(ev, str):
        try:
            ev = json.loads(ev)
        except (ValueError, TypeError):
            ev = {}
    return ev if isinstance(ev, dict) else {}


def finding_item_id(finding: Dict) -> Optional[int]:
    """The item a finding is about, when it is item-scoped. None otherwise."""
    if (finding.get("entity_type") or "").lower() != "item":
        return None
    try:
        return int(finding.get("entity_id"))
    except (TypeError, ValueError):
        return None


async def load_finding(db: AsyncSession, *, tenant_id: int,
                       finding_id: int) -> Optional[Dict]:
    """Load one finding, tenant-scoped. Returns None if it does not exist for
    this tenant (RLS + the explicit predicate both enforce the boundary)."""
    row = (await db.execute(
        text(f"SELECT {_FINDING_COLS} FROM findings "
             f"WHERE id = :fid AND tenant_id = :t"),
        {"fid": finding_id, "t": tenant_id},
    )).mappings().first()
    return dict(row) if row else None


async def get_inventory_state(db: AsyncSession, *, tenant_id: int, item_id: int,
                              store_ids: Optional[List[int]] = None) -> List[Dict]:
    """Current inventory posture for an item across stores, from the same
    `metric_inventory_state` view the worker uses (single source of truth).

    SCOPE SEMANTICS ARE STRICT so an empty scope can never leak the whole tenant:
      * store_ids=None   -> NO store filter (tenant-wide). Pass this ONLY for a
                            super_admin, whose scope IS the tenant.
      * store_ids=[...]  -> only those stores.
      * store_ids=[]     -> NOTHING (`= ANY('{}')` matches no row). An empty
                            accessible-store list is "no stores", not "all stores".
    The caller (never this function) decides whether a role earns the None path.
    """
    params: Dict[str, Any] = {"t": tenant_id, "item": item_id}
    predicate = ""
    if store_ids is not None:
        predicate = " AND store_id = ANY(:stores)"
        params["stores"] = list(store_ids)
    rows = (await db.execute(
        text(
            "SELECT store_id, store_name, item_id, item_name, category, "
            "current_stock, reorder_point, average_daily_sales, days_since_last_sale, "
            "is_out_of_stock, is_below_reorder "
            "FROM metric_inventory_state "
            "WHERE tenant_id = :t AND item_id = :item" + predicate +
            " ORDER BY current_stock ASC"
        ),
        params,
    )).mappings().all()
    return [dict(r) for r in rows]


def _feed_is_stale(age_hours: Optional[float], distinct_stamps: Optional[int],
                   max_age_hours: float) -> bool:
    """Has a store's inventory feed gone dark? PURE, so it's unit-testable.

    Feed-death is a STORE-wide, snapshot-aware question, not a per-row one — the
    same lesson flywheel.inventory_atp.inventory_freshness_ok already learned:
      * no timestamp at all  -> not stale (no signal is not evidence of a problem)
      * one distinct stamp    -> a bulk-loaded snapshot, nothing to be stale
                                 against (a static demo seed must not self-disable)
      * several distinct stamps -> a real feed; only then does the age gate apply.
    A quiet SKU's old timestamp is stability, not staleness — that's why the age
    is measured over the whole store, not the single row we're about to act on.
    """
    if age_hours is None or (distinct_stamps or 0) <= 1:
        return False
    return float(age_hours) > max_age_hours


async def stale_stock_feeds(db: AsyncSession, store_ids: List[int], *,
                            max_age_hours: float) -> List[int]:
    """Which of these stores' inventory feeds have gone dark? Aggregates store-wide
    so a quiet SKU doesn't read as stale; classification is the pure helper above.
    The finding-freshness gate protects the FINDING — this protects the STOCK
    NUMBER we're about to size an order on, using the tenant's freshness window."""
    if not store_ids:
        return []
    rows = (await db.execute(
        text("SELECT store_id, "
             "EXTRACT(EPOCH FROM (now() - MAX(COALESCE("
             "  updated_at, CAST(last_restock_date AS timestamptz))))) / 3600 AS age_hours, "
             "COUNT(DISTINCT COALESCE("
             "  updated_at, CAST(last_restock_date AS timestamptz))) AS distinct_stamps "
             "FROM inventory WHERE store_id = ANY(:s) GROUP BY store_id"),
        {"s": list(store_ids)},
    )).mappings().all()
    return [r["store_id"] for r in rows
            if _feed_is_stale(r["age_hours"], r["distinct_stamps"], max_age_hours)]


def _num(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def build_inventory_evidence(snapshot: Dict, *, observed_at: datetime,
                             prefix: str = "") -> List[EvidenceItem]:
    """Turn one metric_inventory_state row into EvidenceItems. PURE — no I/O.

    This is where a "number the copilot shows" is born, so it is deterministic
    and unit-tested. `observed_at` is passed in (never read from a clock here) so
    the freshness gate is testable and the function stays pure.
    """
    store_id = snapshot.get("store_id")
    tag = f"{prefix}s{store_id}_"
    items: List[EvidenceItem] = []

    stock = _num(snapshot.get("current_stock"))
    if stock is not None:
        items.append(EvidenceItem(
            evidence_id=f"{tag}stock", metric_name="current_stock",
            current_value=stock, unit="units",
            source_type=SourceType.INVENTORY_TABLE,
            source_reference=f"metric_inventory_state(store={store_id},item={snapshot.get('item_id')})",
            observed_at=observed_at,
        ))
    velocity = _num(snapshot.get("average_daily_sales"))
    if velocity is not None:
        items.append(EvidenceItem(
            evidence_id=f"{tag}velocity", metric_name="average_daily_sales",
            current_value=velocity, unit="units_per_day",
            source_type=SourceType.INVENTORY_TABLE,
            source_reference=f"metric_inventory_state(store={store_id},item={snapshot.get('item_id')})",
            observed_at=observed_at,
        ))
    reorder = _num(snapshot.get("reorder_point"))
    if reorder is not None:
        items.append(EvidenceItem(
            evidence_id=f"{tag}reorder", metric_name="reorder_point",
            current_value=reorder, unit="units",
            source_type=SourceType.INVENTORY_TABLE,
            source_reference=f"metric_inventory_state(store={store_id},item={snapshot.get('item_id')})",
            observed_at=observed_at,
        ))
    return items


def build_finding_evidence(finding: Dict, *, observed_at: datetime) -> List[EvidenceItem]:
    """Evidence carried by the finding itself (the deterministic rule's numbers).
    PURE. `metric_value` becomes one item; known numeric evidence keys become more."""
    items: List[EvidenceItem] = []
    ref = f"findings(id={finding.get('id')},rule={finding.get('rule')})"

    metric = _num(finding.get("metric_value"))
    if metric is not None:
        items.append(EvidenceItem(
            evidence_id="finding_metric",
            metric_name=str(finding.get("rule") or "finding_metric"),
            current_value=metric,
            unit="pct" if str(finding.get("rule") or "").endswith(("_drop", "_slump", "_spike")) else "units",
            source_type=SourceType.FINDING_EVIDENCE,
            source_reference=ref, observed_at=observed_at,
        ))
    ev = finding_evidence(finding)
    for key, value in ev.items():
        num = _num(value)
        if num is None:
            continue
        items.append(EvidenceItem(
            evidence_id=f"finding_{key}", metric_name=str(key), current_value=num,
            unit="units", source_type=SourceType.FINDING_EVIDENCE,
            source_reference=ref, observed_at=observed_at,
        ))
    return items
