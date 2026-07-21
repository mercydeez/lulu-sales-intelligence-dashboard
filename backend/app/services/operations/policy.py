"""Operations Copilot — the tenant policy and approval engine.

APPROVAL LOGIC LIVES HERE, NOT IN ROUTE HANDLERS. One place decides who may
approve what, how a replenishment quantity is shaped, when a proposal goes
stale, and how long we wait before measuring. Route handlers ask this module;
they never re-derive the rules.

EVERYTHING IS CONFIGURATION. The code ships DEFAULTS (below) and a tenant may
override any of them via `tenant_operations_policies.policy`. No customer name,
store name, supplier, or monetary limit appears anywhere in this file — the
defaults are expressed in days, units and roles, which are tenant-neutral.

The role ladder reuses the platform's own roles and the caller's server-verified
`permissions.accessible_stores`. There is no parallel authorization model here:
a copilot approval can never grant reach the user does not already have.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.operations.contracts import ActionType, RiskLevel

logger = logging.getLogger(__name__)

#: Seniority ladder. A role may approve anything its own rung or below requires.
ROLE_RANK: Dict[str, int] = {
    "analyst": 0,
    "store_manager": 1,
    "regional_manager": 2,
    "super_admin": 3,
}


class ReplenishmentSettings(BaseModel):
    """Inputs to the deterministic replenishment calculator. Days, not dirhams —
    a quantity rule stays valid across currencies and catalogue sizes."""

    #: Buffer held on top of expected demand over the lead time.
    safety_stock_days: int = Field(default=7, ge=0, le=90)
    #: Used only when the item has no supplier lead time on record. Surfaced as
    #: an explicit assumption on every proposal that relies on it.
    default_lead_time_days: int = Field(default=7, ge=1, le=120)
    #: How far ahead one order should cover, beyond the lead time.
    review_period_days: int = Field(default=7, ge=1, le=90)
    #: Order quantities are rounded UP to this multiple (case/pallet size proxy).
    round_to_multiple: int = Field(default=1, ge=1, le=1000)
    min_order_quantity: int = Field(default=1, ge=1)
    #: Refuse to propose above this; a bigger number needs a human buyer, not a bot.
    max_order_quantity: int = Field(default=10000, ge=1)
    #: Velocity below this is too noisy to size an order from.
    min_daily_velocity: float = Field(default=0.1, ge=0.0)


class TransferSettings(BaseModel):
    """Safety rules for moving stock between stores. The source store is
    protected first: a transfer that creates a second stockout is not a fix."""

    #: Days of cover the SOURCE must retain after the transfer.
    source_min_days_cover: int = Field(default=10, ge=1, le=120)
    #: Never move more than this share of the source's on-hand in one draft.
    max_share_of_source: float = Field(default=0.5, gt=0.0, le=1.0)
    min_transfer_quantity: int = Field(default=1, ge=1)
    max_transfer_quantity: int = Field(default=5000, ge=1)


class OperationsPolicy(BaseModel):
    """The whole tenant-configurable ruleset."""

    allowed_action_types: List[ActionType] = Field(
        default_factory=lambda: list(ActionType))
    #: Minimum role that may approve each action type at normal risk.
    approval_roles: Dict[str, str] = Field(default_factory=lambda: {
        ActionType.INVESTIGATION_TASK.value: "store_manager",
        ActionType.REPLENISHMENT_DRAFT.value: "regional_manager",
        ActionType.STOCK_TRANSFER_DRAFT.value: "regional_manager",
    })
    #: A high-risk action escalates one rung up the ladder (capped at super_admin).
    escalate_high_risk: bool = True
    #: Action types that may only ever produce an INTERNAL draft. Every action
    #: type is draft-only until a real connector exists and is contracted.
    draft_only: Dict[str, bool] = Field(default_factory=lambda: {
        ActionType.REPLENISHMENT_DRAFT.value: True,
        ActionType.STOCK_TRANSFER_DRAFT.value: True,
        ActionType.INVESTIGATION_TASK.value: True,
    })
    #: Integrations. All false: no POS/ERP/procurement/notification connector is
    #: wired. Flipping one on without an implementation changes nothing — the
    #: connector layer refuses rather than faking a success response.
    integrations_enabled: Dict[str, bool] = Field(default_factory=lambda: {
        "procurement": False,
        "stock_transfer": False,
        "supplier_notification": False,
    })
    replenishment: ReplenishmentSettings = Field(default_factory=ReplenishmentSettings)
    transfer: TransferSettings = Field(default_factory=TransferSettings)
    #: An approval given against week-old numbers is not an approval of today.
    max_proposal_age_hours: int = Field(default=336, ge=1, le=8760)   # 14 days
    #: Evidence older than this makes the copilot refuse rather than guess.
    max_evidence_age_hours: int = Field(default=72, ge=1, le=8760)
    #: How long after execution we wait before judging the outcome.
    measurement_window_days: int = Field(default=14, ge=1, le=90)
    #: Below this, refuse to propose and escalate for human review.
    min_confidence: float = Field(default=0.4, ge=0.0, le=1.0)
    #: A proposal must cite at least this many pieces of evidence.
    min_evidence_items: int = Field(default=2, ge=1, le=20)
    #: Material change (fraction) in the key quantity between approval and
    #: execution that aborts execution and demands a fresh approval.
    revalidation_tolerance: float = Field(default=0.25, ge=0.0, le=1.0)


DEFAULT_POLICY = OperationsPolicy()


async def get_policy(db: AsyncSession, tenant_id: int) -> OperationsPolicy:
    """Resolve a tenant's policy, falling back to defaults.

    Fails OPEN to the defaults on a malformed stored document: a bad policy row
    must not take the copilot offline, and the defaults are the conservative
    ones (draft-only, no integrations). The failure is logged loudly.
    """
    try:
        row = (await db.execute(
            text("SELECT policy FROM tenant_operations_policies WHERE tenant_id = :t"),
            {"t": tenant_id},
        )).scalar_one_or_none()
    except Exception as exc:                      # table missing / DB hiccup
        logger.warning("operations policy read failed for tenant %s: %s", tenant_id, exc)
        return DEFAULT_POLICY

    if not row:
        return DEFAULT_POLICY
    try:
        return OperationsPolicy.model_validate(row)
    except ValidationError as exc:
        logger.error("operations policy for tenant %s is invalid, using defaults: %s",
                     tenant_id, exc)
        return DEFAULT_POLICY


def required_role(policy: OperationsPolicy, action_type: ActionType,
                  risk_level: RiskLevel = RiskLevel.MEDIUM) -> str:
    """The minimum role that may approve this action under this policy."""
    base = policy.approval_roles.get(action_type.value, "super_admin")
    rank = ROLE_RANK.get(base, ROLE_RANK["super_admin"])
    if policy.escalate_high_risk and risk_level == RiskLevel.HIGH:
        rank = min(rank + 1, ROLE_RANK["super_admin"])
    for name, value in ROLE_RANK.items():
        if value == rank:
            return name
    return "super_admin"


def accessible_store_ids(user: Dict[str, Any]) -> List[int]:
    """Server-verified store scope. NEVER read from a request body or model output."""
    return list((user.get("permissions") or {}).get("accessible_stores") or [])


def can_approve(user: Dict[str, Any], policy: OperationsPolicy, *,
                action_type: ActionType, risk_level: RiskLevel,
                target_store_ids: List[int]) -> Tuple[bool, str]:
    """May this user approve this action? Returns (allowed, reason_if_not).

    Two independent gates, both must pass:
      1. Role seniority meets the policy's requirement for the action/risk.
      2. EVERY target store is inside the user's own accessible scope — so a
         cross-store transfer needs someone who can already see both stores.
    """
    if action_type not in policy.allowed_action_types:
        return False, f"action type {action_type.value} is not enabled for this tenant"

    role = (user.get("role") or "").lower()
    needed = required_role(policy, action_type, risk_level)
    if ROLE_RANK.get(role, -1) < ROLE_RANK.get(needed, 99):
        return False, f"requires role {needed} or higher"

    # super_admin is scoped to its own tenant by RLS; an empty accessible_stores
    # list means "all stores in this tenant" for that role only.
    if role != "super_admin":
        scope = set(accessible_store_ids(user))
        outside = [s for s in target_store_ids if s not in scope]
        if outside:
            return False, f"stores {outside} are outside your authorised scope"
    return True, ""


def proposal_expiry(policy: OperationsPolicy,
                    created_at: Optional[datetime] = None) -> datetime:
    base = created_at or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base + timedelta(hours=policy.max_proposal_age_hours)


def is_expired(policy: OperationsPolicy, created_at: datetime,
               now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now >= proposal_expiry(policy, created_at)


def evidence_is_fresh(policy: OperationsPolicy, observed_at: datetime,
                      now: Optional[datetime] = None) -> bool:
    """Stale evidence is a refusal reason, not something to caveat and proceed on."""
    now = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now - observed_at) <= timedelta(hours=policy.max_evidence_age_hours)


def materially_changed(policy: OperationsPolicy, approved_value: float,
                       current_value: float) -> bool:
    """Did the world move enough between approval and execution to invalidate
    the approval? Zero-to-nonzero counts as material."""
    if approved_value == 0:
        return current_value != 0
    return abs(current_value - approved_value) / abs(approved_value) > policy.revalidation_tolerance


def is_draft_only(policy: OperationsPolicy, action_type: ActionType) -> bool:
    """True when execution may only write an INTERNAL draft record.

    Draft-only is also forced whenever the matching integration is disabled —
    so a policy that says draft_only=False but has no connector still cannot
    produce an externally-submitted order.
    """
    integration = {
        ActionType.REPLENISHMENT_DRAFT: "procurement",
        ActionType.STOCK_TRANSFER_DRAFT: "stock_transfer",
        ActionType.INVESTIGATION_TASK: None,
    }.get(action_type)
    if integration and not policy.integrations_enabled.get(integration, False):
        return True
    return policy.draft_only.get(action_type.value, True)
