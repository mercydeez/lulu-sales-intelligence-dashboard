"""Operations Copilot — the recommend graph (LangGraph, invocation A).

One auditable finite-state machine that turns a finding into a persisted,
awaiting-approval proposal — or a refusal/escalation. It is INVOCATION A: it runs
to a checkpoint (the awaiting_approval proposal in Postgres) and stops. It never
holds a request open waiting for a human; approval resumes the work as invocation
B (Phase 3), reading the checkpoint back by run_id.

Design choices that keep this honest and bounded:
  * The graph is LINEAR with guarded branches to a terminal — no loops, so the
    recursion limit is a backstop, not a control structure.
  * Every node is wrapped: an exception becomes status=failed + a failure event,
    never a half-built proposal.
  * The value-bearing work (evidence, calculation, the recommendation) is the
    PURE deterministic builder. The only LLM step, `narrate`, may ONLY replace
    prose, and only after ungrounded_numbers clears it; it can never add a number
    or an action. If the model is unavailable or its output is ungrounded, the
    deterministic summary stands and the run still completes.

State carries the db session and policy in-process (the graph compiles without a
checkpointer, so nothing here is serialized) — the sage3 convention.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional, TypedDict

from app.services.operations.contracts import (
    GRAPH_VERSION,
    PROMPT_VERSION,
    Hypothesis,
    NarrativeDraft,
    OperationsRecommendation,
    ungrounded_numbers,
)
from app.services.operations.fallback import build_recommendation
from app.services.operations.policy import (
    OperationsPolicy,
    accessible_store_ids,
    evidence_is_fresh,
)
from app.services.operations.tools_read import (
    finding_item_id,
    get_inventory_state,
    load_finding,
    stale_stock_feeds,
)

logger = logging.getLogger(__name__)

#: Backstop only — the graph has no loops.
_RECURSION_LIMIT = 12
#: Per-run wall-clock ceiling for the whole recommend pass.
_OVERALL_TIMEOUT_S = 45.0
#: The LLM narrate step is best-effort; keep it short so it never dominates.
_NARRATE_TIMEOUT_S = 20.0


class OpsState(TypedDict, total=False):
    # --- request / scope (READ-ONLY after init) ---
    run_id: int
    tenant_id: int
    finding_id: int
    user: Dict[str, Any]          # server-verified auth context

    # --- injected dependencies (never serialized; checkpointer is None) ---
    _db: Any
    _policy: OperationsPolicy

    # --- working data (each node writes its own slot) ---
    finding: Optional[Dict[str, Any]]
    snapshots: List[Dict[str, Any]]
    recommendation: Optional[Dict[str, Any]]   # OperationsRecommendation.model_dump()
    llm_available: bool

    # --- outcome ---
    status: str                   # awaiting_approval | refused | escalated | failed
    phase: str
    refusal_reason: Optional[str]
    error: Optional[str]
    events: List[Dict[str, Any]]  # structured audit events, persisted by the runner


def _event(state: OpsState, event_type: str, **payload) -> None:
    state.setdefault("events", []).append({
        "event_type": event_type,
        "actor": "system",
        "payload": payload,
    })


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

async def load_finding_node(state: OpsState) -> OpsState:
    """Load the finding, tenant-scoped. Absent finding → failed (nothing to do)."""
    state["phase"] = "load_finding"
    finding = await load_finding(state["_db"], tenant_id=state["tenant_id"],
                                 finding_id=state["finding_id"])
    if not finding:
        state["status"] = "failed"
        state["error"] = "finding not found for this tenant"
        _event(state, "finding.not_found", finding_id=state["finding_id"])
        return state
    state["finding"] = finding
    _event(state, "finding.loaded", rule=finding.get("rule"),
           status=finding.get("status"), severity=finding.get("severity"))
    return state


async def check_freshness_node(state: OpsState) -> OpsState:
    """Revalidate the finding is still current: not already resolved, and recent
    enough that acting on it is defensible. Stale/resolved → escalate."""
    state["phase"] = "check_freshness"
    finding = state["finding"]
    policy: OperationsPolicy = state["_policy"]

    if str(finding.get("status")) == "resolved":
        state["status"] = "escalated"
        state["refusal_reason"] = "finding is already resolved — nothing to act on"
        _event(state, "finding.stale", reason="already_resolved")
        return state

    ts = finding.get("updated_at") or finding.get("detected_at")
    if isinstance(ts, datetime) and not evidence_is_fresh(policy, ts, now=_now()):
        state["status"] = "escalated"
        state["refusal_reason"] = (
            "the finding is older than the tenant's freshness window — a human "
            "should re-verify before any action")
        _event(state, "finding.stale", reason="past_freshness_window")
        return state

    _event(state, "finding.fresh")
    return state


async def gather_and_recommend_node(state: OpsState) -> OpsState:
    """Fetch live inventory (for inventory findings) and build the deterministic
    recommendation. This is where evidence and every number are produced."""
    state["phase"] = "gather_and_recommend"
    finding = state["finding"]
    policy: OperationsPolicy = state["_policy"]
    user = state["user"]

    snapshots: List[Dict[str, Any]] = []
    item_id = finding_item_id(finding)
    if item_id is not None:
        role = str(user.get("role") or "").lower()
        scope = accessible_store_ids(user)
        # Only a super_admin with NO explicit store list reads tenant-wide (None).
        # For everyone else the (possibly empty) list is passed through verbatim —
        # an empty scope returns NO snapshots, never the whole tenant's inventory.
        store_filter = None if (role == "super_admin" and not scope) else scope
        snapshots = await get_inventory_state(
            state["_db"], tenant_id=state["tenant_id"], item_id=item_id,
            store_ids=store_filter)
    state["snapshots"] = snapshots
    _event(state, "evidence.gathered", inventory_rows=len(snapshots),
           item_id=item_id)

    # Stock-feed freshness gate: check_freshness_node protected the FINDING; this
    # protects the STOCK NUMBER we're about to size an order on. If a store's
    # inventory feed has gone dark (store-wide + snapshot-aware, so a quiet SKU
    # isn't mistaken for a dead feed), we've lost sight of on-hand stock —
    # escalate for human re-verify rather than order against a number we can't
    # stand behind. Non-inventory findings (no snapshots) skip this.
    if snapshots:
        stale = await stale_stock_feeds(
            state["_db"], [s["store_id"] for s in snapshots],
            max_age_hours=policy.max_evidence_age_hours)
        if stale:
            state["status"] = "escalated"
            state["refusal_reason"] = (
                f"the inventory feed for store(s) {sorted(stale)} has not updated "
                "within the freshness window — a human should re-verify on-hand "
                "stock before any replenishment or transfer")
            _event(state, "stock.stale", stores=sorted(stale))
            return state

    rec = build_recommendation(run_id=state["run_id"], tenant_id=state["tenant_id"],
                               finding=finding, snapshots=snapshots, policy=policy,
                               now=_now())
    rec.llm_available = True   # provisional; narrate may flip it
    state["recommendation"] = rec.model_dump(mode="json")

    if rec.is_actionable:
        state["status"] = "awaiting_approval"
        _event(state, "proposal.drafted",
               action_type=rec.proposed_actions[0].action_type.value,
               confidence=rec.confidence)
    else:
        state["status"] = "escalated" if rec.missing_data else "refused"
        state["refusal_reason"] = rec.refusal_reason
        _event(state, "recommendation.refused", reason=rec.refusal_reason)
    return state


async def narrate_node(state: OpsState) -> OpsState:
    """OPTIONAL LLM polish. May only replace the executive summary and hypotheses,
    and only if every number in the new prose is grounded in existing evidence.
    Any failure — no provider, timeout, bad JSON, ungrounded number — leaves the
    deterministic recommendation untouched. The model never sees a write tool and
    never contributes a number."""
    state["phase"] = "narrate"
    rec_dict = state.get("recommendation")
    if not rec_dict or not rec_dict.get("proposed_actions"):
        return state                      # nothing to narrate for a refusal

    try:
        rec = OperationsRecommendation.model_validate(rec_dict)
    except Exception:
        return state

    try:
        providers = _get_providers()
    except Exception:
        providers = []
    if not providers:
        rec.llm_available = False
        state["recommendation"] = rec.model_dump(mode="json")
        _event(state, "narrate.skipped", reason="no_llm_provider")
        return state

    prompt = _narrative_prompt(rec)
    draft: Optional[NarrativeDraft] = None
    for provider in providers:
        try:
            raw = await asyncio.wait_for(
                provider.complete([{"role": "user", "content": prompt}]),
                timeout=_NARRATE_TIMEOUT_S)
            draft = _parse_narrative(raw)
            if draft:
                break
        except Exception as exc:          # LLMError, timeout, parse — all non-fatal
            logger.info("operations narrate provider failed: %s", exc)
            continue

    if not draft:
        rec.llm_available = False
        _event(state, "narrate.fallback", reason="no_valid_narrative")
        state["recommendation"] = rec.model_dump(mode="json")
        return state

    # The grounding gate: the model may summarise numbers, never mint them. Allow
    # the calculator's own outputs (they are deterministic, just not in evidence).
    extra = _calculated_numbers(rec)
    bad = ungrounded_numbers(draft.free_text(), rec.evidence, extra_allowed=extra)
    if bad:
        rec.llm_available = True          # a model answered, but we rejected it
        _event(state, "narrate.rejected", ungrounded=bad[:5])
        state["recommendation"] = rec.model_dump(mode="json")
        return state

    rec.executive_summary = draft.executive_summary or rec.executive_summary
    if draft.hypotheses:
        rec.hypotheses = [Hypothesis(statement=h.statement, check=h.check)
                          for h in draft.hypotheses]
    rec.llm_available = True
    state["recommendation"] = rec.model_dump(mode="json")
    _event(state, "narrate.applied")
    return state


# ---------------------------------------------------------------------------
# LLM helpers (kept tiny; the provider chain is the existing local-first one)
# ---------------------------------------------------------------------------

def _get_providers():
    from app.services.llm import get_provider_chain
    return get_provider_chain()


def _calculated_numbers(rec: OperationsRecommendation) -> List[float]:
    """Deterministic calculator OUTPUTS the narrative may legitimately cite —
    quantities, cover, target levels. Store/item IDS are excluded: an identifier
    is not a measured value, and letting one ground prose would let an LLM's
    "saves 105 AED" pass whenever 105 happened to be a target store id."""
    nums: List[float] = []
    for action in rec.proposed_actions:
        for key, v in action.calculated_parameters.items():
            if key.endswith("_id") or key.endswith("_ids") or "store_id" in key \
                    or "item_id" in key:
                continue
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                nums.append(float(v))
    return nums


def _narrative_prompt(rec: OperationsRecommendation) -> str:
    evidence_lines = "\n".join(
        f"- {e.metric_name}: {e.current_value} {e.unit} (id {e.evidence_id})"
        for e in rec.evidence)
    return (
        "You are an operations analyst. Rewrite the summary for a store manager in "
        "2-3 sentences. You MUST NOT introduce any number that is not already in the "
        "evidence below — summarise, never invent. Return STRICT JSON with keys: "
        "title, executive_summary, hypotheses (list of {statement, check}).\n\n"
        f"Finding: {rec.title}\n"
        f"Current summary: {rec.executive_summary}\n"
        f"Evidence:\n{evidence_lines}\n"
    )


def _parse_narrative(raw: str) -> Optional[NarrativeDraft]:
    if not raw:
        return None
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
        return NarrativeDraft.model_validate(data)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def _after_load(state: OpsState) -> str:
    return "done" if state.get("status") == "failed" else "continue"


def _after_freshness(state: OpsState) -> str:
    return "done" if state.get("status") in ("escalated", "refused") else "continue"


def _after_recommend(state: OpsState) -> str:
    return "narrate" if state.get("status") == "awaiting_approval" else "done"


def _build_graph():
    from langgraph.graph import StateGraph, START, END

    g = StateGraph(OpsState)
    g.add_node("load_finding", load_finding_node)
    g.add_node("check_freshness", check_freshness_node)
    g.add_node("gather_and_recommend", gather_and_recommend_node)
    g.add_node("narrate", narrate_node)

    g.add_edge(START, "load_finding")
    g.add_conditional_edges("load_finding", _after_load,
                            {"continue": "check_freshness", "done": END})
    g.add_conditional_edges("check_freshness", _after_freshness,
                            {"continue": "gather_and_recommend", "done": END})
    g.add_conditional_edges("gather_and_recommend", _after_recommend,
                            {"narrate": "narrate", "done": END})
    g.add_edge("narrate", END)
    return g


@lru_cache(maxsize=1)
def get_graph():
    """Compiled recommend graph (built once). Stateless compile — the DB row IS
    the checkpoint (Phase-0 decision), so no langgraph checkpointer is used."""
    compiled = _build_graph().compile()
    logger.info("Operations recommend graph compiled (graph_version=%s).", GRAPH_VERSION)
    return compiled


async def run_recommend_graph(*, run_id: int, tenant_id: int, finding_id: int,
                              user: Dict[str, Any], db, policy: OperationsPolicy) -> OpsState:
    """Run invocation A to its checkpoint and return the terminal state. Every
    node is guarded and the whole pass is time-boxed; on any unexpected failure
    the run ends as `failed` with an audit event rather than a partial write."""
    state: OpsState = {
        "run_id": run_id, "tenant_id": tenant_id, "finding_id": finding_id,
        "user": user, "_db": db, "_policy": policy,
        "snapshots": [], "events": [], "llm_available": True,
        "status": "analyzing", "phase": "created",
    }
    graph = get_graph()
    try:
        result: OpsState = await asyncio.wait_for(
            graph.ainvoke(state, config={"recursion_limit": _RECURSION_LIMIT}),
            timeout=_OVERALL_TIMEOUT_S)
        return result
    except asyncio.TimeoutError:
        state["status"] = "failed"
        state["error"] = "recommend pass exceeded the overall timeout"
        _event(state, "run.timeout")
        return state
    except Exception as exc:
        logger.exception("operations recommend graph failed for run %s", run_id)
        state["status"] = "failed"
        state["error"] = str(exc)
        _event(state, "run.failed", error=str(exc)[:300])
        return state
