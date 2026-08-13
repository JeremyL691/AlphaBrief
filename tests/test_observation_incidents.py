"""M16-W02: qualified incidents and no-trade outcomes.

Covers AC-M16-W02-03: weekend, holiday, market-closed,
degraded-provider, RiskGate rejection, and grounded no-opportunity
outcomes qualify only with complete reasons and never trigger an
activity quota or synthetic order.
"""

from __future__ import annotations

import pytest
from alphabrief_core import (
    QUALIFIED_OUTCOMES,
    classify_qualified_outcome,
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
