"""Shared vocabulary for Flywheel: enums, money helpers, decision dataclasses.

MONEY POLICY (non-negotiable, §4 of the brief): every monetary value in this
package is a `Decimal`. Floats are permitted ONLY for probabilities and model
scores, which are not money and are never summed into a balance. `money()` is
the single conversion point — use it at every boundary where a float or string
could sneak into a financial path.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Dict, List, Optional

# AED is minor-unit-2. Every persisted amount is quantized to fils so a Decimal
# never carries phantom precision into a NUMERIC(16,2) column.
FILS = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value: Any) -> Decimal:
    """Coerce anything to a 2dp Decimal. The ONLY sanctioned float→money door.

    Floats are converted via `str` on purpose: `Decimal(0.1)` yields
    0.1000000000000000055511151231257827, while `Decimal(str(0.1))` yields
    exactly 0.1. In a ledger that difference compounds.
    """
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value.quantize(FILS, rounding=ROUND_HALF_UP)
    return Decimal(str(value)).quantize(FILS, rounding=ROUND_HALF_UP)


def money4(value: Any) -> Decimal:
    """4dp variant for unit price/cost columns (NUMERIC(12,4))."""
    if value is None:
        return Decimal("0.0000")
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Enums — mirror the CHECK constraints in migration 075 exactly.
# ---------------------------------------------------------------------------

class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    AUDIENCE_READY = "AUDIENCE_READY"
    SIMULATED = "SIMULATED"
    PENDING_INVENTORY_REVIEW = "PENDING_INVENTORY_REVIEW"
    PENDING_PROCUREMENT_REVIEW = "PENDING_PROCUREMENT_REVIEW"
    PENDING_FINANCE_APPROVAL = "PENDING_FINANCE_APPROVAL"
    PENDING_MARKETING_APPROVAL = "PENDING_MARKETING_APPROVAL"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    MEASURED = "MEASURED"


class ActionType(str, Enum):
    NO_ACTION = "NO_ACTION"
    REMINDER = "REMINDER"
    LOYALTY_POINTS = "LOYALTY_POINTS"
    FREE_DELIVERY = "FREE_DELIVERY"
    PERCENT_DISCOUNT = "PERCENT_DISCOUNT"
    FIXED_DISCOUNT = "FIXED_DISCOUNT"
    PRODUCT_BUNDLE = "PRODUCT_BUNDLE"
    SUBSTITUTE_PRODUCT = "SUBSTITUTE_PRODUCT"
    ALTERNATIVE_STORE = "ALTERNATIVE_STORE"
    HUMAN_REVIEW = "HUMAN_REVIEW"


#: Actions that consume physical stock. Everything else is a non-inventory
#: reward and therefore survives a stockout (rung (d) of the shortage ladder).
STOCK_CONSUMING_ACTIONS = frozenset({
    ActionType.PERCENT_DISCOUNT, ActionType.FIXED_DISCOUNT,
    ActionType.PRODUCT_BUNDLE, ActionType.SUBSTITUTE_PRODUCT,
})

#: Actions that draw on the DISCOUNT budget (vs LOYALTY_REWARD or free).
DISCOUNT_BUDGET_ACTIONS = frozenset({
    ActionType.PERCENT_DISCOUNT, ActionType.FIXED_DISCOUNT, ActionType.PRODUCT_BUNDLE,
})


class BudgetType(str, Enum):
    DISCOUNT = "DISCOUNT"
    MARKETING_MEDIA = "MARKETING_MEDIA"
    LOYALTY_REWARD = "LOYALTY_REWARD"
    PROCUREMENT = "PROCUREMENT"
    LOGISTICS = "LOGISTICS"
    CONTINGENCY = "CONTINGENCY"


class LedgerEntry(str, Enum):
    ALLOCATED = "ALLOCATED"
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    SPENT = "SPENT"
    RELEASED = "RELEASED"


class ReasonCode(str, Enum):
    """Why the optimizer chose — or refused — an action.

    These strings are persisted in `flywheel_decisions.reason_codes` /
    `rejected_actions` and rendered verbatim in the Decision Trace UI, so they
    are part of the product's contract with its user. Changing one is a
    user-visible change, not a refactor.
    """
    # Selection
    POSITIVE_EIV = "POSITIVE_EIV"
    HIGH_CHURN_RISK = "HIGH_CHURN_RISK"
    STRONG_UPLIFT = "STRONG_UPLIFT"
    CHEAPEST_EFFECTIVE_ACTION = "CHEAPEST_EFFECTIVE_ACTION"
    # Refusal
    NEGATIVE_EIV = "NEGATIVE_EIV"
    NEGATIVE_UPLIFT = "NEGATIVE_UPLIFT"
    UPLIFT_BELOW_THRESHOLD = "UPLIFT_BELOW_THRESHOLD"
    MARGIN_FLOOR_BREACHED = "MARGIN_FLOOR_BREACHED"
    DISCOUNT_CAP_EXCEEDED = "DISCOUNT_CAP_EXCEEDED"
    INSUFFICIENT_STOCK = "INSUFFICIENT_STOCK"
    INSUFFICIENT_BUDGET = "INSUFFICIENT_BUDGET"
    NO_CONSENT = "NO_CONSENT"
    #: The data subject exercised their PDPL right to object to automated
    #: profiling. A legal exclusion, not a commercial trade-off.
    PROFILING_OBJECTION = "PROFILING_OBJECTION"
    CONTACT_CAP_REACHED = "CONTACT_CAP_REACHED"
    CONTROL_GROUP = "CONTROL_GROUP"
    CAMPAIGN_NOT_ACTIVE = "CAMPAIGN_NOT_ACTIVE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    NO_PRICE_DATA = "NO_PRICE_DATA"
    PROCUREMENT_TOO_SLOW = "PROCUREMENT_TOO_SLOW"
    PROCUREMENT_UNECONOMIC = "PROCUREMENT_UNECONOMIC"
    STALE_DATA = "STALE_DATA"


class GuardrailBreach(str, Enum):
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    PROJECTED_BUDGET_EXCEEDED = "PROJECTED_BUDGET_EXCEEDED"
    SAFETY_STOCK_REACHED = "SAFETY_STOCK_REACHED"
    MARGIN_BELOW_FLOOR = "MARGIN_BELOW_FLOOR"
    REDEMPTION_ANOMALY = "REDEMPTION_ANOMALY"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    STALE_INVENTORY_DATA = "STALE_INVENTORY_DATA"


# ---------------------------------------------------------------------------
# Stable treatment/control assignment (§18)
# ---------------------------------------------------------------------------

def stable_hash(tenant_id: int, campaign_id: int, customer_id: int) -> int:
    """Deterministic 63-bit hash of (tenant, campaign, customer).

    Python's built-in `hash()` is salted per process (PYTHONHASHSEED), so it
    would reassign customers between treatment and control on every restart and
    silently destroy the experiment. BLAKE2b is stable across processes,
    machines and releases — the assignment is reproducible forever.
    """
    digest = hashlib.blake2b(
        f"{tenant_id}:{campaign_id}:{customer_id}".encode("utf-8"), digest_size=8
    ).digest()
    return int.from_bytes(digest, "big") & 0x7FFFFFFFFFFFFFFF


def is_control(tenant_id: int, campaign_id: int, customer_id: int,
               control_pct: Decimal) -> bool:
    """Assign to control iff the stable hash falls in the first control_pct%."""
    if control_pct <= 0:
        return False
    bucket = stable_hash(tenant_id, campaign_id, customer_id) % 10000
    return bucket < int(Decimal(str(control_pct)) * 100)


# ---------------------------------------------------------------------------
# Decision dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ActionCandidate:
    """One typed candidate the optimizer scores. Every monetary field is Decimal
    so the EIV sum below never mixes representations."""
    action_type: ActionType
    item_id: Optional[int] = None
    store_id: Optional[int] = None
    category: Optional[str] = None
    discount_pct: Decimal = ZERO
    unit_price_aed: Decimal = ZERO
    unit_cost_aed: Decimal = ZERO
    units: int = 1

    # Model-proposed probabilities (floats — not money).
    churn_probability: float = 0.0
    uplift: float = 0.0
    redemption_probability: float = 0.0

    # EIV terms, each kept separately so the total is independently checkable.
    expected_retained_value_aed: Decimal = ZERO
    expected_margin_aed: Decimal = ZERO
    expected_discount_cost_aed: Decimal = ZERO
    comms_cost_aed: Decimal = ZERO
    fulfilment_cost_aed: Decimal = ZERO
    procurement_cost_aed: Decimal = ZERO
    stockout_risk_penalty_aed: Decimal = ZERO

    # Tax-aware view of the sale. `net_price_aed` is what the business actually
    # keeps after remitting tax, and `margin_net_pct` is the figure the margin
    # floor is judged on — never the tax-inclusive one.
    net_price_aed: Decimal = ZERO
    margin_net_pct: Optional[Decimal] = None
    tax_rate_pct: Decimal = ZERO
    margin_note: Optional[str] = None

    reason_codes: List[str] = field(default_factory=list)
    rejected_reason: Optional[str] = None
    feasible: bool = True

    @property
    def eiv_aed(self) -> Decimal:
        """Expected incremental commercial value (§5).

        Benefits minus every cost the action causes. Computed as a property
        rather than a stored field so it can never drift out of sync with its
        terms — the stored column is written FROM this.
        """
        return money(
            self.expected_retained_value_aed
            + self.expected_margin_aed
            - self.expected_discount_cost_aed
            - self.comms_cost_aed
            - self.fulfilment_cost_aed
            - self.procurement_cost_aed
            - self.stockout_risk_penalty_aed
        )

    def to_row(self) -> Dict[str, Any]:
        """Flatten for persistence into flywheel_decisions."""
        return {
            "action_type": self.action_type.value,
            "item_id": self.item_id,
            "store_id": self.store_id,
            "category": self.category,
            "churn_probability": round(self.churn_probability, 5),
            "uplift": round(self.uplift, 5),
            "redemption_probability": round(self.redemption_probability, 5),
            "unit_price_aed": money4(self.unit_price_aed),
            "unit_cost_aed": money4(self.unit_cost_aed),
            "discount_pct": self.discount_pct,
            "expected_retained_value_aed": self.expected_retained_value_aed,
            "expected_margin_aed": self.expected_margin_aed,
            "expected_discount_cost_aed": self.expected_discount_cost_aed,
            "comms_cost_aed": self.comms_cost_aed,
            "fulfilment_cost_aed": self.fulfilment_cost_aed,
            "procurement_cost_aed": self.procurement_cost_aed,
            "stockout_risk_penalty_aed": self.stockout_risk_penalty_aed,
            "eiv_aed": self.eiv_aed,
            "reason_codes": self.reason_codes,
        }


@dataclass
class PolicyEnvelope:
    """The campaign's hard bounds. The optimizer may never propose outside these,
    and `decisioning` re-checks them at evaluate time in case the campaign was
    edited after the audience was built."""
    max_discount_pct: Decimal = Decimal("20")
    min_margin_pct: Decimal = Decimal("10")
    contact_cap_per_week: int = 2
    safety_stock_pct: Decimal = Decimal("10")
    policy_version: str = "v1"

    #: Uplift below this is treated as noise — an offer must EARN its discount.
    #: This is the rule that stops a high churn score alone buying a discount.
    min_uplift_threshold: float = 0.01


@dataclass
class AtpResult:
    """Available-to-promise for one (store, item), with every term exposed so
    the Decision Trace can show the arithmetic rather than a bare number."""
    store_id: int
    item_id: int
    on_hand: int = 0
    incoming: int = 0
    hard_reservations: int = 0
    soft_allocations: int = 0
    safety_stock: int = 0
    demand_buffer: int = 0

    @property
    def atp_units(self) -> int:
        """ATP = on_hand + incoming − reservations − allocations − safety − buffer.

        Clamped at zero: a negative ATP is not a promise of debt, it is simply
        nothing available.
        """
        return max(0, self.on_hand + self.incoming - self.hard_reservations
                   - self.soft_allocations - self.safety_stock - self.demand_buffer)

    def to_snapshot(self) -> Dict[str, Any]:
        return {
            "store_id": self.store_id, "item_id": self.item_id,
            "on_hand": self.on_hand, "incoming": self.incoming,
            "hard_reservations": self.hard_reservations,
            "soft_allocations": self.soft_allocations,
            "safety_stock": self.safety_stock,
            "demand_buffer": self.demand_buffer,
            "atp_units": self.atp_units,
        }
