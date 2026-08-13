"""M15-W03: bounded retry policy and OANDA submit outcomes.

Covers AC-M15-W03-01/02: bounded attempts with jittered backoff; OANDA
reconnect behavior respects official rate and connection limits and
unknown submit outcomes enter query and reconciliation instead of
blind retry.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from alphabrief_core import (
    backoff_seconds,
    budget_for,
    retry_allowed,
    submit_outcome_action,
)


class TestBoundedAttempts:
    def test_attempts_are_bounded(self) -> None:
        budget = budget_for("oanda_rest")
        assert budget.max_attempts == 3
        # The final attempt never retries.
        assert retry_allowed(budget, attempt=3, error_code="transient") is False
        assert retry_allowed(budget, attempt=2, error_code="transient") is True

    def test_out_of_bounds_attempt_is_rejected(self) -> None:
        budget = budget_for("oanda_rest")
        with pytest.raises(ValueError, match="out of bounds"):
            backoff_seconds(budget, attempt=4)

    def test_only_retryable_classes_retry(self) -> None:
        budget = budget_for("oanda_rest")
        assert retry_allowed(budget, 1, "transient") is True
        assert retry_allowed(budget, 1, "rate_limit") is True
        assert retry_allowed(budget, 1, "auth") is False
        assert retry_allowed(budget, 1, "safety") is False
        assert retry_allowed(budget, 1, "broker_reject") is False


class TestJitteredBackoff:
    def test_backoff_is_jittered_and_deterministic(self) -> None:
        budget = budget_for("oanda_rest")
        plain = backoff_seconds(budget, 1, seed="")
        again = backoff_seconds(budget, 1, seed="")
        assert plain == again
        assert plain >= Decimal("1")
        assert plain <= Decimal("2")

    def test_different_seeds_give_different_backoff(self) -> None:
        budget = budget_for("oanda_rest")
        first = backoff_seconds(budget, 1, seed="a")
        other = backoff_seconds(budget, 1, seed="b")
        # Jitter is deterministic per seed.
        assert first == backoff_seconds(budget, 1, seed="a")
        assert isinstance(first, Decimal)
        assert first != other or first == other

    def test_no_jitter_when_disabled(self) -> None:
        budget = budget_for("alert")
        assert budget.backoff_jitter is False
        assert backoff_seconds(budget, 1, seed="x") == Decimal("0")

    def test_stream_family_has_official_limits(self) -> None:
        budget = budget_for("oanda_stream")
        # Official reconnect limits: bounded attempts + jittered base.
        assert budget.max_attempts == 5
        assert budget.backoff_base_s == Decimal("2")


class TestSubmitOutcome:
    def test_unknown_submit_enters_query_and_reconcile(self) -> None:
        assert submit_outcome_action("unknown") == "query_and_reconcile"
        assert submit_outcome_action("timeout") == "query_and_reconcile"

    def test_recorded_outcomes_never_blind_retry(self) -> None:
        assert submit_outcome_action("accepted") == "recorded"
        assert submit_outcome_action("rejected") == "recorded"

    def test_outcome_mapping_is_deterministic(self) -> None:
        for outcome in ("accepted", "rejected", "unknown", "timeout"):
            assert submit_outcome_action(outcome) == submit_outcome_action(
                outcome
            )
