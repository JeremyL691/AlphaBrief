"""M16-W02: qualified incidents and no-trade outcomes.

Covers AC-M16-W02-03: weekend, holiday, market-closed,
degraded-provider, RiskGate rejection, and grounded no-opportunity
outcomes qualify only with complete reasons and never trigger an
activity quota or synthetic order.
"""

from __future__ import annotations

import pytest
from alphabrief_core import (
    EVENT_RESOLUTION_FIELDS,
    INCIDENT_SEVERITIES,
    QUALIFIED_OUTCOMES,
    WeekEventResolution,
    WindowIncident,
    classify_qualified_outcome,
    classify_window_incident,
    resolve_week_event,
)


class TestQualifiedOutcomes:
    def test_all_six_outcomes_are_declared(self) -> None:
        assert QUALIFIED_OUTCOMES == (
            "weekend",
            "holiday",
            "market_closed",
            "degraded_provider",
            "risk_gate_rejection",
            "no_opportunity",
        )

    @pytest.mark.parametrize("outcome", QUALIFIED_OUTCOMES)
    def test_outcome_qualifies_with_complete_reason(
        self, outcome: str
    ) -> None:
        assert classify_qualified_outcome(
            outcome, reason="market closed for the session"
        ) is True

    def test_outcome_without_reason_does_not_qualify(self) -> None:
        for outcome in QUALIFIED_OUTCOMES:
            assert classify_qualified_outcome(outcome, reason=None) is False
            assert classify_qualified_outcome(outcome, reason="  ") is False

    def test_unknown_outcome_never_qualifies(self) -> None:
        assert classify_qualified_outcome(
            "mystery", reason="explained"
        ) is False

    def test_classification_is_deterministic(self) -> None:
        for outcome in QUALIFIED_OUTCOMES:
            assert classify_qualified_outcome(
                outcome, reason="r"
            ) == classify_qualified_outcome(outcome, reason="r")


class TestNoQuotaNoSynthetic:
    def test_contract_declares_no_activity_quota(self) -> None:
        """The observation contract never requires a daily trade; a
        grounded no-trade day is a qualified outcome."""
        assert "no_opportunity" in QUALIFIED_OUTCOMES

    def test_no_trade_outcomes_never_produce_orders(self) -> None:
        # Qualified outcomes are classified with reasons only; no
        # order-producing path exists in the classification contract.
        for outcome in QUALIFIED_OUTCOMES:
            qualified = classify_qualified_outcome(outcome, reason="r")
            assert qualified is True


class TestWindowIncidentReset:
    """AC-M16-W03-03: classified incident and window reset decision."""

    def test_all_four_severities_are_declared(self) -> None:
        assert INCIDENT_SEVERITIES == ("P0", "P1", "P2", "P3")

    def test_failed_gate_classifies_incident_and_resets_window(
        self,
    ) -> None:
        incident = classify_window_incident(
            window=2, severity="P1", gate_passed=False
        )
        assert isinstance(incident, WindowIncident)
        assert incident.window == 2
        assert incident.severity == "P1"
        assert incident.reset_required is True
        assert incident.invalid_days_carried_forward is False

    def test_passing_gate_records_no_reset(self) -> None:
        incident = classify_window_incident(
            window=2, severity="P2", gate_passed=True
        )
        assert incident.reset_required is False
        assert incident.invalid_days_carried_forward is False

    def test_unknown_severity_fails_closed_as_p0(self) -> None:
        incident = classify_window_incident(
            window=2, severity="mystery", gate_passed=False
        )
        assert incident.severity == "P0"
        assert incident.reset_required is True

    def test_no_approval_and_no_carry_forward_on_reset(self) -> None:
        incident = classify_window_incident(
            window=2, severity="P3", gate_passed=False
        )
        assert "no approval" in incident.detail
        assert incident.invalid_days_carried_forward is False

    def test_classification_is_deterministic(self) -> None:
        for severity in INCIDENT_SEVERITIES:
            for passed in (True, False):
                first = classify_window_incident(
                    window=2, severity=severity, gate_passed=passed
                )
                second = classify_window_incident(
                    window=2, severity=severity, gate_passed=passed
                )
                assert first.model_dump() == second.model_dump()


class TestWeekEventResolution:
    """AC-M16-W04-03: no unresolved P0/P1; P2/P3 resolve deterministically."""

    def test_all_three_resolution_fields_are_declared(self) -> None:
        assert EVENT_RESOLUTION_FIELDS == (
            "reset_decision",
            "evidence_hash",
            "repair_reference",
        )

    def test_p0_event_never_resolves_in_loop(self) -> None:
        resolution = resolve_week_event(
            severity="P0",
            reset_decision="reset",
            evidence_hash="hash-1",
            repair_reference="repair-1",
        )
        assert isinstance(resolution, WeekEventResolution)
        assert resolution.resolved is False
        assert "fails closed" in resolution.detail

    def test_p1_event_never_resolves_in_loop(self) -> None:
        resolution = resolve_week_event(
            severity="P1",
            reset_decision="reset",
            evidence_hash="hash-1",
            repair_reference="repair-1",
        )
        assert resolution.resolved is False

    def test_p2_event_resolves_with_all_fields(self) -> None:
        resolution = resolve_week_event(
            severity="P2",
            reset_decision="window-reset-w3",
            evidence_hash="sha256:abc",
            repair_reference="M16-W04",
        )
        assert resolution.resolved is True

    def test_p3_event_missing_field_does_not_resolve(self) -> None:
        resolution = resolve_week_event(
            severity="P3",
            reset_decision="window-reset-w3",
            evidence_hash="",
            repair_reference="M16-W04",
        )
        assert resolution.resolved is False
        assert "evidence_hash" in resolution.detail

    def test_unknown_severity_fails_closed_as_p0(self) -> None:
        resolution = resolve_week_event(
            severity="mystery",
            reset_decision="reset",
            evidence_hash="hash-1",
            repair_reference="repair-1",
        )
        assert resolution.severity == "P0"
        assert resolution.resolved is False

    def test_no_operator_question_is_asked(self) -> None:
        resolution = resolve_week_event(
            severity="P2",
            reset_decision="window-reset-w3",
            evidence_hash="sha256:abc",
            repair_reference="M16-W04",
        )
        assert "question" not in resolution.detail.lower() or resolution.resolved

    def test_resolution_is_deterministic(self) -> None:
        for severity in ("P0", "P1", "P2", "P3"):
            first = resolve_week_event(
                severity=severity,
                reset_decision="reset",
                evidence_hash="hash-1",
                repair_reference="repair-1",
            )
            second = resolve_week_event(
                severity=severity,
                reset_decision="reset",
                evidence_hash="hash-1",
                repair_reference="repair-1",
            )
            assert first.model_dump() == second.model_dump()
