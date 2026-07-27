"""Operations Copilot — output contract tests.

The property under test throughout: a recommendation cannot claim anything it
cannot trace. Unsupported proposals must fail validation rather than reach a
human approver, and LLM prose must not be able to smuggle in a number.
"""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.services.operations.contracts import (
    ActionType,
    EvidenceItem,
    Hypothesis,
    MeasuredFact,
    OperationsRecommendation,
    ProposedAction,
    RunStatus,
    SourceType,
    TERMINAL_RUN_STATUSES,
    ungrounded_numbers,
)

NOW = datetime.now(timezone.utc)


def _evidence(evidence_id="e1", current=120.0, comparison=200.0, unit="units"):
    return EvidenceItem(
        evidence_id=evidence_id,
        metric_name="units_sold_7d",
        current_value=current,
        comparison_value=comparison,
        unit=unit,
        source_type=SourceType.SALES_FACT,
        source_reference="sales_fact_view",
        observed_at=NOW,
    )


def _action(**kw):
    defaults = dict(
        action_type=ActionType.INVESTIGATION_TASK,
        title="Investigate the drop",
        description="Bounded checklist for the store manager.",
        required_approval_role="store_manager",
        evidence_ids=["e1"],
    )
    defaults.update(kw)
    return ProposedAction(**defaults)


def _recommendation(**kw):
    defaults = dict(
        run_id=1, tenant_id=1, title="Category slump",
        evidence=[_evidence()], proposed_actions=[_action()],
    )
    defaults.update(kw)
    return OperationsRecommendation(**defaults)


class TestEvidenceTraceability:
    def test_valid_recommendation_builds(self):
        rec = _recommendation()
        assert rec.is_actionable
        assert rec.payload_version and rec.graph_version and rec.prompt_version

    def test_action_without_evidence_is_rejected(self):
        with pytest.raises(ValidationError, match="no evidence"):
            _recommendation(proposed_actions=[_action(evidence_ids=[])])

    def test_action_citing_unknown_evidence_is_rejected(self):
        with pytest.raises(ValidationError, match="unknown evidence"):
            _recommendation(proposed_actions=[_action(evidence_ids=["ghost"])])

    def test_measured_fact_citing_unknown_evidence_is_rejected(self):
        with pytest.raises(ValidationError, match="unknown evidence"):
            _recommendation(measured_facts=[
                MeasuredFact(statement="Sales fell 40%", evidence_ids=["nope"])])

    def test_measured_fact_requires_at_least_one_citation(self):
        with pytest.raises(ValidationError):
            MeasuredFact(statement="Sales fell", evidence_ids=[])

    def test_hypothesis_needs_no_evidence_but_must_not_invent_ids(self):
        rec = _recommendation(hypotheses=[
            Hypothesis(statement="A competitor opened nearby",
                       check="Compare footfall week over week")])
        assert rec.hypotheses[0].supporting_evidence_ids == []
        with pytest.raises(ValidationError, match="unknown evidence"):
            _recommendation(hypotheses=[
                Hypothesis(statement="x", supporting_evidence_ids=["ghost"])])


class TestRefusalIsValid:
    def test_refusal_with_no_actions_is_a_valid_outcome(self):
        rec = _recommendation(proposed_actions=[],
                              refusal_reason="inventory evidence is stale")
        assert not rec.is_actionable
        assert rec.refusal_reason

    def test_refusal_and_actions_together_is_rejected(self):
        """A refused run must never carry an approvable proposal — a consumer that
        iterates proposed_actions must not build one from a refusal."""
        with pytest.raises(ValidationError, match="refused"):
            _recommendation(refusal_reason="stale evidence")   # _recommendation adds an action

    def test_unknown_expected_effect_is_the_default(self):
        assert _action().expected_effect == "unknown"


class TestNarrativeBoundary:
    """The LLM boundary type carries prose only — never evidence or numbers-as-fields."""

    def test_narrative_has_no_evidence_or_confidence_fields(self):
        from app.services.operations.contracts import NarrativeDraft
        fields = set(NarrativeDraft.model_fields)
        assert "evidence" not in fields
        assert "confidence" not in fields
        assert "severity" not in fields
        assert "measurement_plan" not in fields

    def test_smuggled_extra_fields_are_ignored(self):
        from app.services.operations.contracts import NarrativeDraft
        nd = NarrativeDraft.model_validate({
            "title": "x", "confidence": 0.99, "evidence": [{"anything": 1}],
            "measured_fact_statements": ["sales fell to 120"],
        })
        assert not hasattr(nd, "confidence") or "confidence" not in nd.model_dump()
        assert "confidence" not in nd.model_dump()

    def test_free_text_gathers_every_prose_field(self):
        from app.services.operations.contracts import NarrativeDraft, NarrativeHypothesis
        nd = NarrativeDraft(title="T", executive_summary="S",
                            measured_fact_statements=["fact 120"],
                            hypotheses=[NarrativeHypothesis(statement="H", check="C")],
                            assumptions=["A"], risks=["R"])
        text = nd.free_text()
        for token in ("T", "S", "fact 120", "H", "C", "A", "R"):
            assert token in text


class TestActionAllowlist:
    def test_only_three_action_types_exist(self):
        assert {a.value for a in ActionType} == {
            "replenishment_draft", "stock_transfer_draft", "investigation_task"}

    @pytest.mark.parametrize("forbidden", [
        "price_change", "promotion_change", "supplier_email",
        "employee_discipline", "terminate_employee",
    ])
    def test_forbidden_action_types_cannot_be_constructed(self, forbidden):
        with pytest.raises(ValidationError):
            _action(action_type=forbidden)


class TestTerminalStatuses:
    def test_terminal_set_is_closed(self):
        assert RunStatus.COMPLETED in TERMINAL_RUN_STATUSES
        assert RunStatus.REFUSED in TERMINAL_RUN_STATUSES
        assert RunStatus.ANALYZING not in TERMINAL_RUN_STATUSES
        assert RunStatus.AWAITING_APPROVAL not in TERMINAL_RUN_STATUSES

    def test_every_status_is_either_terminal_or_transitional(self):
        for status in RunStatus:
            assert (status in TERMINAL_RUN_STATUSES) or status in {
                RunStatus.ANALYZING, RunStatus.AWAITING_APPROVAL,
                RunStatus.EXECUTING, RunStatus.MEASURING}


class TestUngroundedNumbers:
    """The mechanical defence: prose may summarise evidence, never mint numbers."""

    def test_numbers_present_in_evidence_are_grounded(self):
        ev = [_evidence(current=120.0, comparison=200.0)]
        assert ungrounded_numbers("Sales fell from 200 to 120 units.", ev) == []

    def test_invented_number_is_caught(self):
        ev = [_evidence(current=120.0, comparison=200.0)]
        found = ungrounded_numbers("This will save 4500 AED next month.", ev)
        assert "4500" in found

    def test_small_ordinals_are_allowed(self):
        ev = [_evidence()]
        # Years are no longer auto-allowed (that window was a smuggling hole);
        # the caller passes the real year via extra_allowed.
        assert ungrounded_numbers("In 2026 the top 3 stores over 14 days.", ev,
                                  extra_allowed=[2026]) == []

    def test_thousands_separator_is_normalised(self):
        ev = [_evidence(current=12000.0, comparison=None)]
        assert ungrounded_numbers("Down to 12,000 units.", ev) == []

    def test_rounded_form_of_an_evidence_value_is_grounded(self):
        ev = [_evidence(current=119.6, comparison=None)]
        assert ungrounded_numbers("About 120 units remain.", ev) == []

    def test_extra_allowed_values_cover_calculator_outputs(self):
        ev = [_evidence(current=120.0, comparison=200.0)]
        assert ungrounded_numbers("Order 350 units.", ev, extra_allowed=[350]) == []
        assert ungrounded_numbers("Order 350 units.", ev) == ["350"]

    def test_empty_narrative_is_safe(self):
        assert ungrounded_numbers("", [_evidence()]) == []
        assert ungrounded_numbers(None, [_evidence()]) == []

    # --- the smuggling holes the review found ---------------------------------

    def test_space_separated_thousands_cannot_hide_a_magnitude(self):
        ev = [_evidence(current=120.0, comparison=200.0)]
        found = ungrounded_numbers("This saves 25 000 AED next month.", ev)
        assert found and "25 000" in found[0].replace(" ", " ")

    def test_k_and_m_suffixes_are_caught(self):
        ev = [_evidence(current=120.0, comparison=200.0)]
        assert ungrounded_numbers("saves 12k AED", ev)
        assert ungrounded_numbers("uplift of 3M dirhams", ev)

    def test_currency_adjacent_small_number_is_a_claim_not_an_ordinal(self):
        ev = [_evidence(current=120.0, comparison=200.0)]
        assert ungrounded_numbers("save 25 AED per unit", ev)      # 25 ≤31 but $-adjacent
        assert ungrounded_numbers("this order costs 1999 AED", ev)  # was in the year window

    def test_percent_adjacent_number_must_be_grounded(self):
        ev = [_evidence(current=120.0, comparison=200.0)]
        assert ungrounded_numbers("reduce stockouts by 30%", ev)

    def test_grounded_percent_passes(self):
        # 40 is a real evidence-derived delta passed via extra_allowed
        ev = [_evidence(current=120.0, comparison=200.0)]
        assert ungrounded_numbers("sales fell 40%", ev, extra_allowed=[40]) == []

    def test_neutral_units_keep_the_ordinal_allowance(self):
        ev = [_evidence()]
        assert ungrounded_numbers("the top 3 stores over 14 days", ev) == []

    def test_no_year_allowlist_years_need_grounding(self):
        """The 1900-2100 window is gone — a four-digit money figure can't hide as
        a 'year'. Genuine years are passed via extra_allowed by the caller."""
        ev = [_evidence(current=120.0, comparison=200.0)]
        assert ungrounded_numbers("you will lose 2050 AED daily", ev)
        assert ungrounded_numbers("in 2026 the trend continues", ev,
                                  extra_allowed=[2026]) == []


class TestEvidenceItem:
    def test_naive_timestamp_is_coerced_to_utc(self):
        item = EvidenceItem(
            evidence_id="e", metric_name="m", current_value=1.0, unit="units",
            source_type=SourceType.DERIVED_ESTIMATE, source_reference="x",
            observed_at=datetime(2026, 7, 1, 12, 0, 0),
        )
        assert item.observed_at.tzinfo is not None

    def test_source_type_labels_derived_estimates_distinctly(self):
        assert SourceType.DERIVED_ESTIMATE.value == "derived"
        assert SourceType.INVENTORY_TABLE.value == "inventory"

    def test_confidence_is_bounded(self):
        with pytest.raises(ValidationError):
            _recommendation(confidence=1.5)
        assert _recommendation(confidence=0.8).confidence == 0.8


def test_measurement_window_bounds():
    from app.services.operations.contracts import MeasurementPlan
    with pytest.raises(ValidationError):
        MeasurementPlan(metric_name="m", unit="units", window_days=0,
                        success_criterion="c")
    plan = MeasurementPlan(metric_name="days_of_cover", unit="days", window_days=14,
                           success_criterion="days of cover above reorder point")
    assert plan.window_days == 14
    assert plan.baseline_value is None      # unknown baseline is explicit, not zero


def test_stale_evidence_timestamp_is_representable():
    old = _evidence()
    old.observed_at = NOW - timedelta(days=30)
    assert old.observed_at < NOW
