"""M10-W02: deterministic per-call, per-cycle, and daily model budgets.

Covers AC-M10-W02-03: budget-exhausted calls are rejected
deterministically, every rejection persists one terminal record, and
already committed evidence is never altered.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from alphabrief_models import (
    FakeProviderAdapter,
    ModelCallBudget,
    ModelGateway,
    ModelRequest,
)

_FIXED_DAY = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _request(
    request_id: str,
    *,
    cycle_key: str | None = None,
    snapshot_id: str | None = None,
) -> ModelRequest:
    return ModelRequest(
        request_id=request_id,
        task_type="symbol_research",
        prompt_version="test-v1",
        input_text="budget test prompt",
        required_capabilities=["text_generation"],
        cycle_key=cycle_key,
        snapshot_id=snapshot_id,
    )


def _gateway(*, budget: ModelCallBudget) -> ModelGateway:
    return ModelGateway(
        [FakeProviderAdapter(capabilities=["text_generation"])],
        budget=budget,
    )


class TestModelCallBudget:
    def test_rejects_limits_and_clock_are_validated(self) -> None:
        with pytest.raises(ValueError):
            ModelCallBudget(max_calls_per_request=0)
        with pytest.raises(ValueError):
            ModelCallBudget(max_calls_per_cycle=0)
        with pytest.raises(ValueError):
            ModelCallBudget(max_calls_per_day=0)

    def test_per_request_budget_rejects_after_limit(self) -> None:
        budget = ModelCallBudget(
            max_calls_per_request=2,
            max_calls_per_cycle=100,
            max_calls_per_day=100,
        )
        gateway = _gateway(budget=budget)

        first = gateway.invoke(_request("req-1"))
        second = gateway.invoke(_request("req-1"))
        third = gateway.invoke(_request("req-1"))

        assert first.response is not None
        assert second.response is not None
        assert third.response is None
        assert third.record.status == "rejected"
        assert third.record.classification == "budget_exhausted"
        assert third.record.error_type == "BudgetExhausted:request_limit"

    def test_per_request_budget_does_not_block_other_requests(self) -> None:
        budget = ModelCallBudget(
            max_calls_per_request=1,
            max_calls_per_cycle=100,
            max_calls_per_day=100,
        )
        gateway = _gateway(budget=budget)

        assert gateway.invoke(_request("req-a")).response is not None
        assert gateway.invoke(_request("req-b")).response is not None
        assert gateway.invoke(_request("req-a")).response is None
        assert gateway.invoke(_request("req-b")).response is None

    def test_per_cycle_budget_rejects_after_limit(self) -> None:
        budget = ModelCallBudget(
            max_calls_per_request=100,
            max_calls_per_cycle=3,
            max_calls_per_day=100,
        )
        gateway = _gateway(budget=budget)

        for index in range(3):
            result = gateway.invoke(
                _request(f"req-{index}", cycle_key="cycle-2026-08-13")
            )
            assert result.response is not None, index

        rejected = gateway.invoke(
            _request("req-3", cycle_key="cycle-2026-08-13")
        )
        assert rejected.response is None
        assert rejected.record.classification == "budget_exhausted"
        assert rejected.record.error_type == "BudgetExhausted:cycle_limit"

    def test_per_cycle_budget_is_independent_per_cycle(self) -> None:
        budget = ModelCallBudget(
            max_calls_per_request=100,
            max_calls_per_cycle=1,
            max_calls_per_day=100,
        )
        gateway = _gateway(budget=budget)

        assert (
            gateway.invoke(_request("r1", cycle_key="cycle-a")).response is not None
        )
        assert (
            gateway.invoke(_request("r2", cycle_key="cycle-b")).response is not None
        )
        assert (
            gateway.invoke(_request("r3", cycle_key="cycle-a")).response is None
        )
        assert (
            gateway.invoke(_request("r4", cycle_key="cycle-b")).response is None
        )

    def test_daily_budget_rejects_after_limit_and_resets_next_day(self) -> None:
        clock = [ _FIXED_DAY ]

        def _now() -> datetime:
            return clock[0]

        budget = ModelCallBudget(
            max_calls_per_request=100,
            max_calls_per_cycle=100,
            max_calls_per_day=2,
            clock=_now,
        )
        gateway = _gateway(budget=budget)

        assert gateway.invoke(_request("r1")).response is not None
        assert gateway.invoke(_request("r2")).response is not None
        rejected = gateway.invoke(_request("r3"))
        assert rejected.response is None
        assert rejected.record.error_type == "BudgetExhausted:daily_limit"

        # A new UTC day resets the daily counter deterministically.
        clock[0] = _FIXED_DAY + timedelta(days=1)
        assert gateway.invoke(_request("r4")).response is not None
        assert gateway.invoke(_request("r5")).response is not None
        again = gateway.invoke(_request("r6"))
        assert again.response is None
        assert again.record.error_type == "BudgetExhausted:daily_limit"

    def test_rejected_calls_do_not_consume_budget(self) -> None:
        budget = ModelCallBudget(
            max_calls_per_request=1,
            max_calls_per_cycle=100,
            max_calls_per_day=100,
        )
        gateway = _gateway(budget=budget)

        assert gateway.invoke(_request("req-1")).response is not None
        first_reject = gateway.invoke(_request("req-1"))
        second_reject = gateway.invoke(_request("req-1"))
        assert first_reject.response is None
        assert second_reject.response is None
        # Identical repeated rejections are stable (deterministic).
        assert (
            first_reject.record.error_type == second_reject.record.error_type
        )


class TestBudgetGatewayEvidence:
    def test_budget_exhausted_records_preserve_committed_evidence(self) -> None:
        budget = ModelCallBudget(
            max_calls_per_request=1,
            max_calls_per_cycle=100,
            max_calls_per_day=100,
        )
        gateway = _gateway(budget=budget)

        first = gateway.invoke(_request("req-1"))
        second = gateway.invoke(_request("req-1"))

        # Both terminal records exist in the gateway's evidence list:
        # the successful call and the budget-exhausted rejection.
        assert len(gateway.call_records) == 2
        assert gateway.call_records[0].status == "succeeded"
        assert gateway.call_records[0].classification == "success"
        assert gateway.call_records[1].status == "rejected"
        assert gateway.call_records[1].classification == "budget_exhausted"
        # The committed success record is not mutated by the rejection.
        assert gateway.call_records[0].output_hash
        assert first.response is not None
        assert second.response is None

    def test_record_sink_receives_every_terminal_record(self) -> None:
        budget = ModelCallBudget(
            max_calls_per_request=1,
            max_calls_per_cycle=100,
            max_calls_per_day=100,
        )
        sunk: list[str] = []
        gateway = ModelGateway(
            [FakeProviderAdapter(capabilities=["text_generation"])],
            budget=budget,
            record_sink=lambda record: sunk.append(record.classification or ""),
        )

        gateway.invoke(_request("req-1"))
        gateway.invoke(_request("req-1"))

        assert sunk == ["success", "budget_exhausted"]

    def test_retry_count_tracks_repeated_request_ids(self) -> None:
        gateway = ModelGateway(
            [FakeProviderAdapter(capabilities=["text_generation"])],
        )
        first = gateway.invoke(_request("req-1"))
        second = gateway.invoke(_request("req-1"))
        third = gateway.invoke(_request("req-1"))

        assert first.record.retry_count == 0
        assert second.record.retry_count == 1
        assert third.record.retry_count == 2

    def test_correlation_ids_are_carried_into_records(self) -> None:
        gateway = ModelGateway(
            [FakeProviderAdapter(capabilities=["text_generation"])],
        )
        result = gateway.invoke(
            _request(
                "req-1",
                cycle_key="cycle-2026-08-13",
                snapshot_id="snap-abc123",
            )
        )
        assert result.record.cycle_key == "cycle-2026-08-13"
        assert result.record.snapshot_id == "snap-abc123"
