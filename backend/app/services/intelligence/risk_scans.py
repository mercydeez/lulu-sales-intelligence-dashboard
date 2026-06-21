"""
Risk scans — the detectors behind Foresia's Risk Radar.

Each detector returns a list of finding dicts; `run_scan` upserts them (deduped by
key), resolves findings that are no longer present, and emits an SSE + signed
webhook for new high-severity ones. Detectors reuse existing engines where it
helps (forecast-driven reorder for stockout risk) and otherwise read directly
from `sales_fact_view` — so findings are always grounded in real data.

The scan runs as the owner connection (it must write tenant-stamped rows for any
tenant); reads of `risk_findings` by the API/Sage are tenant-scoped.
"""
from __future__ import annotations

import json
from typing import Dict, List, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import logger
from app.services.database import async_session
from app.services.alert_service import make_dedupe_key

SCAN_TYPES = ["stockout_risk", "demand_drop", "return_spike", "dead_stock"]
_SEV_BASE = {"high": 100.0, "medium": 60.0, "low": 30.0}


# ---------------------------------------------------------------------------
# Detectors  (each returns List[finding dict])
# ---------------------------------------------------------------------------
async def _detect_stockout(db: AsyncSession, tenant_id: int) -> List[Dict]:
    """Items that will run out within the supplier lead time (forecast-driven)."""
    from app.services.forecast_service import reorder_suggestions
    out = await reorder_suggestions(db, tenant_id=tenant_id, allowed=None, limit=20)
    findings: List[Dict] = []
    for s in out.get("suggestions", []):
        sev = "high" if s.get("urgency") == "critical" else "medium"
        cover = float(s.get("days_of_cover", 0) or 0)
        findings.append({
            "type": "stockout_risk",
            "severity": sev,
            "score": _SEV_BASE[sev] + max(0.0, 14.0 - cover),  # sooner stockout ranks higher
            "title": f"{s.get('item_name')} at {s.get('store_name')} runs out in ~{cover:.0f} days",
            "detail": (f"On hand {s.get('on_hand')}, forecast {s.get('forecast_daily_demand')}/day; "
                       f"reorder ~{s.get('recommended_order_qty')} (lead {s.get('lead_time_days')}d)."),
            "store_id": s.get("store_id"),
            "item_id": s.get("item_id"),
            "metric": {"days_of_cover": cover, "on_hand": s.get("on_hand"),
                       "recommended_order_qty": s.get("recommended_order_qty")},
            "dedupe_key": make_dedupe_key("stockout_risk", s.get("store_id"), s.get("item_id")),
        })
    return findings


async def _detect_demand_drop(db: AsyncSession, tenant_id: int) -> List[Dict]:
    """Stores whose last-7-day daily sales fell well below their prior 3-week norm."""
    rows = (await db.execute(text("""
        WITH daily AS (
            SELECT store_id, date, SUM(sales) AS units
            FROM sales_fact_view
            WHERE tenant_id = :tid AND date >= CURRENT_DATE - INTERVAL '28 days'
            GROUP BY store_id, date
        ), agg AS (
            SELECT store_id,
                AVG(units) FILTER (WHERE date >= CURRENT_DATE - INTERVAL '7 days')  AS recent,
                AVG(units) FILTER (WHERE date <  CURRENT_DATE - INTERVAL '7 days')  AS baseline
            FROM daily GROUP BY store_id
        )
        SELECT a.store_id, s.name, a.recent, a.baseline
        FROM agg a JOIN stores s ON s.id = a.store_id
        WHERE a.baseline > 0 AND a.recent IS NOT NULL AND a.recent < 0.7 * a.baseline
    """), {"tid": tenant_id})).fetchall()
    findings: List[Dict] = []
    for r in rows:
        drop = 1.0 - (float(r.recent) / float(r.baseline))
        sev = "high" if drop >= 0.4 else "medium"
        findings.append({
            "type": "demand_drop",
            "severity": sev,
            "score": _SEV_BASE[sev] + drop * 50.0,
            "title": f"Sales at {r.name} down {drop*100:.0f}% vs the prior 3 weeks",
            "detail": (f"Last 7d averaged {float(r.recent):,.0f} units/day vs a "
                       f"{float(r.baseline):,.0f} baseline — investigate demand or supply."),
            "store_id": r.store_id, "item_id": None,
            "metric": {"recent": round(float(r.recent), 1), "baseline": round(float(r.baseline), 1),
                       "drop_pct": round(drop * 100, 1)},
            "dedupe_key": make_dedupe_key("demand_drop", r.store_id, None),
        })
    return findings


async def _detect_return_spike(db: AsyncSession, tenant_id: int) -> List[Dict]:
    """Stores where returns (negative sales) spiked vs the prior weeks."""
    rows = (await db.execute(text("""
        SELECT f.store_id, s.name,
            SUM(CASE WHEN f.date >= CURRENT_DATE - INTERVAL '7 days' AND f.sales < 0
                     THEN -f.sales ELSE 0 END) AS recent_returns,
            SUM(CASE WHEN f.date <  CURRENT_DATE - INTERVAL '7 days' AND f.sales < 0
                     THEN -f.sales ELSE 0 END) / 3.0 AS baseline_returns
        FROM sales_fact_view f JOIN stores s ON s.id = f.store_id
        WHERE f.tenant_id = :tid AND f.date >= CURRENT_DATE - INTERVAL '28 days'
        GROUP BY f.store_id, s.name
    """), {"tid": tenant_id})).fetchall()
    findings: List[Dict] = []
    for r in rows:
        recent = float(r.recent_returns or 0)
        base = float(r.baseline_returns or 0)
        if recent < 20 or recent <= 1.5 * base:   # ignore noise / normal levels
            continue
        ratio = recent / base if base > 0 else 999.0
        sev = "high" if ratio >= 2.5 else "medium"
        findings.append({
            "type": "return_spike",
            "severity": sev,
            "score": _SEV_BASE[sev] + min(40.0, ratio * 5.0),
            "title": f"Returns spiking at {r.name}",
            "detail": (f"{recent:,.0f} units returned in the last 7d vs a "
                       f"{base:,.0f}/week baseline ({ratio:.1f}x) — check quality or pricing."),
            "store_id": r.store_id, "item_id": None,
            "metric": {"recent_returns": round(recent, 1), "baseline_returns": round(base, 1),
                       "ratio": round(ratio, 1)},
            "dedupe_key": make_dedupe_key("return_spike", r.store_id, None),
        })
    return findings


async def _detect_dead_stock(db: AsyncSession, tenant_id: int) -> List[Dict]:
    """Items that used to sell but have gone cold in the last 30 days."""
    rows = (await db.execute(text("""
        SELECT i.id AS item_id, i.name,
            SUM(CASE WHEN f.date >= CURRENT_DATE - INTERVAL '30 days' THEN f.sales ELSE 0 END) AS recent,
            SUM(CASE WHEN f.date <  CURRENT_DATE - INTERVAL '30 days'
                     AND f.date >= CURRENT_DATE - INTERVAL '120 days' THEN f.sales ELSE 0 END) AS prior
        FROM sales_fact_view f JOIN items i ON i.id = f.item_id
        WHERE f.tenant_id = :tid AND f.date >= CURRENT_DATE - INTERVAL '120 days'
        GROUP BY i.id, i.name
        HAVING SUM(CASE WHEN f.date >= CURRENT_DATE - INTERVAL '30 days' THEN f.sales ELSE 0 END) <= 0
           AND SUM(CASE WHEN f.date <  CURRENT_DATE - INTERVAL '30 days'
                        AND f.date >= CURRENT_DATE - INTERVAL '120 days' THEN f.sales ELSE 0 END) >= 200
        ORDER BY prior DESC
        LIMIT 15
    """), {"tid": tenant_id})).fetchall()
    findings: List[Dict] = []
    for r in rows:
        findings.append({
            "type": "dead_stock",
            "severity": "low",
            "score": _SEV_BASE["low"] + min(30.0, float(r.prior) / 100.0),
            "title": f"{r.name} has gone cold",
            "detail": (f"No net sales in the last 30 days after {int(r.prior):,} units in the "
                       f"prior quarter — capital may be tied up in dead stock."),
            "store_id": None, "item_id": r.item_id,
            "metric": {"recent": int(r.recent), "prior": int(r.prior)},
            "dedupe_key": make_dedupe_key("dead_stock", None, r.item_id),
        })
    return findings


_DETECTORS = (_detect_stockout, _detect_demand_drop, _detect_return_spike, _detect_dead_stock)


# ---------------------------------------------------------------------------
# Persistence + orchestration
# ---------------------------------------------------------------------------
async def _upsert_finding(db: AsyncSession, tenant_id: int, f: Dict) -> bool:
    """Insert or refresh a finding. Returns True if it was newly inserted."""
    row = (await db.execute(text("""
        INSERT INTO risk_findings
            (tenant_id, type, severity, score, title, detail, store_id, item_id, metric, dedupe_key, status, updated_at)
        VALUES
            (:tenant_id, :type, :severity, :score, :title, :detail, :store_id, :item_id,
             CAST(:metric AS jsonb), :dedupe_key, 'open', now())
        ON CONFLICT (tenant_id, dedupe_key) DO UPDATE SET
            severity = EXCLUDED.severity, score = EXCLUDED.score, title = EXCLUDED.title,
            detail = EXCLUDED.detail, store_id = EXCLUDED.store_id, item_id = EXCLUDED.item_id,
            metric = EXCLUDED.metric, status = 'open', updated_at = now()
        RETURNING (xmax = 0) AS inserted
    """), {
        "tenant_id": tenant_id, "type": f["type"], "severity": f["severity"],
        "score": float(f["score"]), "title": f["title"], "detail": f.get("detail"),
        "store_id": f.get("store_id"), "item_id": f.get("item_id"),
        "metric": json.dumps(f.get("metric") or {}),
        "dedupe_key": f["dedupe_key"],
    })).fetchone()
    return bool(row and row.inserted)


async def _resolve_stale(db: AsyncSession, tenant_id: int, seen_keys: Sequence[str]) -> None:
    """Close open findings of the scanned types that this run no longer detected."""
    keys = list(seen_keys)
    await db.execute(text("""
        UPDATE risk_findings SET status = 'resolved', updated_at = now()
        WHERE tenant_id = :tid AND status = 'open' AND type = ANY(:types)
          AND (:has_keys = FALSE OR dedupe_key <> ALL(:keys))
    """), {"tid": tenant_id, "types": SCAN_TYPES, "keys": keys, "has_keys": len(keys) > 0})


async def _emit_high(tenant_id: int, f: Dict) -> None:
    """Push new high-severity findings to the live alert stream + signed webhooks."""
    payload = {
        "kind": "risk", "type": f["type"], "severity": f["severity"],
        "title": f["title"], "detail": f.get("detail"),
        "store_id": f.get("store_id"), "item_id": f.get("item_id"),
        "tenant_id": tenant_id,
    }
    try:
        from app.services.redis_client import publish_alert
        await publish_alert(payload)
    except Exception as e:
        logger.warning("risk SSE publish failed: %s", e)
    try:
        from app.services.webhook_service import dispatch_event_background
        dispatch_event_background(tenant_id, "risk.detected", payload)
    except Exception as e:
        logger.warning("risk webhook dispatch failed: %s", e)


async def run_scan(tenant_id: int) -> Dict:
    """Run every detector for one tenant, persist + dedupe findings, resolve stale
    ones, and emit new high-severity findings. Returns a small summary."""
    all_findings: List[Dict] = []
    async with async_session() as db:
        for detector in _DETECTORS:
            try:
                all_findings.extend(await detector(db, tenant_id))
            except Exception as e:
                logger.warning("risk detector %s failed (tenant %s): %s", detector.__name__, tenant_id, e)

        seen_keys, new_high = set(), []
        for f in all_findings:
            seen_keys.add(f["dedupe_key"])
            try:
                if await _upsert_finding(db, tenant_id, f) and f["severity"] == "high":
                    new_high.append(f)
            except Exception as e:
                logger.warning("risk finding upsert failed: %s", e)
        await _resolve_stale(db, tenant_id, seen_keys)
        await db.commit()

    for f in new_high:
        await _emit_high(tenant_id, f)

    logger.info("risk scan tenant=%s findings=%d new_high=%d", tenant_id, len(all_findings), len(new_high))
    return {"tenant_id": tenant_id, "findings": len(all_findings), "new_high": len(new_high)}


async def run_scan_all_tenants() -> Dict:
    """Scan every tenant (used by the scheduled worker job)."""
    async with async_session() as db:
        try:
            rows = (await db.execute(text("SELECT id FROM tenants ORDER BY id"))).fetchall()
            tenant_ids = [r.id for r in rows] or [1]
        except Exception:
            tenant_ids = [1, 2]
    results = [await run_scan(tid) for tid in tenant_ids]
    return {"tenants": len(results), "results": results}
