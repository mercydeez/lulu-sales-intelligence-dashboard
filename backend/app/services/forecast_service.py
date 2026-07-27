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
from statistics import NormalDist
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

# --- E7-6: safety stock ------------------------------------------------------
# Detecting a stockout is a report. Preventing one is a product.
#
#   safety_stock  = z(service_level) × σ_daily_demand × √lead_time
#   reorder_point = avg_daily_demand × lead_time + safety_stock
#
# σ is the observed standard deviation of daily units for that store-item. With
# fewer than MIN_SIGMA_DAYS observations there is no meaningful spread, so safety
# stock is NOT invented — it comes back null with a reason, and the suggestion
# falls back to the plain days-of-cover trigger, saying so.
DEFAULT_SERVICE_LEVEL = 0.95      # a 95% chance of not stocking out in a lead time
MIN_SIGMA_DAYS = 14               # days of history needed before σ means anything
SIGMA_LOOKBACK_DAYS = 90
_NEEDS_SIGMA = "demand variability — needs at least 14 days of sales history for this item"
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
def service_level_z(service_level: float) -> float:
    """The z multiplier for a target service level. Exact, from the stdlib normal
    quantile — no lookup table to drift, no dependency to add.

    z(0.95) = 1.6449: hold enough extra stock that demand exceeds it in only 5% of
    lead times. Clamped to a sane range: a 100% service level implies infinite stock.
    """
    sl = min(max(float(service_level), 0.50), 0.9999)
    return NormalDist().inv_cdf(sl)


async def _demand_variability(
    db: AsyncSession, tenant_id: int, allowed: Optional[Sequence[int]],
) -> Dict[Tuple[int, int], Dict]:
    """σ and mean of DAILY units per (store, item) over the lookback window.

    Reads metric_sales_fact — the one place `units` is defined (E6-1) — so the
    safety-stock math and the KPI numbers can never disagree. Returns {} on any
    failure: a missing σ degrades to "no safety stock", never to a guessed one.
    """
    scope = ""
    params: Dict = {"tid": tenant_id}
    if allowed:
        scope = "AND s.store_id = ANY(:allowed)"
        params["allowed"] = list(allowed)

    try:
        # SIGMA_LOOKBACK_DAYS is interpolated, not bound: with a bound parameter
        # Postgres resolves `CURRENT_DATE - $n` through the `date - date -> integer`
        # overload and the comparison becomes `date >= integer`. It is a module
        # constant, never user input.
        #
        # A savepoint so a failure here cannot poison the caller's transaction
        # (ADR-009): this is an optional enrichment, not the request's purpose.
        async with db.begin_nested():
            rows = (await db.execute(text(f"""
                SELECT s.store_id, s.item_id,
                       AVG(s.units)::float          AS mu,
                       STDDEV_SAMP(s.units)::float  AS sigma,
                       COUNT(*)                     AS observations
                  FROM metric_sales_fact s
                 WHERE s.tenant_id = :tid
                   AND s.date >= (CURRENT_DATE - INTERVAL '{SIGMA_LOOKBACK_DAYS} days')
                   {scope}
                 GROUP BY s.store_id, s.item_id
            """), params)).mappings().all()
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"demand variability unavailable, safety stock withheld: {e}")
        return {}

    return {
        (r["store_id"], r["item_id"]): {
            "mu": r["mu"] or 0.0,
            # STDDEV_SAMP is NULL for a single row; a constant series gives 0.0.
            "sigma": r["sigma"],
            "observations": r["observations"],
        }
        for r in rows
    }


async def _lead_times_by_item(db: AsyncSession, tenant_id: int) -> Dict[int, int]:
    """Per-item supplier lead time. A blanket 7 days is a guess; the supplier's own
    number is a fact. Falls back to the caller's default where no supplier is known."""
    try:
        # Savepoint: an optional enrichment must never abort the caller's
        # transaction (ADR-009).
        async with db.begin_nested():
            rows = (await db.execute(text("""
                SELECT ps.item_id,
                       MIN(COALESCE(ps.lead_time_days, sp.lead_time_days)) AS lead_time_days
                  FROM product_suppliers ps
                  JOIN suppliers sp ON sp.id = ps.supplier_id
                 WHERE sp.tenant_id = :tid
                   AND COALESCE(ps.lead_time_days, sp.lead_time_days) IS NOT NULL
                 GROUP BY ps.item_id
            """), {"tid": tenant_id})).mappings().all()
        return {r["item_id"]: int(r["lead_time_days"]) for r in rows}
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"per-item lead times unavailable, using the default: {e}")
        return {}


async def reorder_suggestions(
    db: AsyncSession,
    tenant_id: int = 1,
    allowed: Optional[Sequence[int]] = None,
    store_id: Optional[int] = None,
    lead_time_days: int = 7,
    cover_target_days: int = 7,
    limit: int = 20,
    scan: int = 80,
    service_level: float = DEFAULT_SERVICE_LEVEL,
) -> Dict:
    """Forecast-driven reorder list: for each in-scope item, forecast daily
    demand, compute days-of-cover against the derived on-hand quantity, and flag
    items that will run out within the supplier lead time. Suggested order qty
    covers demand over (lead time + safety cover) minus current stock.
    """
    cache_key = generate_cache_key(
        f"forecast_reorder_t{tenant_id}_{_scope_suffix(allowed)}"
        f"_s{store_id}_lt{lead_time_days}_ct{cover_target_days}_l{limit}_sl{service_level}"
    )
    cached = await get_cached(cache_key)
    if cached:
        return cached

    accessible = list(allowed) if allowed else None
    inv = await DataSyncService.get_inventory_from_sales(
        db, store_id=store_id, accessible_stores=accessible, page=1, limit=scan
    )
    items = inv.get("items", [])

    z = service_level_z(service_level)
    variability = await _demand_variability(db, tenant_id, allowed)
    item_lead_times = await _lead_times_by_item(db, tenant_id)

    predictor = SalesPredictor()
    suggestions: List[Dict] = []

    for it in items:
        # The supplier's own lead time beats a blanket default.
        lt = item_lead_times.get(it["item_id"], lead_time_days)
        horizon = max(1, lt + cover_target_days)

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
        demand_over_lead = daily_demand * lt

        # --- safety stock (E7-6) -------------------------------------------
        v = variability.get((it["store_id"], it["item_id"]))
        sigma = v["sigma"] if v else None
        observations = v["observations"] if v else 0
        safety_stock: Optional[int] = None
        reorder_point: Optional[int] = None
        needs: Optional[str] = None
        formula: Optional[str] = None

        if sigma is not None and observations >= MIN_SIGMA_DAYS:
            ss = z * float(sigma) * math.sqrt(lt)
            safety_stock = int(math.ceil(ss))
            reorder_point = int(math.ceil(demand_over_lead + ss))
            formula = (
                f"safety stock = z({service_level:.2f})={z:.2f} × σ={float(sigma):.2f} "
                f"× √{lt}d = {safety_stock} units; "
                f"reorder point = {daily_demand:.2f}/d × {lt}d + {safety_stock} = {reorder_point} units"
            )
        else:
            # No spread, no safety stock. We say so rather than invent one.
            needs = _NEEDS_SIGMA

        # Trigger on the reorder point when we have one; otherwise the old
        # days-of-cover rule, and the payload admits which was used.
        if reorder_point is not None:
            needs_reorder = qty <= reorder_point
            trigger = "reorder_point"
        else:
            needs_reorder = days_of_cover < lt or qty <= it.get("reorder_level", 0)
            trigger = "days_of_cover"
        if not needs_reorder:
            continue

        # Order back up to the demand over (lead + cover) plus the buffer.
        target = daily_demand * horizon + (safety_stock or 0)
        recommended_qty = max(0, int(math.ceil(target - qty)))

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
            "lead_time_days": lt,
            "forecast_demand_lead_time": round(demand_over_lead, 1),
            "recommended_order_qty": recommended_qty,
            "urgency": "critical" if days_of_cover < lt / 2 else "warning",
            # E7-6: the buffer, where it came from, and why we ordered.
            "service_level": service_level,
            "service_level_z": round(z, 3),
            "demand_sigma": round(float(sigma), 2) if sigma is not None else None,
            "sigma_observations": observations,
            "safety_stock": safety_stock,
            "reorder_point": reorder_point,
            "trigger": trigger,
            "formula": formula,
            "needs": needs,
        })

    suggestions.sort(key=lambda s: s["days_of_cover"])
    suggestions = suggestions[:limit]

    result = {
        "lead_time_days": lead_time_days,
        "cover_target_days": cover_target_days,
        "service_level": service_level,
        "service_level_z": round(z, 3),
        "sigma_lookback_days": SIGMA_LOOKBACK_DAYS,
        "model_version": MODEL_VERSION,
        "count": len(suggestions),
        "critical_count": sum(1 for s in suggestions if s["urgency"] == "critical"),
        "with_safety_stock": sum(1 for s in suggestions if s["safety_stock"] is not None),
        "methodology": (
            "safety stock = z(service level) × σ(daily demand) × √(lead time); "
            "reorder point = forecast daily demand × lead time + safety stock. "
            "σ is measured over the last 90 days; where an item has under 14 days of "
            "history no safety stock is claimed and the days-of-cover rule is used instead."
        ),
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
