"""Operations Copilot — the deterministic recommendation builder.

This is the floor the whole feature stands on. It takes a finding, the current
inventory snapshots and the tenant policy, and produces a fully-formed
OperationsRecommendation WITHOUT any LLM: evidence, measured facts, a calculated
action (or a refusal), an approval requirement and a measurement plan. Every
number comes from build_*_evidence and the calculators — nothing here is
invented.

It plays two roles:
  1. The graceful-degradation path when no LLM provider is reachable — the
     copilot still shows the finding, the calculated evidence and a rule-based
     next step (requirement #14: usable when the LLM is unavailable).
  2. The trusted BASE that the LLM narrative merely re-phrases. The graph never
     lets a model add or change a number; it only swaps the executive_summary
     and hypotheses for nicer prose after ungrounded_numbers clears them.

Pure functions only — unit-tested without a database or a model.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.services.operations.calculations import (
    CalculationResult,
    calculate_measurement_baseline,
    calculate_replenishment,
    calculate_transfer,
    days_of_cover,
)
from app.services.operations.contracts import (
    ActionType,
    ApprovalRequirement,
    EvidenceItem,
    Hypothesis,
    MeasuredFact,
    MeasurementPlan,
    OperationsRecommendation,
    ProposedAction,
    RiskLevel,
    Severity,
)
from app.services.operations.policy import (
    OperationsPolicy,
    evidence_is_fresh,
    required_role,
)
from app.services.operations.tools_read import (
    build_finding_evidence,
    build_inventory_evidence,
    finding_item_id,
)

#: Findings whose natural action is replenishing or moving stock.
_INVENTORY_RULES = frozenset({"stockout", "dead_stock_growth", "zero_sales_sku"})
_INVENTORY_ACTION_TYPES = frozenset({"reorder", "markdown"})


def _severity(finding: Dict) -> Severity:
    try:
        return Severity(str(finding.get("severity") or "medium").lower())
    except ValueError:
        return Severity.MEDIUM


def _confidence(evidence: List[EvidenceItem], policy: OperationsPolicy,
                now: datetime, actionable: bool) -> float:
    """Deterministic confidence — NOT a model's self-assessment.

    Three factors, each worth a third: enough evidence, all of it fresh, and a
    defensible calculated action. This is the number policy.min_confidence gates
    on, so it must be reproducible from inputs alone.
    """
    if not evidence:
        return 0.0
    enough = 1.0 if len(evidence) >= policy.min_evidence_items else 0.5
    fresh = 1.0 if all(evidence_is_fresh(policy, e.observed_at, now=now)
                       for e in evidence) else 0.0
    action = 1.0 if actionable else 0.5
    return round((enough + fresh + action) / 3.0, 3)


def _refusal(*, run_id: int, tenant_id: int, finding: Dict,
             evidence: List[EvidenceItem], reason: str,
             missing: Optional[List[str]] = None) -> OperationsRecommendation:
    """A refusal is a valid outcome: show the finding and the evidence, propose
    nothing, say why. The caller escalates for human review."""
    return OperationsRecommendation(
        run_id=run_id, finding_id=finding.get("id"), tenant_id=tenant_id,
        scope={"entity_type": finding.get("entity_type"),
               "entity_id": finding.get("entity_id")},
        title=str(finding.get("title") or "Operational finding"),
        executive_summary=str(finding.get("detail") or ""),
        severity=_severity(finding),
        confidence=0.0,
        evidence=evidence,
        proposed_actions=[],
        missing_data=missing or [],
        refusal_reason=reason,
    )


def _out_of_scope_snapshots(snapshots: List[Dict]) -> Tuple[Optional[Dict], Optional[Dict]]:
    """Pick the neediest store (out of stock / below reorder / lowest cover) and,
    for a possible transfer, the healthiest sibling that can donate."""
    if not snapshots:
        return None, None

    def cover(s):
        c = days_of_cover(s.get("current_stock"), s.get("average_daily_sales"))
        return c if c is not None else float("inf")

    needy = min(snapshots, key=lambda s: (not s.get("is_out_of_stock"), cover(s),
                                          s.get("current_stock") or 0))
    donors = [s for s in snapshots
              if s is not needy and (s.get("current_stock") or 0) > 0
              and not s.get("is_out_of_stock")]
    donor = max(donors, key=cover) if donors else None
    return needy, donor


def build_recommendation(*, run_id: int, tenant_id: int, finding: Dict,
                         snapshots: List[Dict], policy: OperationsPolicy,
                         now: Optional[datetime] = None) -> OperationsRecommendation:
    """The dispatcher. Classifies the finding and builds the right recommendation
    — replenishment, transfer, or investigation — or a refusal when the data
    cannot support any of them. Pure."""
    now = now or datetime.now(timezone.utc)
    rule = str(finding.get("rule") or "").lower()
    action_type = str(finding.get("action_type") or "").lower()
    is_inventory = rule in _INVENTORY_RULES or action_type in _INVENTORY_ACTION_TYPES

    finding_ev = build_finding_evidence(finding, observed_at=now)

    if not is_inventory:
        return _build_investigation(run_id=run_id, tenant_id=tenant_id,
                                    finding=finding, evidence=finding_ev,
                                    policy=policy, now=now)

    # Inventory action needs a live snapshot; without one we cannot size anything.
    item_id = finding_item_id(finding)
    if item_id is None or not snapshots:
        return _refusal(
            run_id=run_id, tenant_id=tenant_id, finding=finding, evidence=finding_ev,
            reason="no current inventory snapshot for this item in your store scope — "
                   "cannot size a replenishment or transfer",
            missing=["current inventory state (metric_inventory_state)"])

    needy, donor = _out_of_scope_snapshots(snapshots)
    needy_ev = build_inventory_evidence(needy, observed_at=now)
    evidence = finding_ev + needy_ev

    # Prefer a transfer when a healthy sibling can cover the need without risk.
    if donor is not None:
        donor_ev = build_inventory_evidence(donor, observed_at=now, prefix="donor_")
        calc = calculate_transfer(
            source_stock=donor.get("current_stock") or 0,
            source_velocity=donor.get("average_daily_sales") or 0,
            destination_stock=needy.get("current_stock") or 0,
            destination_velocity=needy.get("average_daily_sales") or 0,
            settings=policy.transfer)
        if calc.is_actionable:
            return _build_transfer(run_id=run_id, tenant_id=tenant_id, finding=finding,
                                   needy=needy, donor=donor,
                                   evidence=evidence + donor_ev, calc=calc,
                                   policy=policy, now=now)
        # transfer not safe -> fall through to replenishment

    calc = calculate_replenishment(
        current_stock=needy.get("current_stock") or 0,
        daily_velocity=needy.get("average_daily_sales") or 0,
        settings=policy.replenishment,
        reorder_point=needy.get("reorder_point"))
    if not calc.is_actionable:
        return _refusal(run_id=run_id, tenant_id=tenant_id, finding=finding,
                        evidence=evidence,
                        reason=calc.refusal_reason or "no defensible replenishment quantity")

    return _build_replenishment(run_id=run_id, tenant_id=tenant_id, finding=finding,
                                needy=needy, evidence=evidence, calc=calc,
                                policy=policy, now=now)


def _risk_from_quantity(quantity: int, ceiling: int) -> RiskLevel:
    if quantity >= ceiling * 0.75:
        return RiskLevel.HIGH
    if quantity >= ceiling * 0.25:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _finalise(*, run_id: int, tenant_id: int, finding: Dict,
              evidence: List[EvidenceItem], action: ProposedAction,
              measured: List[MeasuredFact], plan: MeasurementPlan,
              policy: OperationsPolicy, now: datetime,
              summary: str) -> OperationsRecommendation:
    actionable = True
    confidence = _confidence(evidence, policy, now, actionable)
    # Confidence/evidence gate: below the floor, refuse rather than propose.
    if confidence < policy.min_confidence or len(evidence) < policy.min_evidence_items:
        return _refusal(run_id=run_id, tenant_id=tenant_id, finding=finding,
                        evidence=evidence,
                        reason=f"evidence/confidence below the tenant threshold "
                               f"(confidence {confidence} < {policy.min_confidence})")
    return OperationsRecommendation(
        run_id=run_id, finding_id=finding.get("id"), tenant_id=tenant_id,
        scope={"entity_type": finding.get("entity_type"),
               "entity_id": finding.get("entity_id"),
               "store_ids": action.target_store_ids},
        title=str(finding.get("title") or "Operational finding"),
        executive_summary=summary,
        severity=_severity(finding),
        confidence=confidence,
        measured_facts=measured,
        evidence=evidence,
        proposed_actions=[action],
        assumptions=list(action.calculated_parameters.get("_assumptions", [])),
        measurement_plan=plan,
        approval_requirement=ApprovalRequirement(
            required_role=action.required_approval_role,
            reason=f"{action.action_type.value} requires {action.required_approval_role} sign-off",
            scope_store_ids=action.target_store_ids),
    )


def _build_replenishment(*, run_id, tenant_id, finding, needy, evidence,
                         calc: CalculationResult, policy, now) -> OperationsRecommendation:
    role = required_role(policy, ActionType.REPLENISHMENT_DRAFT)
    risk = _risk_from_quantity(calc.quantity, policy.replenishment.max_order_quantity)
    if risk == RiskLevel.HIGH:
        role = required_role(policy, ActionType.REPLENISHMENT_DRAFT, RiskLevel.HIGH)
    store_id = needy.get("store_id")
    item_id = needy.get("item_id")
    velocity_eid = f"s{store_id}_velocity"
    stock_eid = f"s{store_id}_stock"

    params = dict(calc.inputs)
    params["quantity"] = calc.quantity
    params["_steps"] = calc.steps
    params["_assumptions"] = calc.assumptions
    params["supplier"] = None            # no supplier data -> none selected (honest)

    action = ProposedAction(
        action_type=ActionType.REPLENISHMENT_DRAFT,
        title=f"Replenish {needy.get('item_name')} at {needy.get('store_name')}",
        description=(f"Draft an internal replenishment for {calc.quantity} units. "
                     "No supplier is selected (no supplier data is connected). "
                     + " ".join(calc.steps)),
        target_store_ids=[store_id] if store_id is not None else [],
        target_item_ids=[item_id] if item_id is not None else [],
        calculated_parameters=params,
        expected_effect=f"restores cover toward {params.get('target_level')} units on hand",
        expected_effect_basis="order-up-to level from observed velocity and lead time",
        risk_level=risk, reversible=True, required_approval_role=role,
        prerequisites=["a supplier must be selected before any external order"],
        evidence_ids=[e.evidence_id for e in evidence
                      if e.evidence_id in {velocity_eid, stock_eid}] or [evidence[0].evidence_id],
    )
    measured = [MeasuredFact(
        statement=f"{needy.get('item_name')} at {needy.get('store_name')} is at "
                  f"{needy.get('current_stock')} units against {needy.get('average_daily_sales')}/day demand",
        evidence_ids=[e.evidence_id for e in evidence if e.evidence_id in {stock_eid, velocity_eid}]
                     or [evidence[0].evidence_id])]
    plan_src = calculate_measurement_baseline(
        action_type=ActionType.REPLENISHMENT_DRAFT.value, policy=policy,
        current_stock=needy.get("current_stock"), daily_velocity=needy.get("average_daily_sales"))
    plan = MeasurementPlan(metric_name=plan_src.metric_name, baseline_value=plan_src.baseline_value,
                           unit=plan_src.unit, window_days=plan_src.window_days,
                           success_criterion=plan_src.success_criterion)
    summary = (f"{needy.get('item_name')} is short at {needy.get('store_name')}. "
               f"A replenishment of {calc.quantity} units restores cover; approval drafts "
               "an internal procurement task, not an external order.")
    return _finalise(run_id=run_id, tenant_id=tenant_id, finding=finding, evidence=evidence,
                     action=action, measured=measured, plan=plan, policy=policy, now=now,
                     summary=summary)


def _build_transfer(*, run_id, tenant_id, finding, needy, donor, evidence,
                    calc: CalculationResult, policy, now) -> OperationsRecommendation:
    role = required_role(policy, ActionType.STOCK_TRANSFER_DRAFT)
    src_id, dst_id = donor.get("store_id"), needy.get("store_id")
    item_id = needy.get("item_id")
    params = dict(calc.inputs)
    params["quantity"] = calc.quantity
    params["_steps"] = calc.steps
    params["_assumptions"] = calc.assumptions
    params["source_store_id"] = src_id
    params["destination_store_id"] = dst_id

    cited = [e.evidence_id for e in evidence
             if e.evidence_id in {f"s{dst_id}_stock", f"s{dst_id}_velocity",
                                  f"donor_s{src_id}_stock", f"donor_s{src_id}_velocity"}]
    action = ProposedAction(
        action_type=ActionType.STOCK_TRANSFER_DRAFT,
        title=f"Transfer {calc.quantity} units of {needy.get('item_name')} "
              f"from {donor.get('store_name')} to {needy.get('store_name')}",
        description=(f"Draft an internal stock transfer of {calc.quantity} units. "
                     + " ".join(calc.steps)),
        target_store_ids=[s for s in (src_id, dst_id) if s is not None],
        target_item_ids=[item_id] if item_id is not None else [],
        calculated_parameters=params,
        expected_effect=f"raises {needy.get('store_name')} cover while keeping "
                        f"{donor.get('store_name')} above its safety floor",
        expected_effect_basis="transfer sized by destination need and source safety stock",
        risk_level=RiskLevel.MEDIUM, reversible=True, required_approval_role=role,
        prerequisites=["both stores must be within the approver's region"],
        evidence_ids=cited or [evidence[0].evidence_id])
    measured = [MeasuredFact(
        statement=f"{donor.get('store_name')} holds {donor.get('current_stock')} units "
                  f"while {needy.get('store_name')} is at {needy.get('current_stock')}",
        evidence_ids=cited or [evidence[0].evidence_id])]
    plan_src = calculate_measurement_baseline(
        action_type=ActionType.STOCK_TRANSFER_DRAFT.value, policy=policy,
        current_stock=needy.get("current_stock"), daily_velocity=needy.get("average_daily_sales"))
    plan = MeasurementPlan(metric_name=plan_src.metric_name, baseline_value=plan_src.baseline_value,
                           unit=plan_src.unit, window_days=plan_src.window_days,
                           success_criterion=plan_src.success_criterion)
    summary = (f"{needy.get('item_name')} is short at {needy.get('store_name')} while "
               f"{donor.get('store_name')} has surplus. A transfer of {calc.quantity} units "
               "relieves it without risking the source; approval drafts an internal transfer task.")
    return _finalise(run_id=run_id, tenant_id=tenant_id, finding=finding, evidence=evidence,
                     action=action, measured=measured, plan=plan, policy=policy, now=now,
                     summary=summary)


def _build_investigation(*, run_id, tenant_id, finding, evidence,
                         policy, now) -> OperationsRecommendation:
    if not evidence:
        return _refusal(run_id=run_id, tenant_id=tenant_id, finding=finding, evidence=[],
                        reason="the finding carries no measurable evidence to investigate",
                        missing=["finding evidence (metric_value / evidence blob)"])
    role = required_role(policy, ActionType.INVESTIGATION_TASK)
    rule = str(finding.get("rule") or "")
    checklist = _investigation_checklist(rule)
    action = ProposedAction(
        action_type=ActionType.INVESTIGATION_TASK,
        title=f"Investigate: {finding.get('title')}",
        description="Assign a bounded investigation. Checklist: " + "; ".join(checklist),
        target_store_ids=[int(finding["entity_id"])] if str(finding.get("entity_type")) == "store"
                         and str(finding.get("entity_id") or "").isdigit() else [],
        target_item_ids=[int(finding["entity_id"])] if str(finding.get("entity_type")) == "item"
                        and str(finding.get("entity_id") or "").isdigit() else [],
        calculated_parameters={"checklist": checklist, "_assumptions": []},
        expected_effect="unknown",
        expected_effect_basis="an investigation surfaces cause; it does not itself move the metric",
        risk_level=RiskLevel.LOW, reversible=True, required_approval_role=role,
        evidence_ids=[e.evidence_id for e in evidence])
    measured = [MeasuredFact(
        statement=str(finding.get("detail") or finding.get("title")),
        evidence_ids=[evidence[0].evidence_id])]
    hypotheses = [Hypothesis(statement=h, check=c) for h, c in _investigation_hypotheses(rule)]
    plan_src = calculate_measurement_baseline(
        action_type=ActionType.INVESTIGATION_TASK.value, policy=policy,
        finding_metric_value=finding.get("metric_value"), finding_rule=rule)
    plan = MeasurementPlan(metric_name=plan_src.metric_name, baseline_value=plan_src.baseline_value,
                           unit=plan_src.unit, window_days=plan_src.window_days,
                           success_criterion=plan_src.success_criterion)
    confidence = _confidence(evidence, policy, now, actionable=True)
    if confidence < policy.min_confidence or len(evidence) < policy.min_evidence_items:
        # Investigations have a lower bar than money actions, but still need a
        # minimum of evidence; below it, escalate for a human to scope.
        return _refusal(run_id=run_id, tenant_id=tenant_id, finding=finding, evidence=evidence,
                        reason=f"insufficient evidence to scope an investigation "
                               f"(confidence {confidence} < {policy.min_confidence})")
    return OperationsRecommendation(
        run_id=run_id, finding_id=finding.get("id"), tenant_id=tenant_id,
        scope={"entity_type": finding.get("entity_type"), "entity_id": finding.get("entity_id")},
        title=str(finding.get("title") or "Operational finding"),
        executive_summary=str(finding.get("detail") or ""),
        severity=_severity(finding), confidence=confidence,
        measured_facts=measured, hypotheses=hypotheses, evidence=evidence,
        proposed_actions=[action], measurement_plan=plan,
        approval_requirement=ApprovalRequirement(
            required_role=role, reason=f"investigation task requires {role} sign-off",
            scope_store_ids=action.target_store_ids))


def _investigation_checklist(rule: str) -> List[str]:
    base = ["Confirm the finding against the source dashboard",
            "Check for a known operational cause (holiday, closure, data gap)",
            "Record findings and a corrective step in the task"]
    extra = {
        "revenue_drop": ["Compare like-for-like days", "Check stock availability of top sellers"],
        "category_slump": ["Compare against the category's regional trend",
                           "Check for a lapsed promotion"],
        "return_spike": ["Sample recent returns for a common reason",
                         "Check a supplier batch or quality issue"],
        "laggard_store": ["Compare staffing and footfall vs peers",
                          "Check local competition or roadworks"],
    }.get(rule, [])
    return base[:1] + extra + base[1:]


def _investigation_hypotheses(rule: str) -> List[Tuple[str, str]]:
    return {
        "revenue_drop": [("A top-selling line went out of stock",
                          "Cross-check stockout findings for the same store/period")],
        "category_slump": [("A competing promotion pulled demand",
                            "Compare the category's regional share trend")],
        "return_spike": [("A single supplier batch is faulty",
                          "Group recent returns by supplier/batch")],
    }.get(rule, [("Cause is not yet identified from the data",
                  "The investigation task is to determine it")])
