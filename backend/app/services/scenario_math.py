"""
Phase 1 GATE — scenario mathematics (board pack v3, p.7/p.9/p.10/p.14).

Replaces the fixed ±40% uncertainty band with honest uncertainty:

  * QUANTILE BASE DEMAND — empirical P10/P50/P90 of the SKU-store daily demand
    distribution (board pack p.7: "Produces P10 / P50 / P90 rather than one
    number"). Deliberately EMPIRICAL, not LightGBM-quantile: the board pack is
    explicit that algorithm names are recommendations to benchmark, and a
    trained quantile model is only justified once it beats this baseline on
    Retail IQ data. The interface below is the seam a LGBMRegressor(objective=
    'quantile') drops into unchanged.

  * MONTE CARLO — propagates uncertainty in base demand, offer response,
    returns and expiry through to profit and cash (p.10), producing a
    distribution rather than a single promise.

  * CVaR / cash-at-risk — mean of the worst tail (p.9: "PROFIT != CASH SAFETY",
    "Shows expected result and tail loss, not only average profit").

  * INTERMITTENT DEMAND — Croston-style guard (p.7): when most periods have zero
    demand, a normal high-volume model is not forced onto a sparse item; the
    series is flagged so the caller degrades honestly.

Deterministic: every run seeds its RNG from (tenant, campaign, depth) so a
board decision reproduces exactly from stored inputs. Money is Decimal at the
boundaries; the simulation core works in float and quantises on the way out.
"""
from __future__ import annotations

import hashlib
import random
import statistics
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Sequence

CENT = Decimal("0.01")
DEFAULT_TRIALS = 2000
# A series with this share of zero-demand periods is "intermittent" (Croston
# territory) — a smooth quantile model would be misleading.
INTERMITTENT_ZERO_SHARE = 0.35


def _q(x) -> Decimal:
    return Decimal(str(x)).quantize(CENT, ROUND_HALF_UP)


def _seed(*parts) -> int:
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:8], 16)


# ---------------------------------------------------------------------------
# Quantile base demand
# ---------------------------------------------------------------------------

def empirical_quantiles(values: Sequence[float],
                        probs: Sequence[float] = (0.10, 0.50, 0.90)) -> Dict[str, float]:
    """Linear-interpolated empirical quantiles. No numpy dependency needed."""
    if not values:
        return {f"p{int(p*100)}": 0.0 for p in probs}
    s = sorted(float(v) for v in values)
    out = {}
    for p in probs:
        if len(s) == 1:
            out[f"p{int(p*100)}"] = s[0]
            continue
        pos = p * (len(s) - 1)
        lo = int(pos)
        hi = min(lo + 1, len(s) - 1)
        frac = pos - lo
        out[f"p{int(p*100)}"] = s[lo] + frac * (s[hi] - s[lo])
    return out


def base_demand_quantiles(daily_units: Sequence[float], horizon_days: int) -> Dict:
    """P10/P50/P90 base demand over the horizon from the daily demand series.

    Scaling daily quantiles by horizon would overstate spread (day-to-day noise
    partially cancels over a horizon), so the spread is scaled by sqrt(n) around
    the median — the standard variance-of-a-sum correction.
    """
    series = [float(v) for v in daily_units]
    n = max(1, int(horizon_days))
    if not series:
        return {"p10": 0, "p50": 0, "p90": 0, "daily_p50": 0.0,
                "status": "no_history", "intermittent": False, "method": "none"}

    zero_share = sum(1 for v in series if v <= 0) / len(series)
    intermittent = zero_share >= INTERMITTENT_ZERO_SHARE
    qs = empirical_quantiles(series)
    med, p10, p90 = qs["p50"], qs["p10"], qs["p90"]

    centre = med * n
    scale = n ** 0.5
    low = max(0.0, centre - (med - p10) * scale)
    high = centre + (p90 - med) * scale
    return {
        "p10": int(round(low)),
        "p50": int(round(centre)),
        "p90": int(round(high)),
        "daily_p50": round(med, 3),
        "observations": len(series),
        "zero_share": round(zero_share, 3),
        "intermittent": intermittent,
        # Board-pack p.7: sparse items must not be modelled as smooth demand.
        "status": "intermittent_low_confidence" if intermittent else "ready",
        "method": "empirical_quantile_sqrt_horizon",
    }


# ---------------------------------------------------------------------------
# Monte Carlo scenario simulation
# ---------------------------------------------------------------------------

def monte_carlo(*, base_p10: float, base_p50: float, base_p90: float,
                lift_fraction: float, contacted: int, response_prob: float,
                price: Decimal, cost: Optional[Decimal], discount_pct: Decimal,
                supply_units: int, units_expiring: int,
                fixed_cost: Decimal, salvage_frac: Decimal = Decimal("0.20"),
                return_rate: float = 0.03, trials: int = DEFAULT_TRIALS,
                seed: int = 0) -> Dict:
    """Propagate demand, response, returns and expiry uncertainty into a profit
    and units distribution. Returns P10/P50/P90, mean, CVaR@5% and risk rates."""
    rng = random.Random(seed)
    p = float(price)
    c = float(cost) if cost is not None else None
    d = float(discount_pct) / 100.0
    salv = float(salvage_frac)
    fixed = float(fixed_cost)

    # Triangular base-demand draw from the quantile band (lo, mode, hi).
    lo, mode, hi = float(base_p10), float(base_p50), float(base_p90)
    if not (lo <= mode <= hi):
        lo, mode, hi = min(lo, mode, hi), mode, max(lo, mode, hi)
    if hi <= lo:
        hi = lo + 1e-9

    profits: List[float] = []
    sold_units: List[float] = []
    stockouts = 0
    leftovers: List[float] = []
    expiry_losses: List[float] = []

    for _ in range(max(1, trials)):
        base = rng.triangular(lo, hi, mode)
        # Response uncertainty: redemptions ~ Binomial-ish via normal approx of
        # the contacted population, floored at zero.
        eff_resp = max(0.0, rng.gauss(response_prob, response_prob * 0.35))
        promo_units = base * lift_fraction * (eff_resp / response_prob if response_prob > 0 else 0.0)
        demand = max(0.0, base + promo_units)

        sold = min(demand, float(supply_units))
        if demand > supply_units:
            stockouts += 1
        returned = sold * max(0.0, rng.gauss(return_rate, return_rate * 0.5))
        net_sold = max(0.0, sold - returned)

        incremental = max(0.0, net_sold - base)
        if c is None:
            margin = 0.0
        else:
            margin = incremental * (p * (1 - d) - c)

        leftover = max(0.0, supply_units - demand)
        expiring_unsold = min(float(units_expiring), leftover)
        expiry_loss = expiring_unsold * ((c if c is not None else 0.0) * (1 - salv))

        profit = margin - fixed - expiry_loss
        profits.append(profit)
        sold_units.append(net_sold)
        leftovers.append(leftover)
        expiry_losses.append(expiry_loss)

    profits_sorted = sorted(profits)
    pq = empirical_quantiles(profits_sorted)
    uq = empirical_quantiles(sold_units)
    # CVaR@5%: mean of the worst 5% of outcomes (tail loss, not just a quantile).
    tail_n = max(1, int(len(profits_sorted) * 0.05))
    cvar = sum(profits_sorted[:tail_n]) / tail_n

    return {
        "trials": len(profits),
        "profit_p10_aed": str(_q(pq["p10"])),
        "profit_p50_aed": str(_q(pq["p50"])),
        "profit_p90_aed": str(_q(pq["p90"])),
        "profit_mean_aed": str(_q(statistics.fmean(profits))),
        "cvar_5pct_aed": str(_q(cvar)),
        "loss_probability": round(sum(1 for x in profits if x < 0) / len(profits), 3),
        "units_sold_p10": int(round(uq["p10"])),
        "units_sold_p50": int(round(uq["p50"])),
        "units_sold_p90": int(round(uq["p90"])),
        "stockout_probability": round(stockouts / len(profits), 3),
        "expected_leftover_units": int(round(statistics.fmean(leftovers))),
        "expected_expiry_loss_aed": str(_q(statistics.fmean(expiry_losses))),
        "method": "monte_carlo_triangular_demand",
    }


def cash_at_risk(mc: Dict, committed_cash: Decimal) -> Dict:
    """Board-pack p.9 finance view: tail loss plus any irreversible cash out."""
    cvar = Decimal(mc["cvar_5pct_aed"])
    return {
        "cvar_5pct_aed": str(_q(cvar)),
        "committed_cash_aed": str(_q(committed_cash)),
        # Worst credible cash exposure: tail loss plus cash already committed.
        "cash_at_risk_aed": str(_q(min(cvar, Decimal("0")) - committed_cash)),
        "loss_probability": mc["loss_probability"],
    }
