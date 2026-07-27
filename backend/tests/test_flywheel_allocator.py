"""Global constrained allocation — the properties that make it safe to ship.

Three claims, in order of how badly a violation would hurt:

  1. DEGRADATION. With no binding constraint the portfolio allocator must
     produce EXACTLY what per-customer greedy produces. A change that improves
     the constrained case by regressing the unconstrained one is not an
     improvement, and this is the property most likely to break silently under
     a "small" ranking tweak.

  2. IMPROVEMENT. Under a binding budget it must beat greedy, because greedy
     ranks on EIV where the correct ranking is EIV per AED.

  3. DETERMINISM. The same audience must produce the same allocation regardless
     of input ordering. Without this `replay()` is meaningless and no allocation
     can be audited.
"""
from __future__ import annotations

import random
from decimal import Decimal

import pytest

from app.services.flywheel.allocator import (
    AllocReason, Constraints, Proposal, action_cost, allocate, compare,
)
from app.services.flywheel.types import ZERO, ActionCandidate, ActionType, money


def candidate(*, eiv: str, cost: str, item_id: int = 1, store_id: int = 1,
              discount: str = "10", units: int = 1,
              action: ActionType = ActionType.PERCENT_DISCOUNT) -> ActionCandidate:
    """Build a candidate with an exact EIV and an exact cost.

    `eiv_aed` is a derived property, so the retained-value term is set to
    (eiv + cost) to land the subtraction on the intended figure — the same path
    the real optimizer takes, rather than stubbing the property.
    """
    c = ActionCandidate(
        action_type=action, item_id=item_id, store_id=store_id,
        discount_pct=Decimal(discount), units=units, uplift=0.05,
    )
    c.expected_retained_value_aed = money(Decimal(eiv) + Decimal(cost))
    c.expected_discount_cost_aed = money(Decimal(cost))
    return c


# ---------------------------------------------------------------------------
# 1. Degradation — the easy case must not regress
# ---------------------------------------------------------------------------

def test_unconstrained_portfolio_equals_greedy():
    proposals = [
        Proposal(customer_id=1, candidates=[
            candidate(eiv="10.00", cost="5.00", discount="5"),
            candidate(eiv="18.00", cost="20.00", discount="10"),
            candidate(eiv="22.00", cost="50.00", discount="20"),
        ]),
        Proposal(customer_id=2, candidates=[
            candidate(eiv="4.00", cost="2.00", discount="5", item_id=2),
            candidate(eiv="9.00", cost="12.00", discount="10", item_id=2),
        ]),
    ]
    result = compare(proposals, constraints=Constraints(budget_aed=None))
    assert result["eiv_delta_aed"] == ZERO
    assert result["portfolio"].total_eiv_aed == result["greedy"].total_eiv_aed
    assert result["portfolio"].binding_constraint == "none"


def test_unconstrained_gives_each_customer_their_highest_eiv_action():
    """Not their highest-DENSITY action. A pure density ranking would hand
    everyone the cheap 5% nudge and quietly make unconstrained decisions worse
    than the code it replaces."""
    proposals = [Proposal(customer_id=1, candidates=[
        candidate(eiv="10.00", cost="1.00", discount="5"),    # density 10.0
        candidate(eiv="25.00", cost="50.00", discount="20"),  # density 0.5, best EIV
    ])]
    result = allocate(proposals, constraints=Constraints(budget_aed=None))
    selected = [line for line in result.lines if line.selected]
    assert len(selected) == 1
    assert selected[0].eiv_aed == money("25.00")
    assert selected[0].candidate is not None
    assert selected[0].candidate.discount_pct == Decimal("20")


@pytest.mark.parametrize("seed", [1, 7, 42, 99])
def test_degradation_holds_on_random_audiences(seed):
    rng = random.Random(seed)
    proposals = []
    for cid in range(1, 40):
        base = rng.uniform(20, 200)
        cands = []
        for pct_off in (5, 10, 20):
            cost = base * pct_off / 100
            eiv = base * (pct_off ** 0.6) / 12
            cands.append(candidate(eiv=f"{eiv:.2f}", cost=f"{cost:.2f}",
                                   discount=str(pct_off),
                                   item_id=rng.randint(1, 8),
                                   store_id=rng.randint(1, 3)))
        proposals.append(Proposal(customer_id=cid, candidates=cands))

    result = compare(proposals, constraints=Constraints(budget_aed=None))
    assert result["eiv_delta_aed"] == ZERO, (
        "portfolio diverged from greedy with no binding constraint")


# ---------------------------------------------------------------------------
# 2. Improvement — the hard case must actually be better
# ---------------------------------------------------------------------------

def test_binding_budget_portfolio_beats_greedy():
    """The fractional-knapsack error, in miniature.

    Greedy takes customer 1's best action (EIV 20 for 50 AED) and has nothing
    left. The portfolio path buys two cheap high-density actions instead and
    ends up ahead on total EIV.
    """
    proposals = [
        Proposal(customer_id=1, candidates=[
            candidate(eiv="8.00", cost="10.00", discount="5"),
            candidate(eiv="20.00", cost="50.00", discount="20"),
        ]),
        Proposal(customer_id=2, candidates=[
            candidate(eiv="9.00", cost="10.00", discount="5", item_id=2),
        ]),
        Proposal(customer_id=3, candidates=[
            candidate(eiv="9.50", cost="10.00", discount="5", item_id=3),
        ]),
    ]
    result = compare(proposals, constraints=Constraints(budget_aed=money("30.00")))
    assert result["eiv_delta_aed"] > ZERO
    assert result["portfolio"].total_eiv_aed > result["greedy"].total_eiv_aed
    assert result["portfolio"].binding_constraint == "budget"


def test_portfolio_never_exceeds_the_budget():
    rng = random.Random(3)
    proposals = [
        Proposal(customer_id=cid, candidates=[
            candidate(eiv=f"{rng.uniform(1, 30):.2f}", cost=f"{rng.uniform(1, 40):.2f}",
                      discount="10", item_id=rng.randint(1, 5))
        ])
        for cid in range(1, 60)
    ]
    budget = money("100.00")
    result = allocate(proposals, constraints=Constraints(budget_aed=budget))
    assert result.total_cost_aed <= budget


def test_budget_exhaustion_does_not_stop_the_scan():
    """First-fit decreasing, not first-fail-stop.

    An expensive action that does not fit must not prevent a later cheap one
    from being taken — otherwise the allocator leaves budget unspent and
    customers unserved for no reason.
    """
    proposals = [
        Proposal(customer_id=1, candidates=[candidate(eiv="50.00", cost="90.00")]),
        Proposal(customer_id=2, candidates=[candidate(eiv="5.00", cost="5.00", item_id=2)]),
    ]
    result = allocate(proposals, constraints=Constraints(budget_aed=money("10.00")))
    selected = {line.customer_id for line in result.lines if line.selected}
    assert 2 in selected, "cheap affordable action was skipped after a dear one failed"


# ---------------------------------------------------------------------------
# Stock
# ---------------------------------------------------------------------------

def test_stock_goes_to_the_highest_value_claim_not_the_first_scored():
    """The silent bug: under sequential per-customer scoring a scarce SKU went
    to whoever happened to be processed first."""
    proposals = [
        Proposal(customer_id=1, candidates=[
            candidate(eiv="2.00", cost="1.00", item_id=7, store_id=1)]),
        Proposal(customer_id=2, candidates=[
            candidate(eiv="30.00", cost="1.00", item_id=7, store_id=1)]),
    ]
    constraints = Constraints(budget_aed=None, stock={(1, 7): 1})
    result = allocate(proposals, constraints=constraints)
    selected = [line for line in result.lines if line.selected]
    assert len(selected) == 1
    assert selected[0].customer_id == 2, "the single unit did not go to the best claim"


def test_non_stock_actions_survive_a_stockout():
    """Reminders and points consume no shelf stock — rung (d) of the shortage
    ladder. Gating them on a stock pool they never touch would be wrong."""
    proposals = [Proposal(customer_id=1, candidates=[
        candidate(eiv="5.00", cost="0.05", action=ActionType.REMINDER,
                  item_id=7, store_id=1)])]
    constraints = Constraints(budget_aed=None, stock={(1, 7): 0})
    result = allocate(proposals, constraints=constraints)
    assert any(line.selected for line in result.lines)


def test_upgrade_releases_the_units_it_previously_held():
    """Moving a customer from 5% to 10% on the SAME sku must not be charged for
    stock twice, which would spuriously fail on a tight pool."""
    proposals = [Proposal(customer_id=1, candidates=[
        candidate(eiv="5.00", cost="2.00", discount="5", item_id=7, units=1),
        candidate(eiv="12.00", cost="6.00", discount="10", item_id=7, units=1),
    ])]
    constraints = Constraints(budget_aed=None, stock={(1, 7): 1})
    result = allocate(proposals, constraints=constraints)
    selected = [line for line in result.lines if line.selected]
    assert len(selected) == 1
    assert selected[0].eiv_aed == money("12.00"), "upgrade was blocked by its own units"


# ---------------------------------------------------------------------------
# 3. Determinism
# ---------------------------------------------------------------------------

def test_allocation_is_independent_of_input_order():
    rng = random.Random(5)
    proposals = [
        Proposal(customer_id=cid, candidates=[
            candidate(eiv=f"{rng.uniform(1, 30):.2f}", cost=f"{rng.uniform(1, 20):.2f}",
                      discount="10", item_id=rng.randint(1, 4))
        ])
        for cid in range(1, 40)
    ]
    constraints = Constraints(budget_aed=money("120.00"))

    first = allocate(proposals, constraints=constraints)
    shuffled = proposals[:]
    random.Random(99).shuffle(shuffled)
    second = allocate(shuffled, constraints=constraints)

    assert first.input_digest == second.input_digest
    assert first.total_eiv_aed == second.total_eiv_aed
    assert first.actions_selected == second.actions_selected
    assert ({l.customer_id for l in first.lines if l.selected}
            == {l.customer_id for l in second.lines if l.selected})


def test_digest_changes_when_the_budget_changes():
    """A digest that ignored a constraint would let two genuinely different
    allocations claim to be the same run."""
    proposals = [Proposal(customer_id=1, candidates=[candidate(eiv="5.00", cost="1.00")])]
    a = allocate(proposals, constraints=Constraints(budget_aed=money("10.00")))
    b = allocate(proposals, constraints=Constraints(budget_aed=money("20.00")))
    assert a.input_digest != b.input_digest


# ---------------------------------------------------------------------------
# Accounting
# ---------------------------------------------------------------------------

def test_every_customer_appears_in_the_result_exactly_once():
    """No customer may be silently dropped. An allocation that omits people is
    indistinguishable from one that refused them, and the difference matters."""
    proposals = [
        Proposal(customer_id=cid, candidates=[candidate(eiv="5.00", cost="20.00")])
        for cid in range(1, 11)
    ]
    result = allocate(proposals, constraints=Constraints(budget_aed=money("25.00")))
    assert len(result.lines) == 10
    assert len({line.customer_id for line in result.lines}) == 10


def test_unselected_lines_carry_a_reason():
    proposals = [
        Proposal(customer_id=cid, candidates=[candidate(eiv="5.00", cost="20.00")])
        for cid in range(1, 6)
    ]
    result = allocate(proposals, constraints=Constraints(budget_aed=money("20.00")))
    for line in result.lines:
        if not line.selected:
            assert line.reason_code
            assert line.reason_code != AllocReason.SELECTED


def test_infeasible_and_zero_eiv_candidates_are_never_selected():
    infeasible = candidate(eiv="50.00", cost="1.00")
    infeasible.feasible = False
    worthless = candidate(eiv="0.00", cost="1.00", item_id=2)

    proposals = [Proposal(customer_id=1, candidates=[infeasible, worthless])]
    result = allocate(proposals, constraints=Constraints(budget_aed=None))
    assert not any(line.selected for line in result.lines)


def test_totals_match_the_selected_lines():
    """The reported totals must be the sum of what was actually selected — a
    header that disagrees with its own table is how a dashboard loses trust."""
    rng = random.Random(17)
    proposals = [
        Proposal(customer_id=cid, candidates=[
            candidate(eiv=f"{rng.uniform(1, 20):.2f}", cost=f"{rng.uniform(1, 10):.2f}",
                      item_id=rng.randint(1, 3))])
        for cid in range(1, 25)
    ]
    result = allocate(proposals, constraints=Constraints(budget_aed=money("60.00")))
    assert result.total_eiv_aed == money(
        sum((l.eiv_aed for l in result.lines if l.selected), ZERO))
    assert result.total_cost_aed == money(
        sum((l.cost_aed for l in result.lines if l.selected), ZERO))
    assert result.actions_selected == sum(1 for l in result.lines if l.selected)


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        allocate([], constraints=Constraints(), mode="magic")
