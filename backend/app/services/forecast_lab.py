"""
Forecast Lab & analytics computation/cache layer.

WHY THIS MODULE EXISTS (dependency direction + mega-file): the Forecast Lab
training pipeline (`compute_and_cache_model_metrics`), its cross-worker warm
lease, and the store-distribution aggregation are shared by the analytics
routes, the cache warmer, and the background forecast trainer. They used to
live in `app.routes.analytics` (which made two *services* import a route
module and pushed analytics.py past 1000 lines). They now live here, below the
web layer; `app.routes.analytics` re-exports every name so the old import path
keeps working.
"""
import asyncio

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone
from typing import List, Optional

from app.config import logger
from app.models.sales import Sale, Store, Item
from app.services.cache import set_cached, generate_cache_key, CACHE_TTL


# =============================================================================
# Store distribution (shared by the /stores route and the cache warmer)
# =============================================================================

def store_distribution_cache_key(allowed_stores, tenant_id: int = 1):
    """Cache key for the store-distribution scope (empty/None => all stores),
    scoped by tenant so super_admins of different tenants (who share the 'all'
    scope) never collide on one key."""
    stores_suffix = f"_stores_{','.join(map(str, sorted(allowed_stores)))}" if allowed_stores else "_all"
    return generate_cache_key(f"analytics_stores_t{tenant_id}{stores_suffix}")


async def compute_and_cache_store_distribution(db: AsyncSession, allowed_stores, tenant_id: int = 1) -> dict:
    """
    Compute sales distribution by store, cache it under the scope's key, and
    return it. Shared by the route (on cache miss) and the cache warmer.

    Filters by tenant_id at the APP layer (defense in depth) so it is correct
    even on the owner/superuser session the cache warmer uses, which bypasses RLS.
    """
    query = select(
        Sale.store_id,
        Store.name.label('store_name'),
        func.sum(Sale.sales * Item.unit_price_aed).label('total_sales')
    ).join(
        Store, Sale.store_id == Store.id
    ).join(
        Item, Sale.item_id == Item.id
    ).where(Sale.tenant_id == tenant_id)

    if allowed_stores:
        query = query.where(Sale.store_id.in_(allowed_stores))

    query = query.group_by(
        Sale.store_id, Store.name
    ).order_by(func.sum(Sale.sales * Item.unit_price_aed).desc())

    result = await db.execute(query)
    rows = result.fetchall()

    total = float(sum(row.total_sales for row in rows))

    store_data = []
    for row in rows:
        store_data.append({
            "store_id": row.store_id,
            "store_name": row.store_name,
            "total_revenue": float(row.total_sales),
            "percentage": round((float(row.total_sales) / total * 100) if total > 0 else 0, 2)
        })

    response = {"data": store_data, "total": total}
    await set_cached(store_distribution_cache_key(allowed_stores, tenant_id), response, CACHE_TTL['analytics'])
    return response


# =============================================================================
# Forecast Lab (model metrics) — shared by the routes and the forecast trainer
# =============================================================================

# Forecast Lab payload is served stale-but-warm: the trainer refreshes it well
# within this TTL (see services/forecast_trainer.py), so it never expires under it.
MODEL_METRICS_TTL = 6 * 3600

# Cross-worker guard so concurrent cold requests don't each spawn a duplicate
# (expensive) background training task. A Redis SET NX lease, not an in-process
# set: under `gunicorn --workers N` an in-process set would let N workers train
# the same scope N times. Fails OPEN (a Redis blip just permits a duplicate warm —
# the output is idempotent, so this is waste, never wrong).
_INFLIGHT_METRICS_TTL = 15 * 60  # a warm should finish well within this; auto-frees on crash


def _inflight_key(cache_key: str) -> str:
    return f"analytics:warming:{cache_key}"


async def _try_claim_metrics_warm(cache_key: str) -> bool:
    """True if THIS worker should run the warm; False if another already is."""
    from app.services import redis_client as _redis
    client = _redis.redis_client
    if client is None:
        return True  # no Redis => no cross-worker coordination; proceed (idempotent)
    try:
        got = await client.set(_inflight_key(cache_key), "1", nx=True, ex=_INFLIGHT_METRICS_TTL)
        return bool(got)
    except Exception:
        return True  # fail open


async def _release_metrics_warm(cache_key: str) -> None:
    from app.services import redis_client as _redis
    client = _redis.redis_client
    if client is None:
        return
    try:
        await client.delete(_inflight_key(cache_key))
    except Exception:
        pass


def _empty_model_metrics(status: str = "ready") -> dict:
    return {
        "accuracy": None, "selected_model": None, "mape": None, "leaderboard": [],
        "forecast": [], "backtest": [], "interval_pct": None, "accuracy_trend": [],
        "feature_importance": [], "classifier": {}, "heatmap": [],
        "category_heatmap": [], "item_accuracy": [],
        "business_impact": {}, "status": status,
        # --- E7-1 Forecasting v2 fields (safe defaults; populated by
        # diagnostics.forecast_summary once history exists) ---
        "forecasting_version": "v2_uae_calendar",
        "baseline_model": "seasonal_naive",
        "baseline_mape": None, "baseline_wape": None,
        "selected_model_mape": None, "selected_model_wape": None,
        "wape_improvement_vs_baseline_pct": None,
        "ramadan_accuracy": None, "ramadan_mape": None, "ramadan_wape": None,
        "ramadan_eval_days": 0, "ramadan_accuracy_reason": "not_computed",
        "calendar_feature_summary": {
            "uses_uae_calendar": True, "uses_weather_features": False,
            "lunar_dates_approximate": True,
        },
        "methodology_note": (
            "Forecasts compare the selected model against a seasonal-naive baseline. "
            "UAE lunar dates are approximate until confirmed; weather features are "
            "neutral when unavailable; Ramadan accuracy is reported only when the "
            "backtest window contains Ramadan dates."
        ),
    }


def model_metrics_cache_key(tenant_id: int, allowed: Optional[List[int]], horizon: int) -> str:
    scope = "-".join(map(str, sorted(allowed))) if allowed else "all"
    return generate_cache_key(f"model_metrics_t{tenant_id}_{scope}_{horizon}")


def _compute_model_metrics_sync(
    hist_records: List[dict],
    store_records: List[dict],
    cat_records: List[dict],
    item_records: List[dict],
    avg_price: float,
    horizon: int,
) -> dict:
    """CPU-bound Forecast Lab computation (rolling-origin backtest + DL model
    selection, LightGBM feature importance, stockout classifier, business impact,
    accuracy heatmaps).

    Pure/synchronous and takes already-fetched plain-Python records so it can run
    in a worker thread via ``asyncio.to_thread`` — the numpy/pandas/sklearn/torch
    work releases the GIL, so the event loop stays free to serve requests instead
    of being starved by training (the old behaviour pinned all cores and made the
    API unresponsive).
    """
    import pandas as pd
    from app.services.forecasting import diagnostics as diag

    result = _empty_model_metrics("ready")
    if hist_records:
        hist = pd.DataFrame(hist_records)
        result.update(diag.forecast_summary(hist, horizon))
        result["accuracy_trend"] = diag.accuracy_over_time(
            hist, horizon, result.get("selected_model")
        )
        result["feature_importance"] = diag.feature_importance(hist)
        result["classifier"] = diag.stockout_classifier(hist)
        recent_daily = float(hist["sales"].tail(30).mean()) if len(hist) else 0.0
        result["business_impact"] = diag.business_impact(
            result.get("forecast", []), result.get("classifier", {}), avg_price, recent_daily
        )

    by_store: dict = {}
    for r in store_records:
        by_store.setdefault((r["store_id"], r["store_name"]), []).append(
            {"date": r["date"], "sales": r["sales"]}
        )
    result["heatmap"] = [
        {"store_id": sid, "store_name": sname,
         "accuracy": diag.classical_accuracy(pd.DataFrame(recs))}
        for (sid, sname), recs in list(by_store.items())[:12]
    ]

    result["category_heatmap"] = diag.accuracy_by_group(
        cat_records, ["store_id", "store_name", "category"]
    )
    result["item_accuracy"] = diag.accuracy_by_group(
        item_records, ["item_id", "item_name", "category"]
    )
    return result


async def compute_and_cache_model_metrics(
    db: AsyncSession,
    tenant_id: int = 1,
    allowed: Optional[List[int]] = None,
    horizon: int = 14,
) -> dict:
    """Heavy Forecast Lab computation for one tenant/scope/horizon: rolling-origin
    backtest + DL model selection, LightGBM feature importance, stockout-risk
    classifier, business impact, and per-store accuracy heatmap.

    This is the ONLY place forecast models are trained. It runs off the request
    path (background trainer + lazy background warm) and writes to the cache key
    the /model-metrics endpoint reads, so user requests never train a model.

    DB I/O happens on the event loop; the CPU-bound model work is offloaded to a
    worker thread (``_compute_model_metrics_sync``) so training never blocks the
    server.
    """
    where = ["s.tenant_id = :tenant_id"]
    params: dict = {"tenant_id": tenant_id}
    if allowed:
        where.append("s.store_id = ANY(:allowed)")
        params["allowed"] = allowed
    where_sql = " AND ".join(where)

    try:
        # --- All DB reads on the event loop; materialise to plain Python so the
        #     compute step can run in a thread without touching the session. ---
        agg_sql = (
            f"SELECT s.date AS date, SUM(s.sales) AS sales FROM sales_fact_view s "
            f"WHERE {where_sql} GROUP BY s.date ORDER BY s.date"
        )
        rows = (await db.execute(text(agg_sql), params)).fetchall()
        hist_records = [{"date": r.date, "sales": float(r.sales or 0)} for r in rows]

        avg_price = 0.0
        if rows:
            avg_price_row = (await db.execute(text("SELECT AVG(unit_price_aed) AS p FROM items"))).fetchone()
            avg_price = float(avg_price_row.p) if avg_price_row and avg_price_row.p else 0.0

        store_sql = (
            f"SELECT st.id AS store_id, st.name AS store_name, s.date AS date, "
            f"SUM(s.sales) AS sales FROM sales_fact_view s JOIN stores st ON st.id = s.store_id "
            f"WHERE {where_sql} GROUP BY st.id, st.name, s.date ORDER BY st.id, s.date"
        )
        srows = (await db.execute(text(store_sql), params)).fetchall()
        store_records = [
            {"store_id": r.store_id, "store_name": r.store_name,
             "date": r.date, "sales": float(r.sales or 0)}
            for r in srows
        ]

        # Store × category accuracy grid (the heatmap-depth view).
        cat_sql = (
            f"SELECT st.id AS store_id, st.name AS store_name, i.category AS category, "
            f"s.date AS date, SUM(s.sales) AS sales FROM sales_fact_view s "
            f"JOIN stores st ON st.id = s.store_id JOIN items i ON i.id = s.item_id "
            f"WHERE {where_sql} GROUP BY st.id, st.name, i.category, s.date "
            f"ORDER BY st.id, i.category, s.date"
        )
        cat_rows = (await db.execute(text(cat_sql), params)).fetchall()
        cat_records = [
            {"store_id": r.store_id, "store_name": r.store_name,
             "category": r.category, "date": r.date, "sales": r.sales}
            for r in cat_rows
        ]

        # Per-item accuracy (category → items drill-down, across the scoped stores).
        item_sql = (
            f"SELECT i.id AS item_id, i.name AS item_name, i.category AS category, "
            f"s.date AS date, SUM(s.sales) AS sales FROM sales_fact_view s "
            f"JOIN items i ON i.id = s.item_id "
            f"WHERE {where_sql} GROUP BY i.id, i.name, i.category, s.date "
            f"ORDER BY i.id, s.date"
        )
        item_rows = (await db.execute(text(item_sql), params)).fetchall()
        item_records = [
            {"item_id": r.item_id, "item_name": r.item_name,
             "category": r.category, "date": r.date, "sales": r.sales}
            for r in item_rows
        ]

        # --- CPU-bound model training/diagnostics off the event loop. ---
        result = await asyncio.to_thread(
            _compute_model_metrics_sync,
            hist_records, store_records, cat_records, item_records, avg_price, horizon,
        )
    except Exception as e:
        logger.error(f"Model metrics computation error: {e}")
        # Cache nothing on failure so the next cycle/request retries cleanly.
        return _empty_model_metrics("ready")

    result["status"] = "ready"
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    await set_cached(model_metrics_cache_key(tenant_id, allowed, horizon), result, MODEL_METRICS_TTL)
    return result


async def _warm_model_metrics_in_background(
    tenant_id: int, allowed: Optional[List[int]], horizon: int
) -> None:
    """Compute one scope's metrics off the request path, with its own DB session
    (the request's session is gone by the time this runs). Guarded so concurrent
    cold requests for the same scope don't trigger duplicate training."""
    cache_key = model_metrics_cache_key(tenant_id, allowed, horizon)
    if not await _try_claim_metrics_warm(cache_key):
        return  # another worker is already warming this scope
    try:
        from app.services.database import async_session
        async with async_session() as session:
            await compute_and_cache_model_metrics(session, tenant_id, allowed, horizon)
    except Exception as e:
        logger.warning(f"Background model-metrics warm failed: {e}")
    finally:
        await _release_metrics_warm(cache_key)
