"""
Shared forecast service (B1.7) — the single place the rest of the product
consumes the forecasting engine, so the forecasts drive the app rather than
living only in the Forecast Lab.

The Lab trains/selects models off the request path (services/forecast_trainer.py,
routes/analytics.py) and caches the result. This module turns forecasts into the
operational decisions the product needs:

  - revenue_projection(...)  → dashboard forward revenue (units forecast × price)
  - reorder_suggestions(...) → inventory: days-of-cover < lead time → reorder qty
  - demand_baseline(...)     → promotions: expected un-promoted demand (uplift base)
  - forecast_narrative(...)  → AI assistant: a data-grounded forecast answer

Heavy rolling-origin model selection stays in the Lab. Here we reuse the
lightweight, deterministic SeasonalTrendModel (predictor.py) for per-series
forecasts so these endpoints stay fast, plus the per-item SalesPredictor (already
Redis-cached) for reorder math. Everything is tenant/scope-aware and cached.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import logger
from app.services.cache import get_cached, set_cached, generate_cache_key
from app.services.data_sync import DataSyncService
from app.services.predictor import SeasonalTrendModel, SalesPredictor, MIN_TRAINING_DAYS

# Forecast-derived endpoints are cheap to recompute and want to track the live
# stream, so keep the TTL short.
FORECAST_TTL = 900  # 15 minutes
DEFAULT_HORIZON = 14
MODEL_VERSION = SalesPredictor.MODEL_VERSION


# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------
def _scope_suffix(allowed: Optional[Sequence[int]]) -> str:
    if allowed:
        return "stores_" + ",".join(map(str, sorted(allowed)))
    return "all"


async def _aggregate_daily_series(
    db: AsyncSession,
    tenant_id: int,
    allowed: Optional[Sequence[int]],
    store_id: Optional[int] = None,
) -> List[Tuple[date, float]]:
    """Tenant/scope-aware daily total-units series from the unified fact view."""
    where = ["s.tenant_id = :tenant_id"]
    params: Dict = {"tenant_id": tenant_id}
    if store_id is not None:
        where.append("s.store_id = :store_id")
        params["store_id"] = store_id
    elif allowed:
        where.append("s.store_id = ANY(:allowed)")
        params["allowed"] = list(allowed)
    sql = (
        "SELECT s.date AS d, SUM(s.sales) AS units FROM sales_fact_view s "
        f"WHERE {' AND '.join(where)} GROUP BY s.date ORDER BY s.date"
    )
    rows = (await db.execute(text(sql), params)).fetchall()
    return [(r.d, float(r.units or 0)) for r in rows]


async def _avg_unit_price(db: AsyncSession) -> float:
    row = (await db.execute(text("SELECT AVG(unit_price_aed) AS p FROM items"))).fetchone()
    return float(row.p) if row and row.p else 0.0


# ---------------------------------------------------------------------------
# 1. Dashboard revenue projection
# ---------------------------------------------------------------------------
async def revenue_projection(
    db: AsyncSession,
    tenant_id: int = 1,
    allowed: Optional[Sequence[int]] = None,
    horizon: int = DEFAULT_HORIZON,
) -> Dict:
    """Forward revenue projection for the dashboard: forecast aggregate daily
    units with the seasonal-trend model, then value them at the average unit
    price. Returns daily points (with an 80%-ish confidence band) plus totals.
    """
    cache_key = generate_cache_key(
        f"forecast_projection_t{tenant_id}_{_scope_suffix(allowed)}_{horizon}"
    )
    cached = await get_cached(cache_key)
    if cached:
        return cached

    series = await _aggregate_daily_series(db, tenant_id, allowed)
    avg_price = await _avg_unit_price(db)

    out: Dict = {
        "horizon_days": horizon,
        "currency": "AED",
        "model_version": MODEL_VERSION,
        "projected_units": 0,
        "projected_revenue": 0.0,
        "avg_daily_units": 0.0,
        "avg_daily_revenue": 0.0,
        "daily": [],
        "status": "insufficient_history",
    }

    if len(series) < MIN_TRAINING_DAYS:
        return out

    try:
        model = SeasonalTrendModel(series)
        points = model.forecast(horizon)
    except ValueError:
        return out

    daily = []
    total_units = 0.0
    for p in points:
        units = max(0.0, p["predicted_sales"])
        total_units += units
        daily.append({
            "date": p["prediction_date"],
            "units": round(units, 1),
            "revenue": round(units * avg_price, 2),
            "revenue_lower": round(max(0.0, p["confidence_lower"]) * avg_price, 2),
            "revenue_upper": round(p["confidence_upper"] * avg_price, 2),
        })

    out.update({
        "projected_units": int(round(total_units)),
        "projected_revenue": round(total_units * avg_price, 2),
        "avg_daily_units": round(total_units / horizon, 1) if horizon else 0.0,
        "avg_daily_revenue": round(total_units * avg_price / horizon, 2) if horizon else 0.0,
        "daily": daily,
        "status": "ready",
    })
    await set_cached(cache_key, out, FORECAST_TTL)
    return out


# ---------------------------------------------------------------------------
# 2. Inventory reorder suggestions (forecast → days-of-cover → reorder qty)
# ---------------------------------------------------------------------------
async def reorder_suggestions(
    db: AsyncSession,
    tenant_id: int = 1,
    allowed: Optional[Sequence[int]] = None,
    store_id: Optional[int] = None,
    lead_time_days: int = 7,
    cover_target_days: int = 7,
    limit: int = 20,
    scan: int = 80,
) -> Dict:
    """Forecast-driven reorder list: for each in-scope item, forecast daily
    demand, compute days-of-cover against the derived on-hand quantity, and flag
    items that will run out within the supplier lead time. Suggested order qty
    covers demand over (lead time + safety cover) minus current stock.
    """
    cache_key = generate_cache_key(
        f"forecast_reorder_t{tenant_id}_{_scope_suffix(allowed)}"
        f"_s{store_id}_lt{lead_time_days}_ct{cover_target_days}_l{limit}"
    )
    cached = await get_cached(cache_key)
    if cached:
        return cached

    accessible = list(allowed) if allowed else None
    inv = await DataSyncService.get_inventory_from_sales(
        db, store_id=store_id, accessible_stores=accessible, page=1, limit=scan
    )
    items = inv.get("items", [])

    predictor = SalesPredictor()
    horizon = max(1, lead_time_days + cover_target_days)
    suggestions: List[Dict] = []

    for it in items:
        try:
            preds = await predictor.predict(it["store_id"], it["item_id"], days=horizon)
        except Exception:
            preds = []
        if preds:
            forecast_demand = sum(max(0.0, p["predicted_sales"]) for p in preds)
            daily_demand = forecast_demand / horizon
        else:
            # Fall back to the reorder level as a coarse demand proxy.
            daily_demand = max(0.01, it.get("reorder_level", 0) / max(1, horizon))
            forecast_demand = daily_demand * horizon

        qty = max(0, int(it.get("quantity", 0)))
        daily_demand = max(daily_demand, 0.01)
        days_of_cover = qty / daily_demand
        demand_over_lead = daily_demand * lead_time_days
        needs_reorder = days_of_cover < lead_time_days or qty <= it.get("reorder_level", 0)
        if not needs_reorder:
            continue

        recommended_qty = max(0, int(math.ceil(daily_demand * horizon - qty)))
        suggestions.append({
            "store_id": it["store_id"],
            "store_name": it.get("store_name"),
            "item_id": it["item_id"],
            "item_name": it.get("item_name"),
            "category": it.get("category"),
            "on_hand": qty,
            "reorder_level": it.get("reorder_level", 0),
            "forecast_daily_demand": round(daily_demand, 2),
            "days_of_cover": round(days_of_cover, 1),
            "lead_time_days": lead_time_days,
            "forecast_demand_lead_time": round(demand_over_lead, 1),
            "recommended_order_qty": recommended_qty,
            "urgency": "critical" if days_of_cover < lead_time_days / 2 else "warning",
        })

    suggestions.sort(key=lambda s: s["days_of_cover"])
    suggestions = suggestions[:limit]

    result = {
        "lead_time_days": lead_time_days,
        "cover_target_days": cover_target_days,
        "model_version": MODEL_VERSION,
        "count": len(suggestions),
        "critical_count": sum(1 for s in suggestions if s["urgency"] == "critical"),
        "suggestions": suggestions,
    }
    await set_cached(cache_key, result, FORECAST_TTL)
    return result


# ---------------------------------------------------------------------------
# 3. Promotion uplift baseline (expected demand WITHOUT the promotion)
# ---------------------------------------------------------------------------
async def demand_baseline(
    db: AsyncSession,
    tenant_id: int = 1,
    allowed: Optional[Sequence[int]] = None,
    category: Optional[str] = None,
    horizon: int = DEFAULT_HORIZON,
) -> Dict:
    """Forecast the baseline (un-promoted) demand for a scope/category over the
    horizon. Promotions measure uplift as actual demand minus this baseline, so
    the forecasting engine — not a flat historical average — anchors the lift.
    """
    cache_key = generate_cache_key(
        f"forecast_baseline_t{tenant_id}_{_scope_suffix(allowed)}_{category or 'all'}_{horizon}"
    )
    cached = await get_cached(cache_key)
    if cached:
        return cached

    where = ["s.tenant_id = :tenant_id"]
    params: Dict = {"tenant_id": tenant_id}
    if allowed:
        where.append("s.store_id = ANY(:allowed)")
        params["allowed"] = list(allowed)
    join = ""
    if category:
        join = "JOIN items i ON i.id = s.item_id"
        where.append("i.category = :category")
        params["category"] = category
    sql = (
        f"SELECT s.date AS d, SUM(s.sales) AS units FROM sales_fact_view s {join} "
        f"WHERE {' AND '.join(where)} GROUP BY s.date ORDER BY s.date"
    )
    rows = (await db.execute(text(sql), params)).fetchall()
    series = [(r.d, float(r.units or 0)) for r in rows]

    out = {
        "category": category,
        "horizon_days": horizon,
        "model_version": MODEL_VERSION,
        "baseline_units": 0,
        "baseline_daily_avg": 0.0,
        "status": "insufficient_history",
    }
    if len(series) < MIN_TRAINING_DAYS:
        return out

    try:
        points = SeasonalTrendModel(series).forecast(horizon)
    except ValueError:
        return out

    baseline_units = sum(max(0.0, p["predicted_sales"]) for p in points)
    out.update({
        "baseline_units": int(round(baseline_units)),
        "baseline_daily_avg": round(baseline_units / horizon, 1) if horizon else 0.0,
        "status": "ready",
    })
    await set_cached(cache_key, out, FORECAST_TTL)
    return out


def expected_uplift(actual_units: float, baseline_units: float) -> Dict:
    """Given observed demand and the forecast baseline, express the promotion
    uplift in absolute units and percent (the shared metric for promo ROI)."""
    delta = actual_units - baseline_units
    pct = (delta / baseline_units * 100) if baseline_units > 0 else 0.0
    return {
        "baseline_units": int(round(baseline_units)),
        "actual_units": int(round(actual_units)),
        "uplift_units": int(round(delta)),
        "uplift_pct": round(pct, 1),
    }


# ---------------------------------------------------------------------------
# 4. AI-assistant forecast narrative
# ---------------------------------------------------------------------------
async def forecast_narrative(
    db: AsyncSession,
    tenant_id: int = 1,
    allowed: Optional[Sequence[int]] = None,
    horizon: int = DEFAULT_HORIZON,
) -> str:
    """A short, data-grounded forecast answer for the AI assistant — projected
    units/revenue for the next `horizon` days plus the top reorder risks."""
    proj = await revenue_projection(db, tenant_id, allowed, horizon)
    if proj.get("status") != "ready":
        return ("📈 **Forecast:** Not enough history yet to project the next "
                f"{horizon} days for this scope. The model needs at least "
                f"{MIN_TRAINING_DAYS} days of sales.")

    lines = [
        f"📈 **{horizon}-Day Forecast**",
        "",
        f"• Projected sales: **{proj['projected_units']:,}** units",
        f"• Projected revenue: **AED {proj['projected_revenue']:,.0f}**",
        f"• Daily average: **{proj['avg_daily_units']:,.0f}** units "
        f"(~AED {proj['avg_daily_revenue']:,.0f}/day)",
        f"• Model: `{proj['model_version']}`",
    ]

    try:
        reorder = await reorder_suggestions(db, tenant_id, allowed, limit=5)
        if reorder.get("suggestions"):
            lines.append("")
            lines.append("⚠️ **Top reorder risks (forecast-driven):**")
            for s in reorder["suggestions"]:
                lines.append(
                    f"• **{s['item_name']}** @ {s['store_name']}: "
                    f"{s['days_of_cover']:.0f} days of cover → order ~{s['recommended_order_qty']} units"
                )
    except Exception as e:  # pragma: no cover - narrative is best-effort
        logger.warning(f"forecast_narrative reorder section failed: {e}")

    return "\n".join(lines)
