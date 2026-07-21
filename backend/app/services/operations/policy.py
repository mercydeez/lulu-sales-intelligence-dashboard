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
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError
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

#: Which integration each action type needs to execute for real rather than as an
#: internal draft. This is CODE, not tenant config: a connector appears here only
#: when a module actually implements it. No JSON value can add an entry, so a
#: tenant cannot enable a connector that does not exist — see is_draft_only().
AVAILABLE_CONNECTORS: frozenset = frozenset()   # none wired yet — everything is draft-only

#: Action types that MUST name at least one store to be scoped. An action with an
#: empty target list must never pass the approval scope check by having no scope.
STORE_SCOPED_ACTIONS: frozenset = frozenset({
    ActionType.REPLENISHMENT_DRAFT, ActionType.STOCK_TRANSFER_DRAFT,
    ActionType.INVESTIGATION_TASK,
})


class MalformedPolicyError(Exception):
    """A stored tenant policy exists but does not validate. Money-adjacent gates
    must REFUSE the run rather than silently fall back to a different ruleset."""


class ReplenishmentSettings(BaseModel):
    """Inputs to the deterministic replenishment calculator. Days, not dirhams —
    a quantity rule stays valid across currencies and catalogue sizes."""

    model_config = ConfigDict(frozen=True)

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

    model_config = ConfigDict(frozen=True)

    #: Days of cover the SOURCE must retain after the transfer.
    source_min_days_cover: int = Field(default=10, ge=1, le=120)
    #: Never move more than this share of the source's on-hand in one draft.
    max_share_of_source: float = Field(default=0.5, gt=0.0, le=1.0)
    min_transfer_quantity: int = Field(default=1, ge=1)
    max_transfer_quantity: int = Field(default=5000, ge=1)


class OperationsPolicy(BaseModel):
    """The whole tenant-configurable ruleset.

    Frozen: get_policy() hands out the shared DEFAULT_POLICY singleton to every
    tenant without a policy row, so it must not be mutable — one caller flipping a
    flag would leak across tenants. A tenant that needs different values stores a
    policy row; overriding at runtime is a bug, not a feature.
    """

    model_config = ConfigDict(frozen=True)

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
    #: Capped so a tenant cannot widen it into "approvals never expire".
    max_proposal_age_hours: int = Field(default=336, ge=1, le=720)    # 14d default, 30d ceiling
    #: Evidence older than this makes the copilot refuse rather than guess. Ceiling
    #: keeps "stale evidence must cause refusal" from being configured into a no-op.
    max_evidence_age_hours: int = Field(default=72, ge=1, le=336)     # 3d default, 14d ceiling
    #: How long after execution we wait before judging the outcome.
    measurement_window_days: int = Field(default=14, ge=1, le=90)
    #: Below this, refuse to propose and escalate for human review.
    min_confidence: float = Field(default=0.4, ge=0.0, le=1.0)
    #: A proposal must cite at least this many pieces of evidence.
    min_evidence_items: int = Field(default=2, ge=1, le=20)
    #: Material change (fraction) in the key quantity between approval and
    #: execution that aborts execution and demands a fresh approval. Capped well
    #: below 1.0 — tolerating a 100% swing would defeat revalidation entirely.
    revalidation_tolerance: float = Field(default=0.25, ge=0.0, le=0.5)


DEFAULT_POLICY = OperationsPolicy()


async def get_policy(db: AsyncSession, tenant_id: int) -> OperationsPolicy:
    """Resolve a tenant's policy.

    NO ROW → the shared DEFAULT_POLICY (the conservative ruleset: draft-only, no
    integrations). That is a safe substitute for "tenant never configured one".

    MALFORMED ROW or a DB error → raise MalformedPolicyError. A tenant that stored
    a policy expressed an intent; silently swapping a DIFFERENT ruleset underneath
    a money-adjacent gate (re-enabling drafts they disabled, widening a freshness
    window they tightened) is worse than refusing the run. The caller turns this
    into a refusal/escalation, not an invented recommendation.
    """
    try:
        row = (await db.execute(
            text("SELECT policy FROM tenant_operations_policies WHERE tenant_id = :t"),
            {"t": tenant_id},
        )).scalar_one_or_none()
    except Exception as exc:                      # table missing / DB hiccup
        logger.error("operations policy read failed for tenant %s: %s", tenant_id, exc)
        raise MalformedPolicyError(f"could not read operations policy: {exc}") from exc

    if not row:
        return DEFAULT_POLICY
    try:
        return OperationsPolicy.model_validate(row)
    except ValidationError as exc:
        logger.error("operations policy for tenant %s is invalid: %s", tenant_id, exc)
        raise MalformedPolicyError(
            f"stored operations policy for tenant {tenant_id} does not validate"
        ) from exc


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
                target_store_ids: List[int],
                proposal_tenant_id: int) -> Tuple[bool, str]:
    """May this user approve this action? Returns (allowed, reason_if_not).

    Four independent gates, all must pass — belt-and-braces above RLS, because
    `settings.use_rls_role` is off outside production and this function is billed
    as *the* approval gate:
      0. The proposal belongs to the user's OWN tenant.
      1. The action type is enabled for the tenant.
      2. Role seniority meets the policy's requirement for the action/risk.
      3. A store-scoped action names at least one store, and EVERY named store is
         inside the user's own accessible scope. An empty target list is a
         refusal, not a free pass.
    """
    # Gate 0 — tenant. Server-verified auth context only; never a request body.
    user_tenant = user.get("tenant_id")
    if user_tenant is None or int(user_tenant) != int(proposal_tenant_id):
        return False, "proposal belongs to a different tenant"

    if action_type not in policy.allowed_action_types:
        return False, f"action type {action_type.value} is not enabled for this tenant"

    role = (user.get("role") or "").lower()
    needed = required_role(policy, action_type, risk_level)
    if ROLE_RANK.get(role, -1) < ROLE_RANK.get(needed, 99):
        return False, f"requires role {needed} or higher"

    scope = set(accessible_store_ids(user))
    # super_admin with NO explicit store list means "all stores in this tenant";
    # a super_admin whose scope was deliberately narrowed is still held to it.
    if role == "super_admin" and not scope:
        return True, ""

    if action_type in STORE_SCOPED_ACTIONS and not target_store_ids:
        return False, "action names no target store — cannot be scope-checked"

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
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    # A future-dated created_at is not a valid, never-expiring proposal — it is
    # bad data, and bad data must not extend an approval's life.
    if created_at > now:
        return True
    return now >= proposal_expiry(policy, created_at)


def evidence_is_fresh(policy: OperationsPolicy, observed_at: datetime,
                      now: Optional[datetime] = None) -> bool:
    """Stale evidence is a refusal reason, not something to caveat and proceed on.

    Bounded on BOTH sides: future-dated evidence is not "fresh", it is untrusted
    (an LLM or a bad clock could otherwise mint permanently-fresh evidence by
    dating it in the future).
    """
    now = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age = now - observed_at
    return timedelta(0) <= age <= timedelta(hours=policy.max_evidence_age_hours)


def materially_changed(policy: OperationsPolicy, approved_value: float,
                       current_value: float) -> bool:
    """Did the world move enough between approval and execution to invalidate
    the approval? Zero-to-nonzero counts as material, and a non-finite reading
    (NaN/inf from a bad upstream division) is treated as material — the one
    function whose job is to abort must fail toward aborting, not proceeding."""
    if approved_value is None or current_value is None:
        return True
    if not math.isfinite(approved_value) or not math.isfinite(current_value):
        return True
    if approved_value == 0:
        return current_value != 0
    return abs(current_value - approved_value) / abs(approved_value) > policy.revalidation_tolerance


def is_draft_only(policy: OperationsPolicy, action_type: ActionType) -> bool:
    """True when execution may only write an INTERNAL draft record.

    THREE ways this returns True, and no tenant configuration can escape the
    first: a connector that is not implemented in code cannot be enabled by a
    JSON flag. Only a real, registered connector that the tenant has also
    enabled, for an action the tenant has NOT marked draft-only, executes for
    real. Since AVAILABLE_CONNECTORS is empty, everything is draft-only today.
    """
    integration = {
        ActionType.REPLENISHMENT_DRAFT: "procurement",
        ActionType.STOCK_TRANSFER_DRAFT: "stock_transfer",
        ActionType.INVESTIGATION_TASK: None,
    }.get(action_type)
    if integration:
        # Gate 1: the connector must actually exist in code. A tenant cannot
        # enable what no module implements.
        if integration not in AVAILABLE_CONNECTORS:
            return True
        # Gate 2: the tenant must have turned it on.
        if not policy.integrations_enabled.get(integration, False):
            return True
    # Gate 3: the tenant's explicit draft-only flag (defaults to draft-only).
    return policy.draft_only.get(action_type.value, True)
