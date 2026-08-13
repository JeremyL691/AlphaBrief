"""M15-W04: controlled practice E2E path.

Covers AC-M15-W04-02: the controlled practice E2E command can use only
the formal proposal, OrderIntent, persisted RiskDecision, submit,
transaction, cleanup, and reconciliation path and refuses direct or
residual execution.
"""

from __future__ import annotations

import pytest
from alphabrief_core import (
    FORBIDDEN_E2E_STEPS,
    PRACTICE_E2E_PATH,
    validate_e2e_sequence,
)


class TestFormalPath:
    def test_formal_path_is_exactly_seven_steps(self) -> None:
        assert PRACTICE_E2E_PATH == (
            "proposal",
            "order_intent",
            "persisted_risk_decision",
            "submit",
            "transaction",
            "cleanup",
            "reconciliation",
        )

    def test_formal_sequence_is_accepted(self) -> None:
        passed, reason = validate_e2e_sequence(list(PRACTICE_E2E_PATH))
        assert passed is True
        assert "formal practice E2E path" in reason

    def test_missing_step_is_rejected(self) -> None:
        passed, _ = validate_e2e_sequence(
            list(PRACTICE_E2E_PATH)[:6]
        )
        assert passed is False

    def test_reordered_steps_are_rejected(self) -> None:
        steps = list(PRACTICE_E2E_PATH)
        steps[3], steps[4] = steps[4], steps[3]
        passed, _ = validate_e2e_sequence(steps)
        assert passed is False


class TestForbiddenExecution:
    @pytest.mark.parametrize("step", FORBIDDEN_E2E_STEPS)
    def test_forbidden_steps_are_always_refused(self, step: str) -> None:
        passed, reason = validate_e2e_sequence(
            list(PRACTICE_E2E_PATH) + [step]
        )
        assert passed is False
        assert "forbidden step" in reason
        assert step in reason

    def test_all_forbidden_steps_are_declared(self) -> None:
        assert FORBIDDEN_E2E_STEPS == (
            "direct_broker_submit",
            "in_memory_fill",
            "live_execution",
            "simulated_fallback",
        )

    def test_validation_is_deterministic(self) -> None:
        first = validate_e2e_sequence(list(PRACTICE_E2E_PATH))
        second = validate_e2e_sequence(list(PRACTICE_E2E_PATH))
        assert first == second
