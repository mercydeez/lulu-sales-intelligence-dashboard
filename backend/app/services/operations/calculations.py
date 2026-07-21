"""Operations Copilot — the deterministic calculators.

EVERY QUANTITY THE COPILOT PROPOSES IS COMPUTED HERE. No model, no heuristic
that cannot be written down, no I/O: these are pure functions over numbers the
read tools already fetched, which is what makes them unit-testable and what lets
the UI show a human exactly how a number was reached.

Each calculator returns its inputs and its assumptions alongside the answer. An
assumption is not decoration — "no supplier lead time on record, assuming 7 days"
is the difference between a defensible draft and a guess wearing a number.

Refusal is a first-class result. When velocity is too noisy to size an order, or
a transfer would put the source store at risk, the calculator returns
quantity=0 with a refusal_reason rather than a small number that looks decisive.

UNITS: stock and quantities are UNITS, velocity is UNITS PER DAY, cover is DAYS.
No currency enters these functions — the product convention is that volume
metrics never share an axis with value metrics.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.services.operations.policy import (
    OperationsPolicy,
    ReplenishmentSettings,
    TransferSettings,
)


class CalculationResult(BaseModel):
    """A quantity, why it is that quantity, and what we had to assume."""

    quantity: int = 0
    #: Human-readable inputs -> the UI renders these as "how we got here".
    inputs: Dict[str, Any] = Field(default_factory=dict)
    steps: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    #: Set when no defensible quantity exists. quantity is 0 whenever this is set.
    refusal_reason: Optional[str] = None

    @property
    def is_actionable(self) -> bool:
        return self.quantity > 0 and not self.refusal_reason


def days_of_cover(current_stock: float, daily_velocity: float) -> Optional[float]:
    """Days the current stock lasts at the observed rate.

    Returns None (not infinity, not zero) when velocity is zero: "how long will
    stock last for an item that isn't selling" has no useful numeric answer, and
    None forces callers to say so instead of printing a fake number.
    """
    if daily_velocity is None or daily_velocity <= 0:
        return None
    if current_stock is None or current_stock < 0:
        current_stock = 0
    return round(current_stock / daily_velocity, 2)


def _round_up_to_multiple(value: float, multiple: int) -> int:
    if multiple <= 1:
        return int(math.ceil(value))
    return int(math.ceil(value / multiple) * multiple)


def calculate_replenishment(
    *,
    current_stock: float,
    daily_velocity: float,
    settings: ReplenishmentSettings,
    lead_time_days: Optional[int] = None,
    reorder_point: Optional[float] = None,
    on_order_quantity: float = 0.0,
) -> CalculationResult:
    """How much to reorder, by the textbook order-up-to-level rule.

        target level = demand over (lead time + review period) + safety stock
        order        = target level - (on hand + already on order)

    `lead_time_days=None` means the item has no supplier lead time on record.
    That is not fatal, but it IS an assumption the approver must see, so it is
    recorded explicitly rather than silently defaulted.
    """
    assumptions: List[str] = []
    steps: List[str] = []

    if daily_velocity is None or daily_velocity < settings.min_daily_velocity:
        return CalculationResult(
            inputs={"current_stock": current_stock, "daily_velocity": daily_velocity,
                    "min_daily_velocity": settings.min_daily_velocity},
            refusal_reason=(
                f"observed velocity ({daily_velocity}) is below the minimum "
                f"({settings.min_daily_velocity}) needed to size an order defensibly"
            ),
        )

    if lead_time_days is None:
        lead_time_days = settings.default_lead_time_days
        assumptions.append(
            f"No supplier lead time on record for this item — assuming "
            f"{lead_time_days} days (tenant policy default)."
        )
    horizon_days = lead_time_days + settings.review_period_days
    expected_demand = daily_velocity * horizon_days
    safety_stock = daily_velocity * settings.safety_stock_days
    target_level = expected_demand + safety_stock
    available = (current_stock or 0) + (on_order_quantity or 0)
    raw_order = target_level - available

    steps.append(
        f"Expected demand over {horizon_days} days "
        f"({lead_time_days}d lead time + {settings.review_period_days}d review) "
        f"= {daily_velocity} units/day x {horizon_days} = {round(expected_demand, 2)} units"
    )
    steps.append(
        f"Safety stock = {daily_velocity} units/day x {settings.safety_stock_days} days "
        f"= {round(safety_stock, 2)} units"
    )
    steps.append(
        f"Order-up-to level = {round(target_level, 2)} units; "
        f"on hand {current_stock} + on order {on_order_quantity} = {available} units"
    )

    if on_order_quantity == 0:
        assumptions.append(
            "No open purchase orders were counted — this draft assumes nothing is "
            "already inbound for this store/item."
        )
    if reorder_point is not None:
        steps.append(f"Store's configured reorder point is {reorder_point} units (context only).")

    if raw_order <= 0:
        return CalculationResult(
            inputs={"current_stock": current_stock, "daily_velocity": daily_velocity,
                    "lead_time_days": lead_time_days, "target_level": round(target_level, 2),
                    "on_order_quantity": on_order_quantity},
            steps=steps, assumptions=assumptions,
            refusal_reason=(
                "stock on hand already meets the order-up-to level — no replenishment "
                "is justified"
            ),
        )

    quantity = _round_up_to_multiple(raw_order, settings.round_to_multiple)
    quantity = max(quantity, settings.min_order_quantity)
    steps.append(
        f"Shortfall {round(raw_order, 2)} units, rounded up to a multiple of "
        f"{settings.round_to_multiple} = {quantity} units"
    )

    if quantity > settings.max_order_quantity:
        return CalculationResult(
            quantity=0,
            inputs={"current_stock": current_stock, "daily_velocity": daily_velocity,
                    "lead_time_days": lead_time_days, "uncapped_quantity": quantity,
                    "max_order_quantity": settings.max_order_quantity},
            steps=steps, assumptions=assumptions,
            refusal_reason=(
                f"calculated quantity ({quantity} units) exceeds the tenant maximum "
                f"({settings.max_order_quantity}) — this needs a human buyer, not a draft"
            ),
        )

    return CalculationResult(
        quantity=quantity,
        inputs={
            "current_stock": current_stock,
            "daily_velocity": daily_velocity,
            "lead_time_days": lead_time_days,
            "review_period_days": settings.review_period_days,
            "safety_stock_days": settings.safety_stock_days,
            "expected_demand": round(expected_demand, 2),
            "safety_stock": round(safety_stock, 2),
            "target_level": round(target_level, 2),
            "on_order_quantity": on_order_quantity,
            "days_of_cover_before": days_of_cover(current_stock, daily_velocity),
        },
        steps=steps,
        assumptions=assumptions,
    )


def calculate_transfer(
    *,
    source_stock: float,
    source_velocity: float,
    destination_stock: float,
    destination_velocity: float,
    settings: TransferSettings,
    target_days_cover: Optional[int] = None,
) -> CalculationResult:
    """How much stock may move from a surplus store to a store at risk.

    THE SOURCE IS PROTECTED FIRST. A transfer that fixes one stockout by causing
    another is not a fix, so the quantity is the smallest of:
      - what the destination actually needs to reach its target cover,
      - what the source can spare while retaining its own minimum days of cover,
      - a hard share-of-on-hand cap, and the tenant's absolute maximum.
    """
    assumptions: List[str] = []
    steps: List[str] = []
    target_days_cover = target_days_cover or settings.source_min_days_cover

    if destination_velocity is None or destination_velocity <= 0:
        return CalculationResult(
            inputs={"destination_velocity": destination_velocity},
            refusal_reason=(
                "destination store shows no sales velocity for this item — a transfer "
                "cannot be justified as demand relief"
            ),
        )

    destination_need = max(
        0.0, destination_velocity * target_days_cover - (destination_stock or 0))
    steps.append(
        f"Destination needs {destination_velocity} units/day x {target_days_cover} days "
        f"= {round(destination_velocity * target_days_cover, 2)} units of cover, "
        f"has {destination_stock} -> shortfall {round(destination_need, 2)} units"
    )

    if source_velocity is None or source_velocity <= 0:
        # A source that isn't selling can spare everything above zero, but that is
        # an assumption worth stating rather than a fact worth hiding.
        source_reserve = 0.0
        assumptions.append(
            "Source store shows no sales velocity for this item, so its entire "
            "on-hand quantity is treated as spare."
        )
    else:
        source_reserve = source_velocity * settings.source_min_days_cover
    source_spare = max(0.0, (source_stock or 0) - source_reserve)
    steps.append(
        f"Source must retain {settings.source_min_days_cover} days of cover "
        f"= {round(source_reserve, 2)} units; has {source_stock} "
        f"-> can spare {round(source_spare, 2)} units"
    )

    share_cap = (source_stock or 0) * settings.max_share_of_source
    steps.append(
        f"Share cap: at most {settings.max_share_of_source:.0%} of the source's "
        f"{source_stock} units = {round(share_cap, 2)} units"
    )

    quantity = int(math.floor(min(
        destination_need, source_spare, share_cap, float(settings.max_transfer_quantity))))

    inputs = {
        "source_stock": source_stock,
        "source_velocity": source_velocity,
        "destination_stock": destination_stock,
        "destination_velocity": destination_velocity,
        "destination_need": round(destination_need, 2),
        "source_spare": round(source_spare, 2),
        "share_cap": round(share_cap, 2),
        "source_min_days_cover": settings.source_min_days_cover,
        "source_days_of_cover_before": days_of_cover(source_stock, source_velocity),
        "destination_days_of_cover_before": days_of_cover(destination_stock,
                                                          destination_velocity),
    }

    if quantity < settings.min_transfer_quantity:
        binding = "the source has nothing to spare without dropping below its own " \
                  "minimum cover" if source_spare < destination_need else \
                  "the destination's shortfall is too small to justify a movement"
        return CalculationResult(
            inputs=inputs, steps=steps, assumptions=assumptions,
            refusal_reason=f"no safe transfer quantity — {binding}",
        )

    steps.append(f"Transfer quantity = min(need, spare, share cap, max) = {quantity} units")
    inputs["source_days_of_cover_after"] = days_of_cover(
        (source_stock or 0) - quantity, source_velocity)
    inputs["destination_days_of_cover_after"] = days_of_cover(
        (destination_stock or 0) + quantity, destination_velocity)

    return CalculationResult(quantity=quantity, inputs=inputs, steps=steps,
                            assumptions=assumptions)


class MeasurementBaseline(BaseModel):
    """What we will compare against after the action, fixed BEFORE approval."""

    metric_name: str
    baseline_value: Optional[float] = None
    unit: str
    window_days: int
    success_criterion: str


def calculate_measurement_baseline(
    *, action_type: str, policy: OperationsPolicy,
    current_stock: Optional[float] = None,
    daily_velocity: Optional[float] = None,
    finding_metric_value: Optional[float] = None,
    finding_rule: Optional[str] = None,
) -> MeasurementBaseline:
    """Pick the metric that will decide whether the action worked.

    For stock actions that is days of cover, which is what the action directly
    moves. For an investigation it is the finding's own headline metric, so the
    outcome is judged by the same number that raised the alarm — and by the same
    worker measure job that already closes that loop.
    """
    window = policy.measurement_window_days

    if action_type in ("replenishment_draft", "stock_transfer_draft"):
        baseline = days_of_cover(current_stock or 0, daily_velocity or 0)
        return MeasurementBaseline(
            metric_name="days_of_cover",
            baseline_value=baseline,
            unit="days",
            window_days=window,
            success_criterion=(
                "days of cover rises above the store's reorder point and the item is "
                "not out of stock at the end of the window"
                if baseline is not None else
                "item is in stock at the end of the window (no baseline cover was "
                "derivable — velocity was zero)"
            ),
        )

    return MeasurementBaseline(
        metric_name=finding_rule or "finding_metric",
        baseline_value=finding_metric_value,
        unit="pct" if (finding_rule or "").endswith(("_drop", "_slump", "_spike")) else "units",
        window_days=window,
        success_criterion=(
            "the diagnostic rule that raised this finding no longer fires when "
            "re-evaluated at the end of the measurement window"
        ),
    )
