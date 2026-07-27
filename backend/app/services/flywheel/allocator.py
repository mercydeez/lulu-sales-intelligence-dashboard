"""Global constrained allocation — the portfolio decision across an audience.

WHAT WAS WRONG. `optimizer.select_best()` scores ONE customer in isolation and
returns their highest-EIV feasible action. That is correct for one customer and
wrong for a campaign, because customers are not independent: they compete for a
shared discount budget and shared shelf stock. Two consequences, both provable
and both silent:

  BUDGET. Under a binding budget, ranking by EIV is the wrong objective. Paying
  for the highest-EIV action for each customer in turn until the money runs out
  is the classic fractional-knapsack error. The correct ranking is EIV DENSITY —
  value per AED committed — and the two orderings differ whenever cost varies
  across candidates, which the discount ladder guarantees.

  STOCK. ATP is checked per decision against current availability, so with
  customers processed sequentially a scarce SKU is consumed by whoever happened
  to be scored first rather than by whoever earns the most margin from it.
  ITERATION ORDER WAS SILENTLY DECIDING ALLOCATION. Nobody chose that policy and
  nothing surfaced it.

THE ALGORITHM, AND WHY NOT THE OBVIOUS ONE.

The obvious fix — rank every (customer, action) pair by density and take them
greedily — is wrong in a way that matters. With no binding constraint it would
hand every customer their highest-DENSITY action (a cheap 5% nudge) rather than
their highest-EIV action, quietly making unconstrained decisions worse than the
code it replaces. A change that regresses the easy case to improve the hard one
is not an improvement.

So this is the standard greedy for the MULTIPLE-CHOICE KNAPSACK problem, which
is what the real problem is: at most one action per customer, chosen from that
customer's menu, under shared budget and stock.

  1. Every customer starts at NO_ACTION — cost 0, EIV 0.
  2. For each customer, build the EFFICIENT FRONTIER of their candidates: the
     subset where paying more genuinely buys more EIV, with diminishing returns.
     Dominated candidates (cost more, earn less) are discarded up front.
  3. Walking that frontier gives a sequence of UPGRADE STEPS, each with a
     marginal cost and marginal EIV, and — because the frontier is concave — a
     strictly decreasing marginal density.
  4. Pool every customer's steps, sort by marginal density descending, and apply
     them in order while budget and stock allow.

This degrades EXACTLY to the current behaviour when nothing binds: every
customer walks their whole frontier and lands on their highest-EIV action, which
is what `select_best()` would have returned. That equivalence is asserted in
tests/test_flywheel_allocator.py, not merely intended.

DETERMINISM IS A HARD REQUIREMENT. `replay()` must reproduce a stored decision
exactly, and an allocation that depends on dict ordering or float jitter cannot
be replayed or audited. Every sort key here is fully specified down to a unique
tie-breaker, all money stays Decimal, and the inputs are fingerprinted so two
runs over the same audience are provably the same run.

WHAT THIS FILE STILL DOES NOT DO: contain a model. It consumes candidates that
`optimizer.build_candidates()` produced and allocates among them. Models
propose; deterministic policy-checked services dispose.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.services.flywheel.types import (
    ZERO, ActionCandidate, ActionType, STOCK_CONSUMING_ACTIONS, money,
)

logger = logging.getLogger(__name__)

ALLOCATOR_VERSION = "v1"

#: Stock is keyed by the physical location it is drawn from.
StockKey = Tuple[int, int]  # (store_id, item_id)


class AllocReason:
    """Why a candidate was or was not allocated.

    Extends `ReasonCode` rather than joining it: these codes only have meaning
    once allocation is GLOBAL. Under per-customer selection there was no rival
    claim to lose to, so there was nothing for them to describe.
    """
    SELECTED = "SELECTED"
    #: Beaten by a better use of the same scarce resource. The characteristic
    #: portfolio rejection — the action was affordable and in stock, it simply
    #: was not the best thing to spend that AED or that unit on.
    LOST_TO_HIGHER_DENSITY = "LOST_TO_HIGHER_DENSITY"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    STOCK_EXHAUSTED = "STOCK_EXHAUSTED"
    CONTACT_CAP_REACHED = "CONTACT_CAP_REACHED"
    DOMINATED = "DOMINATED"
    NOT_VIABLE = "NOT_VIABLE"


@dataclass(frozen=True)
class Proposal:
    """One customer's menu of candidate actions.

    `candidates` should already have passed the per-customer policy gates in
    `optimizer.select_best()` — the uplift floor, the margin floor, consent. The
    allocator decides between VIABLE options; it does not re-litigate whether an
    option is permitted, because policy belongs in one place.
    """
    customer_id: int
    candidates: Sequence[ActionCandidate]


@dataclass
class Constraints:
    """The shared, scarce resources the audience competes for."""
    #: Remaining discount budget. None = unconstrained (the degradation case).
    budget_aed: Optional[Decimal] = None
    #: Available-to-promise units per (store_id, item_id). Missing key =
    #: unconstrained, which is the right default for non-stock actions.
    stock: Dict[StockKey, int] = field(default_factory=dict)
    #: Actions permitted per customer in this run. >1 is not currently used but
    #: the contact-governance work in migration 076 will want it.
    max_actions_per_customer: int = 1

    def binding_summary(self, spent: Decimal, stock_used: Dict[StockKey, int],
                        blocked: Dict[str, int]) -> str:
        """Which constraint actually bit. Recorded on the run so the UI can say
        'you left margin on the table because you ran out of X'."""
        if blocked.get(AllocReason.BUDGET_EXHAUSTED):
            return "budget"
        if blocked.get(AllocReason.STOCK_EXHAUSTED):
            return "stock"
        if blocked.get(AllocReason.CONTACT_CAP_REACHED):
            return "contact_cap"
        return "none"


@dataclass
class AllocationLine:
    """One customer's outcome in the allocation."""
    customer_id: int
    candidate: Optional[ActionCandidate]
    selected: bool
    eiv_aed: Decimal
    cost_aed: Decimal
    eiv_density: Optional[Decimal]
    reason_code: str

    def to_row(self) -> Dict[str, Any]:
        c = self.candidate
        return {
            "customer_id": self.customer_id,
            "action_type": c.action_type.value if c else ActionType.NO_ACTION.value,
            "item_id": c.item_id if c else None,
            "store_id": c.store_id if c else None,
            "discount_pct": c.discount_pct if c else ZERO,
            "units": c.units if c else 0,
            "eiv_aed": self.eiv_aed,
            "cost_aed": self.cost_aed,
            "eiv_density": self.eiv_density,
            "selected": self.selected,
            "reason_code": self.reason_code,
        }


@dataclass
class AllocationResult:
    mode: str
    lines: List[AllocationLine]
    total_eiv_aed: Decimal
    total_cost_aed: Decimal
    actions_selected: int
    customers_considered: int
    candidates_considered: int
    binding_constraint: str
    input_digest: str
    solver: str = "density_greedy"
    blocked: Dict[str, int] = field(default_factory=dict)

    def to_run_row(self, *, budget_limit: Decimal) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "budget_limit_aed": budget_limit,
            "candidates_considered": self.candidates_considered,
            "customers_considered": self.customers_considered,
            "actions_selected": self.actions_selected,
            "total_eiv_aed": self.total_eiv_aed,
            "total_cost_aed": self.total_cost_aed,
            "binding_constraint": self.binding_constraint,
            "input_digest": self.input_digest,
            "solver": self.solver,
        }


# ---------------------------------------------------------------------------
# Cost model
# ---------------------------------------------------------------------------

def action_cost(candidate: ActionCandidate) -> Decimal:
    """Total AED this action commits.

    Matches `optimizer.select_best`'s internal `total_cost` exactly. If the two
    ever diverge the allocator would be ranking on one number and the budget
    reserving another, and the campaign would silently overspend — so this is
    the single definition and the optimizer's tie-break should be read as
    agreeing with it.
    """
    return money(
        candidate.expected_discount_cost_aed
        + candidate.comms_cost_aed
        + candidate.fulfilment_cost_aed
        + candidate.procurement_cost_aed
    )


def _stock_key(candidate: ActionCandidate) -> Optional[StockKey]:
    """Which stock pool this action draws on, or None if it consumes no stock.

    Non-inventory rewards (reminders, points, free delivery) survive a stockout
    by design — rung (d) of the shortage ladder — so they must not be gated on
    a stock pool they never touch.
    """
    if candidate.action_type not in STOCK_CONSUMING_ACTIONS:
        return None
    if candidate.store_id is None or candidate.item_id is None:
        return None
    return (candidate.store_id, candidate.item_id)


def _tie_break_key(customer_id: int, candidate: ActionCandidate) -> Tuple:
    """A total order over candidates, with NO dependence on iteration order.

    Every field is an explicit value from the candidate itself. Two runs over
    the same audience therefore produce byte-identical allocations, which is
    what makes `replay()` meaningful and an audit possible.
    """
    return (
        customer_id,
        candidate.action_type.value,
        str(candidate.discount_pct),
        candidate.item_id if candidate.item_id is not None else -1,
        candidate.store_id if candidate.store_id is not None else -1,
        candidate.units,
    )


# ---------------------------------------------------------------------------
# Efficient frontier
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Step:
    """One upgrade along a customer's frontier: pay a bit more, earn a bit more."""
    customer_id: int
    from_index: int          # position on the frontier before this step
    to_index: int            # position after
    candidate: ActionCandidate
    delta_cost: Decimal
    delta_eiv: Decimal
    density: Decimal
    sort_key: Tuple


def _efficient_frontier(
    customer_id: int, candidates: Sequence[ActionCandidate]
) -> Tuple[List[ActionCandidate], List[ActionCandidate]]:
    """Split a customer's menu into the frontier and the dominated remainder.

    A candidate is DOMINATED when another costs no more and earns at least as
    much — there is no budget under which the dominated one is the right pick,
    so carrying it forward would only add noise to the ranking.

    The surviving frontier is made CONCAVE: if paying for step B yields a better
    marginal return than the cheaper step A before it, then A was never worth
    stopping at and is removed. Concavity is what guarantees each customer's
    upgrades appear in the global density ordering in the correct sequence,
    which is what lets a single sorted pass do the right thing.
    """
    viable = [
        c for c in candidates
        if c.feasible and c.action_type != ActionType.NO_ACTION and c.eiv_aed > ZERO
    ]
    if not viable:
        return [], []

    # Deterministic pre-sort: cheapest first, then highest EIV, then the total
    # order. Without this the frontier could depend on input ordering.
    ordered = sorted(viable, key=lambda c: (action_cost(c), -c.eiv_aed,
                                            _tie_break_key(customer_id, c)))

    frontier: List[ActionCandidate] = []
    dominated: List[ActionCandidate] = []

    for cand in ordered:
        cost, eiv = action_cost(cand), cand.eiv_aed
        # Dominated by something already on the frontier (costs >=, earns <=).
        if frontier and eiv <= frontier[-1].eiv_aed:
            dominated.append(cand)
            continue
        # Enforce concavity: drop trailing frontier points whose marginal return
        # is worse than this new point's, measured from their own predecessor.
        while len(frontier) >= 1:
            prev = frontier[-1]
            base_cost = action_cost(frontier[-2]) if len(frontier) >= 2 else ZERO
            base_eiv = frontier[-2].eiv_aed if len(frontier) >= 2 else ZERO

            prev_dc = action_cost(prev) - base_cost
            prev_de = prev.eiv_aed - base_eiv
            new_dc = cost - base_cost
            new_de = eiv - base_eiv
            if prev_dc <= ZERO or new_dc <= ZERO:
                break
            # Cross-multiply instead of dividing: exact in Decimal, and avoids
            # a division-by-zero branch on free actions.
            if new_de * prev_dc > prev_de * new_dc:
                dominated.append(frontier.pop())
                continue
            break
        frontier.append(cand)

    return frontier, dominated


def _steps_for(customer_id: int, frontier: Sequence[ActionCandidate]) -> List[_Step]:
    """Turn a frontier into upgrade steps with marginal densities."""
    steps: List[_Step] = []
    prev_cost, prev_eiv = ZERO, ZERO
    for idx, cand in enumerate(frontier):
        cost, eiv = action_cost(cand), cand.eiv_aed
        delta_cost = money(cost - prev_cost)
        delta_eiv = money(eiv - prev_eiv)
        if delta_eiv <= ZERO:
            prev_cost, prev_eiv = cost, eiv
            continue
        # A free action with positive EIV is infinite density — take it before
        # anything that costs money. Representing that as a large finite number
        # keeps the sort total and avoids special-casing inf in Decimal.
        density = (money(delta_eiv / delta_cost) if delta_cost > ZERO
                   else Decimal("999999999.99"))
        steps.append(_Step(
            customer_id=customer_id, from_index=idx - 1, to_index=idx,
            candidate=cand, delta_cost=delta_cost, delta_eiv=delta_eiv,
            density=density, sort_key=_tie_break_key(customer_id, cand),
        ))
        prev_cost, prev_eiv = cost, eiv
    return steps


# ---------------------------------------------------------------------------
# The allocator
# ---------------------------------------------------------------------------

def allocate(
    proposals: Sequence[Proposal], *, constraints: Constraints,
    mode: str = "portfolio",
) -> AllocationResult:
    """Allocate actions across the whole audience under shared constraints.

    `mode='greedy'` reproduces the legacy per-customer behaviour (each customer
    takes their highest-EIV feasible action, first-come-first-served on stock
    and budget) so the two can be compared on identical inputs. That comparison
    is the entire justification for this module, so it must be measurable rather
    than argued.
    """
    if mode not in ("portfolio", "greedy"):
        raise ValueError(f"unknown allocation mode: {mode}")

    digest = _fingerprint(proposals, constraints)
    if mode == "greedy":
        return _allocate_greedy(proposals, constraints, digest)
    return _allocate_portfolio(proposals, constraints, digest)


def _allocate_portfolio(
    proposals: Sequence[Proposal], constraints: Constraints, digest: str,
) -> AllocationResult:
    remaining = constraints.budget_aed
    stock = dict(constraints.stock)

    # current[customer] = the candidate they hold right now (None = NO_ACTION)
    current: Dict[int, Optional[ActionCandidate]] = {}
    position: Dict[int, int] = {}
    dominated_by_customer: Dict[int, List[ActionCandidate]] = {}
    all_steps: List[_Step] = []
    candidates_considered = 0

    for proposal in proposals:
        candidates_considered += len(proposal.candidates)
        frontier, dominated = _efficient_frontier(proposal.customer_id, proposal.candidates)
        dominated_by_customer[proposal.customer_id] = dominated
        current[proposal.customer_id] = None
        position[proposal.customer_id] = -1
        all_steps.extend(_steps_for(proposal.customer_id, frontier))

    # THE RANKING. Marginal density descending; every tie broken deterministically.
    all_steps.sort(key=lambda s: (-s.density, -s.delta_eiv, s.sort_key))

    blocked: Dict[str, int] = {}
    reason_by_customer: Dict[int, str] = {}

    for step in all_steps:
        # Steps are applied in frontier order per customer. Concavity guarantees
        # a customer's cheaper step always sorts ahead of their dearer one, so
        # this only skips steps whose prerequisite was itself blocked.
        if position[step.customer_id] != step.from_index:
            continue

        if constraints.max_actions_per_customer < 1:
            blocked[AllocReason.CONTACT_CAP_REACHED] = \
                blocked.get(AllocReason.CONTACT_CAP_REACHED, 0) + 1
            reason_by_customer.setdefault(step.customer_id, AllocReason.CONTACT_CAP_REACHED)
            continue

        # --- budget ---
        if remaining is not None and step.delta_cost > remaining:
            blocked[AllocReason.BUDGET_EXHAUSTED] = \
                blocked.get(AllocReason.BUDGET_EXHAUSTED, 0) + 1
            # Do NOT break. A cheaper step further down the ranking may still
            # fit, and stopping here would leave budget unspent — first-fit
            # decreasing, not first-fail-stop.
            reason_by_customer.setdefault(step.customer_id, AllocReason.BUDGET_EXHAUSTED)
            continue

        # --- stock ---
        key = _stock_key(step.candidate)
        prior = current[step.customer_id]
        prior_key = _stock_key(prior) if prior else None
        if key is not None and key in stock:
            # An upgrade releases the units its predecessor held before taking
            # its own; without this, moving 5% -> 10% on the same SKU would be
            # charged for stock twice and spuriously fail.
            released = prior.units if (prior_key == key and prior) else 0
            if stock[key] + released < step.candidate.units:
                blocked[AllocReason.STOCK_EXHAUSTED] = \
                    blocked.get(AllocReason.STOCK_EXHAUSTED, 0) + 1
                reason_by_customer.setdefault(step.customer_id, AllocReason.STOCK_EXHAUSTED)
                continue

        # --- apply ---
        if prior_key is not None and prior_key in stock and prior is not None:
            stock[prior_key] += prior.units
        if key is not None and key in stock:
            stock[key] -= step.candidate.units
        if remaining is not None:
            remaining = money(remaining - step.delta_cost)

        current[step.customer_id] = step.candidate
        position[step.customer_id] = step.to_index
        reason_by_customer[step.customer_id] = AllocReason.SELECTED

    return _build_result(
        mode="portfolio", proposals=proposals, current=current,
        dominated_by_customer=dominated_by_customer,
        reason_by_customer=reason_by_customer, blocked=blocked,
        constraints=constraints, digest=digest,
        candidates_considered=candidates_considered,
    )


def _allocate_greedy(
    proposals: Sequence[Proposal], constraints: Constraints, digest: str,
) -> AllocationResult:
    """The legacy path, reproduced faithfully so the comparison is honest.

    Each customer, in the order given, takes their highest-EIV feasible action
    if budget and stock happen to still allow it. This is what the product does
    today — including its dependence on iteration order, which is precisely the
    behaviour the portfolio allocator exists to replace. Reproducing the flaw
    rather than a flattering approximation of it is the point.
    """
    remaining = constraints.budget_aed
    stock = dict(constraints.stock)
    current: Dict[int, Optional[ActionCandidate]] = {}
    reason_by_customer: Dict[int, str] = {}
    blocked: Dict[str, int] = {}
    candidates_considered = 0

    for proposal in proposals:
        candidates_considered += len(proposal.candidates)
        cid = proposal.customer_id
        current[cid] = None

        viable = [c for c in proposal.candidates
                  if c.feasible and c.action_type != ActionType.NO_ACTION
                  and c.eiv_aed > ZERO]
        if not viable:
            reason_by_customer[cid] = AllocReason.NOT_VIABLE
            continue

        # Highest EIV, cheapest on ties — optimizer.select_best rule 3 and 4.
        best = min(viable, key=lambda c: (-c.eiv_aed, action_cost(c),
                                          _tie_break_key(cid, c)))
        cost = action_cost(best)

        if remaining is not None and cost > remaining:
            blocked[AllocReason.BUDGET_EXHAUSTED] = \
                blocked.get(AllocReason.BUDGET_EXHAUSTED, 0) + 1
            reason_by_customer[cid] = AllocReason.BUDGET_EXHAUSTED
            continue

        key = _stock_key(best)
        if key is not None and key in stock and stock[key] < best.units:
            blocked[AllocReason.STOCK_EXHAUSTED] = \
                blocked.get(AllocReason.STOCK_EXHAUSTED, 0) + 1
            reason_by_customer[cid] = AllocReason.STOCK_EXHAUSTED
            continue

        if key is not None and key in stock:
            stock[key] -= best.units
        if remaining is not None:
            remaining = money(remaining - cost)
        current[cid] = best
        reason_by_customer[cid] = AllocReason.SELECTED

    return _build_result(
        mode="greedy", proposals=proposals, current=current,
        dominated_by_customer={}, reason_by_customer=reason_by_customer,
        blocked=blocked, constraints=constraints, digest=digest,
        candidates_considered=candidates_considered,
    )


def _build_result(
    *, mode: str, proposals: Sequence[Proposal],
    current: Dict[int, Optional[ActionCandidate]],
    dominated_by_customer: Dict[int, List[ActionCandidate]],
    reason_by_customer: Dict[int, str], blocked: Dict[str, int],
    constraints: Constraints, digest: str, candidates_considered: int,
) -> AllocationResult:
    lines: List[AllocationLine] = []
    total_eiv, total_cost = ZERO, ZERO

    for proposal in proposals:
        cid = proposal.customer_id
        chosen = current.get(cid)
        if chosen is not None:
            cost = action_cost(chosen)
            total_eiv = money(total_eiv + chosen.eiv_aed)
            total_cost = money(total_cost + cost)
            lines.append(AllocationLine(
                customer_id=cid, candidate=chosen, selected=True,
                eiv_aed=chosen.eiv_aed, cost_aed=cost,
                eiv_density=(money(chosen.eiv_aed / cost) if cost > ZERO else None),
                reason_code=AllocReason.SELECTED,
            ))
        else:
            reason = reason_by_customer.get(cid, AllocReason.LOST_TO_HIGHER_DENSITY)
            lines.append(AllocationLine(
                customer_id=cid, candidate=None, selected=False,
                eiv_aed=ZERO, cost_aed=ZERO, eiv_density=None, reason_code=reason,
            ))

    selected_count = sum(1 for line in lines if line.selected)
    return AllocationResult(
        mode=mode, lines=lines, total_eiv_aed=total_eiv, total_cost_aed=total_cost,
        actions_selected=selected_count, customers_considered=len(proposals),
        candidates_considered=candidates_considered,
        binding_constraint=constraints.binding_summary(total_cost, {}, blocked),
        input_digest=digest, blocked=blocked,
    )


def _fingerprint(proposals: Sequence[Proposal], constraints: Constraints) -> str:
    """Deterministic digest of everything the allocation depends on.

    Two runs with the same digest MUST produce the same allocation. Recorded on
    the run so a replay that disagrees is detectable rather than merely
    suspected — the same discipline `optimizer.replay()` already applies to a
    single decision, lifted to the portfolio.
    """
    hasher = hashlib.blake2b(digest_size=32)
    hasher.update(f"v={ALLOCATOR_VERSION}|budget={constraints.budget_aed}"
                  f"|cap={constraints.max_actions_per_customer}|".encode())
    for key in sorted(constraints.stock):
        hasher.update(f"stock:{key[0]}:{key[1]}={constraints.stock[key]}|".encode())
    for proposal in sorted(proposals, key=lambda p: p.customer_id):
        hasher.update(f"c={proposal.customer_id}|".encode())
        for cand in sorted(proposal.candidates,
                           key=lambda c: _tie_break_key(proposal.customer_id, c)):
            hasher.update(
                f"{cand.action_type.value}:{cand.discount_pct}:{cand.item_id}:"
                f"{cand.store_id}:{cand.units}:{cand.eiv_aed}:"
                f"{action_cost(cand)}:{int(cand.feasible)}|".encode()
            )
    return hasher.hexdigest()


def compare(
    proposals: Sequence[Proposal], *, constraints: Constraints,
) -> Dict[str, Any]:
    """Run both allocators on identical inputs and report the delta.

    This is the number that justifies the work: total EIV the portfolio
    allocator found that per-customer greedy left on the table. It is reported
    even when zero — a shadow run that quietly stopped proving its worth should
    be visible, not silently reassuring.
    """
    portfolio = allocate(proposals, constraints=constraints, mode="portfolio")
    greedy = allocate(proposals, constraints=constraints, mode="greedy")
    delta = money(portfolio.total_eiv_aed - greedy.total_eiv_aed)

    return {
        "portfolio": portfolio,
        "greedy": greedy,
        "eiv_delta_aed": delta,
        "cost_delta_aed": money(portfolio.total_cost_aed - greedy.total_cost_aed),
        "actions_delta": portfolio.actions_selected - greedy.actions_selected,
        "binding_constraint": portfolio.binding_constraint,
        "digests_match": portfolio.input_digest == greedy.input_digest,
        "note": (
            "Positive eiv_delta_aed is margin the per-customer path left behind. "
            "Zero is the CORRECT answer when no constraint binds — the allocator "
            "must not differ from the current behaviour in the easy case."
        ),
    }
