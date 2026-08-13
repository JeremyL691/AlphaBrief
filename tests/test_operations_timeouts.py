"""M15-W03: external request deadlines.

Covers AC-M15-W03-01/03: every external request family has a
configured connect, read, total, and cycle budget; a timed-out
provider task is classified with complete scrubbed telemetry.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from alphabrief_core import (
    REQUEST_BUDGETS,
    REQUEST_FAMILIES,
    TimeoutTelemetry,
    budget_for,
    classify_timeout,
)


class TestRequestBudgets:
    def test_all_seven_families_are_configured(self) -> None:
        assert REQUEST_FAMILIES == (
            "oanda_rest",
            "oanda_stream",
            "market_data",
            "content",
            "model",
            "alert",
            "backup",
        )
        assert set(REQUEST_BUDGETS) == set(REQUEST_FAMILIES)

    @pytest.mark.parametrize("family", REQUEST_FAMILIES)
    def test_every_family_has_connect_read_total_cycle_budget(
        self, family: str
    ) -> None:
        budget = budget_for(family)
        assert budget.connect_timeout_s > 0
        assert budget.read_timeout_s > 0
        assert budget.total_timeout_s > 0
        assert budget.cycle_budget_s > 0
        assert budget.max_attempts >= 1
        assert budget.max_concurrency >= 1

    def test_unknown_family_raises(self) -> None:
        with pytest.raises(KeyError, match="no budget"):
            budget_for("mystery")

    def test_budgets_are_deterministic(self) -> None:
        assert budget_for("oanda_rest") == budget_for("oanda_rest")


class TestTimeoutTelemetry:
    def test_timeout_is_classified_with_scrubbed_telemetry(self) -> None:
        full_id = "account-" + "12345678901234567890"
        telemetry = classify_timeout(
            task="fetch-instruments",
            family="oanda_rest",
            elapsed_s=Decimal("65"),
            fields={"account_id": full_id, "detail": "read timeout"},
        )
        assert isinstance(telemetry, TimeoutTelemetry)
        assert telemetry.classification == "timeout"
        assert telemetry.family == "oanda_rest"
        assert full_id not in str(telemetry.fields)

    def test_elapsed_exceeding_total_is_visible(self) -> None:
        telemetry = classify_timeout(
            task="model-call",
            family="model",
            elapsed_s=Decimal("200"),
        )
        assert telemetry.elapsed_s == Decimal("200")
        assert telemetry.budget_total_s == Decimal("180")

    def test_telemetry_is_deterministic(self) -> None:
        first = classify_timeout(
            task="t", family="backup", elapsed_s=Decimal("10")
        )
        second = classify_timeout(
            task="t", family="backup", elapsed_s=Decimal("10")
        )
        assert first.model_dump() == second.model_dump()
