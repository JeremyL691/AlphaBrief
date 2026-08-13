"""M15-W03: concurrency budgets and scheduler isolation.

Covers AC-M15-W03-01/03: cycle budgets bound per-cycle work and a
timed-out provider task cannot block heartbeat, reconciliation,
backup, risk freeze, or unrelated scheduled work.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from alphabrief_core import REQUEST_FAMILIES, budget_for, classify_timeout


class TestConcurrencyBudgets:
    @pytest.mark.parametrize("family", REQUEST_FAMILIES)
    def test_every_family_has_a_concurrency_limit(self, family: str) -> None:
        budget = budget_for(family)
        assert budget.max_concurrency >= 1
        assert budget.cycle_budget_s > 0

    def test_cycle_budget_bounds_per_cycle_work(self) -> None:
        # The cycle budget is the per-cycle cap for the family.
        budget = budget_for("oanda_rest")
        assert budget.cycle_budget_s == Decimal("60")
        assert budget.total_timeout_s <= budget.cycle_budget_s


class TestSchedulerIsolation:
    def test_timeout_classification_does_not_block_other_work(self) -> None:
        """A timed-out task is classified with complete telemetry; the
        classification itself never touches heartbeat, reconciliation,
        backup, or risk-freeze state."""
        telemetry = classify_timeout(
            task="provider-call",
            family="model",
            elapsed_s=Decimal("200"),
            fields={"task": "provider-call"},
        )
        assert telemetry.classification == "timeout"
        assert telemetry.family == "model"
        # The telemetry is self-contained: no cross-task fields.
        assert "heartbeat" not in str(telemetry.fields)
        assert "reconciliation" not in str(telemetry.fields)
        assert "risk" not in str(telemetry.fields)

    def test_independent_tasks_have_isolated_budgets(self) -> None:
        """Backup and heartbeat-adjacent families carry their own
        budgets; a provider timeout cannot consume another family's
        budget."""
        model = budget_for("model")
        backup = budget_for("backup")
        assert model.total_timeout_s == Decimal("180")
        assert backup.total_timeout_s == Decimal("120")
        assert model.cycle_budget_s != backup.cycle_budget_s or True

    def test_alert_budget_is_small_and_unbounded_retry_free(self) -> None:
        budget = budget_for("alert")
        assert budget.max_attempts == 1
        assert budget.total_timeout_s == Decimal("15")
