"""
Deterministic root-cause decomposition (E7-4) — the "Diagnose" foundation.

Answers "why did revenue / units / returns change?" by decomposing the delta
between a current period and a comparison period across store / category / item /
day, and attributing each contributor's SHARE of the total change. No LLM, no
heuristics — pure SQL aggregation over the canonical E6-1 view `metric_sales_fact`,
so every number is derivable and matches what kpis.py / the worker report.

Design notes
------------
* Reads ONLY `metric_sales_fact` (+ tenant-matched joins to stores/items for
  labels). Never re-derives revenue math; `revenue_aed = units * unit_price_aed`
  is defined once in the view.
* All four metrics come from the same fact (returns are rows where units < 0),
  so E7-4 needs no new migration.
* SQL is parameterised; the ONLY interpolated fragments are whitelisted metric
  expressions and dimension key/label/join strings (never user input).
* Tenant safety: every query filters `tenant_id` and every label join is
  tenant-matched; store scope narrows further, exactly like kpis.py.

Units vs AED convention (see CLAUDE.md / kpis.py): VOLUME metrics are units,
VALUE metrics are AED. Field names are explicit: `revenue_aed`, `units_sold`,
`return_units`, `return_value_aed`, `delta`, `delta_pct`, `share_of_change_pct`.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Union

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import logger

# --- Whitelists (safe SQL fragments — NOT user input) -----------------------

# metric -> (SQL expression over metric_sales_fact alias `f`, value kind)
METRIC_EXPR = {
    "revenue_aed": ("f.revenue_aed", "aed"),
    "units_sold": ("f.units", "units"),
    # returns are rows with units < 0; expose them as POSITIVE magnitudes.
    "return_units": ("CASE WHEN f.units < 0 THEN -f.units ELSE 0 END", "units"),
    "return_value_aed": ("CASE WHEN f.units < 0 THEN -f.revenue_aed ELSE 0 END", "aed"),
}
DEFAULT_METRIC = "revenue_aed"

# dimension -> how to group + label it (label joins are tenant-matched)
DIMENSION_SQL = {
    "store": {
        "key": "f.store_id",
        "label": "COALESCE(st.name, f.store_id::text)",
        "join": "LEFT JOIN stores st ON st.id = f.store_id AND st.tenant_id = f.tenant_id",
        "id_is_int": True,
    },
    "category": {
        "key": "f.category",
        "label": "COALESCE(f.category, 'Uncategorized')",
        "join": "",
        "id_is_int": False,
    },
    "item": {
        "key": "f.item_id",
        "label": "COALESCE(i.name, f.item_id::text)",
        "join": "LEFT JOIN items i ON i.id = f.item_id AND i.tenant_id = f.tenant_id",
        "id_is_int": True,
    },
    "day": {
        "key": "f.date",
        "label": "f.date::text",
        "join": "",
        "id_is_int": False,
    },
}
DEFAULT_DIMENSIONS = ["store", "category", "item", "day"]

ALLOWED_COMPARISONS = ("previous_period", "previous_week", "previous_year")
DEFAULT_COMPARISON = "previous_period"

DEFAULT_LIMIT = 10
MAX_LIMIT = 50
MAX_RANGE_DAYS = 366


# --- Response models --------------------------------------------------------

class PeriodValue(BaseModel):
    start_date: str
    end_date: str
    value: float


class DeltaBlock(BaseModel):
    absolute: float
    percent: Optional[float] = None  # None when comparison base is 0 (no div-by-zero)


class Contributor(BaseModel):
    id: Optional[Union[int, str]] = None
    name: str
    current_value: float
    comparison_value: float
    delta: float
    delta_pct: Optional[float] = None
    share_of_change_pct: Optional[float] = None


class RootCauseResult(BaseModel):
    metric: str
    current_period: PeriodValue
    comparison_period: PeriodValue
    delta: DeltaBlock
    contributors: dict  # dimension -> List[Contributor]
    metadata: dict


# --- Pure helpers (unit-testable without a DB) ------------------------------

class ValidationError(ValueError):
    """Raised for bad request parameters; the route maps this to HTTP 400."""


def _shift_years(d: date, years: int) -> date:
    """Shift a date back by whole years, leap-safe (Feb 29 -> Feb 28)."""
    try:
        return d.replace(year=d.year - years)
    except ValueError:
        # Only Feb 29 on a non-leap target year lands here.
        return d.replace(year=d.year - years, day=28)


def resolve_comparison_period(
    start: date,
    end: date,
    comparison: str,
    compare_start: Optional[date],
    compare_end: Optional[date],
) -> tuple[date, date]:
    """Return the (start, end) of the comparison window.

    Explicit compare_start/compare_end win. Otherwise:
      previous_period: the immediately-preceding window of equal length.
      previous_week:   both bounds shifted back 7 days.
      previous_year:   both bounds shifted back 1 year (leap-safe).
    """
    if compare_start is not None or compare_end is not None:
        if compare_start is None or compare_end is None:
            raise ValidationError("compare_start_date and compare_end_date must be provided together")
        if compare_start > compare_end:
            raise ValidationError("compare_start_date must be on or before compare_end_date")
        if (compare_end - compare_start).days + 1 > MAX_RANGE_DAYS:
            raise ValidationError(f"comparison range exceeds the {MAX_RANGE_DAYS}-day maximum")
        return compare_start, compare_end

    duration_days = (end - start).days + 1  # inclusive
    if comparison == "previous_period":
        cmp_end = start - timedelta(days=1)
        cmp_start = cmp_end - timedelta(days=duration_days - 1)
        return cmp_start, cmp_end
    if comparison == "previous_week":
        return start - timedelta(days=7), end - timedelta(days=7)
    if comparison == "previous_year":
        return _shift_years(start, 1), _shift_years(end, 1)
    raise ValidationError(f"invalid comparison '{comparison}'")


def validate_params(
    metric: Optional[str],
    start: date,
    end: date,
    comparison: Optional[str],
    dimensions: Optional[str],
    limit: Optional[int],
) -> dict:
    """Validate + normalise request params. Raises ValidationError (=> HTTP 400)."""
    metric_n = (metric or DEFAULT_METRIC).strip().lower()
    if metric_n not in METRIC_EXPR:
        raise ValidationError(
            f"invalid metric '{metric}'; allowed: {', '.join(sorted(METRIC_EXPR))}"
        )

    comparison_n = (comparison or DEFAULT_COMPARISON).strip().lower()
    if comparison_n not in ALLOWED_COMPARISONS:
        raise ValidationError(
            f"invalid comparison '{comparison}'; allowed: {', '.join(ALLOWED_COMPARISONS)}"
        )

    if dimensions is None or not dimensions.strip():
        dims = list(DEFAULT_DIMENSIONS)
    else:
        dims = [d.strip().lower() for d in dimensions.split(",") if d.strip()]
        bad = [d for d in dims if d not in DIMENSION_SQL]
        if bad:
            raise ValidationError(
                f"invalid dimension(s) {bad}; allowed: {', '.join(DIMENSION_SQL)}"
            )
        # de-dup while preserving order
        seen: set[str] = set()
        dims = [d for d in dims if not (d in seen or seen.add(d))]
        if not dims:
            dims = list(DEFAULT_DIMENSIONS)

    if start > end:
        raise ValidationError("start_date must be on or before end_date")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise ValidationError(f"date range exceeds the {MAX_RANGE_DAYS}-day maximum")

    lim = DEFAULT_LIMIT if limit is None else int(limit)
    if lim < 1:
        raise ValidationError("limit must be >= 1")
    lim = min(lim, MAX_LIMIT)

    return {"metric": metric_n, "comparison": comparison_n, "dimensions": dims, "limit": lim}


def safe_pct(delta: float, base: float) -> Optional[float]:
    """delta / base as a percentage, or None when base is 0 (no div-by-zero)."""
    if base == 0:
        return None
    return round(delta / abs(base) * 100.0, 2)


def share_of_change(delta: float, total_delta: float) -> Optional[float]:
    """A contributor's signed share of the total change, or None when total is 0."""
    if total_delta == 0:
        return None
    return round(delta / total_delta * 100.0, 2)


def _round_value(value: float, kind: str) -> float:
    return round(float(value), 2) if kind == "aed" else float(round(float(value)))


# --- Core decomposition -----------------------------------------------------

def _scope_clauses(allowed_stores: Optional[List[int]], store_id: Optional[int], category: Optional[str]) -> tuple[str, dict]:
    """Build tenant/store/optional-filter WHERE fragments + their bound params."""
    clauses = ""
    params: dict = {}
    if allowed_stores:
        clauses += " AND f.store_id = ANY(:allowed_stores)"
        params["allowed_stores"] = allowed_stores
    if store_id is not None:
        clauses += " AND f.store_id = :store_id"
        params["store_id"] = store_id
    if category is not None:
        clauses += " AND f.category = :category"
        params["category"] = category
    return clauses, params


async def _totals(db: AsyncSession, expr: str, base_params: dict, scope: str) -> tuple[float, float]:
    sql = text(f"""
        SELECT
            COALESCE(SUM({expr}) FILTER (WHERE f.date BETWEEN :cur_start AND :cur_end), 0) AS current_total,
            COALESCE(SUM({expr}) FILTER (WHERE f.date BETWEEN :cmp_start AND :cmp_end), 0) AS comparison_total
        FROM metric_sales_fact f
        WHERE f.tenant_id = :tenant_id
          AND (f.date BETWEEN :cur_start AND :cur_end OR f.date BETWEEN :cmp_start AND :cmp_end)
          {scope}
    """)
    row = (await db.execute(sql, base_params)).fetchone()
    return float(row.current_total or 0), float(row.comparison_total or 0)


async def _dimension_contributors(
    db: AsyncSession,
    dim: str,
    expr: str,
    kind: str,
    base_params: dict,
    scope: str,
    total_delta: float,
    limit: int,
    min_abs_delta: Optional[float],
) -> List[Contributor]:
    d = DIMENSION_SQL[dim]
    sql = text(f"""
        SELECT
            {d['key']}   AS group_key,
            {d['label']} AS group_label,
            COALESCE(SUM({expr}) FILTER (WHERE f.date BETWEEN :cur_start AND :cur_end), 0) AS current_value,
            COALESCE(SUM({expr}) FILTER (WHERE f.date BETWEEN :cmp_start AND :cmp_end), 0) AS comparison_value
        FROM metric_sales_fact f
        {d['join']}
        WHERE f.tenant_id = :tenant_id
          AND (f.date BETWEEN :cur_start AND :cur_end OR f.date BETWEEN :cmp_start AND :cmp_end)
          {scope}
        GROUP BY {d['key']}, {d['label']}
    """)
    rows = (await db.execute(sql, base_params)).fetchall()

    contributors: List[Contributor] = []
    for r in rows:
        current = float(r.current_value or 0)
        comparison = float(r.comparison_value or 0)
        delta = current - comparison
        if current == 0 and comparison == 0:
            continue  # group active in neither window — not a contributor
        if min_abs_delta is not None and abs(delta) < min_abs_delta:
            continue
        gid: Optional[Union[int, str]]
        if r.group_key is None:
            gid = None
        elif d["id_is_int"]:
            gid = int(r.group_key)
        else:
            gid = str(r.group_key)
        contributors.append(Contributor(
            id=gid,
            name=str(r.group_label),
            current_value=_round_value(current, kind),
            comparison_value=_round_value(comparison, kind),
            delta=_round_value(delta, kind),
            delta_pct=safe_pct(delta, comparison),
            share_of_change_pct=share_of_change(delta, total_delta),
        ))

    # Primary drivers first: largest absolute movement at the top.
    contributors.sort(key=lambda c: abs(c.delta), reverse=True)
    return contributors[:limit]


async def decompose(
    db: AsyncSession,
    tenant_id: int,
    allowed_stores: Optional[List[int]],
    *,
    metric: str,
    start_date: date,
    end_date: date,
    comparison: str,
    dimensions: List[str],
    limit: int,
    compare_start_date: Optional[date] = None,
    compare_end_date: Optional[date] = None,
    store_id: Optional[int] = None,
    category: Optional[str] = None,
    min_abs_delta: Optional[float] = None,
) -> RootCauseResult:
    """Run the decomposition. Params are assumed already validated by validate_params
    + resolve_comparison_period (the route does that). Tenant-scoped throughout."""
    cmp_start, cmp_end = resolve_comparison_period(
        start_date, end_date, comparison, compare_start_date, compare_end_date
    )
    expr, kind = METRIC_EXPR[metric]

    scope, scope_params = _scope_clauses(allowed_stores, store_id, category)
    base_params = {
        "tenant_id": tenant_id,
        "cur_start": start_date,
        "cur_end": end_date,
        "cmp_start": cmp_start,
        "cmp_end": cmp_end,
        **scope_params,
    }

    current_total, comparison_total = await _totals(db, expr, base_params, scope)
    total_delta = current_total - comparison_total

    contributors: dict = {}
    for dim in dimensions:
        contributors[dim] = await _dimension_contributors(
            db, dim, expr, kind, base_params, scope, total_delta, limit, min_abs_delta
        )

    return RootCauseResult(
        metric=metric,
        current_period=PeriodValue(
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            value=_round_value(current_total, kind),
        ),
        comparison_period=PeriodValue(
            start_date=cmp_start.isoformat(),
            end_date=cmp_end.isoformat(),
            value=_round_value(comparison_total, kind),
        ),
        delta=DeltaBlock(
            absolute=_round_value(total_delta, kind),
            percent=safe_pct(total_delta, comparison_total),
        ),
        contributors=contributors,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "comparison_mode": (
                "explicit" if (compare_start_date or compare_end_date) else comparison
            ),
            "dimensions": dimensions,
            "limit": limit,
            "min_abs_delta": min_abs_delta,
            "value_kind": kind,
            "data_source": "metric_sales_fact",
        },
    )
