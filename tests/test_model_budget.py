"""Tests for the daily model budget (PROJECT_GUIDE 5.13)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_api.db.model_call import ModelCallStore
from alphabrief_models import ModelCallRecord
from alphabrief_models.model_budget import (
    CHATGPT_PLAN_CHANNEL,
    NO_TRADE_MODEL_BUDGET,
    NO_TRADE_MODEL_UNAVAILABLE,
    OPENAI_COMPATIBLE_CHANNEL,
    ChannelUsage,
    ModelBudgetGuard,
    ModelBudgetPolicy,
)

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class _FakeUsage:
    """In-memory usage source for the pure guard tests."""

    def __init__(self, usage: dict[str, ChannelUsage] | None = None) -> None:
        self.usage = usage or {}
        self.disabled: dict[tuple[str, str], str] = {}

    def daily_usage(self, since: datetime) -> dict[str, ChannelUsage]:
        return dict(self.usage)

    def disabled_channel_reason(self, channel: str, day: str) -> str | None:
        return self.disabled.get((channel, day))

    def disable_channel(self, channel: str, day: str, reason: str) -> None:
        self.disabled.setdefault((channel, day), reason)


def _record(
    *, provider: str, cost: Decimal | None, created_at: datetime
) -> ModelCallRecord:
    return ModelCallRecord(
        call_id=f"call_{provider}_{created_at.timestamp()}_{cost}",
        request_id="req_1",
        provider=provider,
        model="m",
        task_type="symbol_research",
        prompt_version="v1",
        input_hash="a" * 64,
        output_hash="b" * 64,
        latency_ms=10,
        cost_estimate=cost,
        status="succeeded",
        classification="success",
        created_at=created_at,
    )


class TestGuardDecisions:
    def test_under_the_limit_is_allowed(self) -> None:
        guard = ModelBudgetGuard(
            _FakeUsage({CHATGPT_PLAN_CHANNEL: ChannelUsage(calls=10)}),
            clock=lambda: NOW,
        )

        verdict = guard.admit(CHATGPT_PLAN_CHANNEL)

        assert verdict.allowed is True
        assert verdict.reason == ""
        assert verdict.calls_today == 10

    def test_call_limit_exhaustion_blocks_with_the_guide_code(self) -> None:
        guard = ModelBudgetGuard(
            _FakeUsage(
                {CHATGPT_PLAN_CHANNEL: ChannelUsage(calls=150)}
            ),
            clock=lambda: NOW,
        )

        verdict = guard.admit(CHATGPT_PLAN_CHANNEL)

        assert verdict.allowed is False
        assert verdict.reason == NO_TRADE_MODEL_BUDGET
        assert "150 of 150" in verdict.detail

    def test_cost_limit_exhaustion_blocks_the_fallback_channel(self) -> None:
        guard = ModelBudgetGuard(
            _FakeUsage(
                {
                    OPENAI_COMPATIBLE_CHANNEL: ChannelUsage(
                        calls=5, cost=Decimal("2.00")
                    )
                }
            ),
            clock=lambda: NOW,
        )

        verdict = guard.admit(OPENAI_COMPATIBLE_CHANNEL)

        assert verdict.allowed is False
        assert verdict.reason == NO_TRADE_MODEL_BUDGET
        assert verdict.cost_today == Decimal("2.00")

    def test_channel_without_a_limit_is_unlimited(self) -> None:
        guard = ModelBudgetGuard(_FakeUsage(), clock=lambda: NOW)

        assert guard.admit("some_other_channel").allowed is True

    def test_disabled_channel_reports_unavailable(self) -> None:
        usage = _FakeUsage()
        guard = ModelBudgetGuard(usage, clock=lambda: NOW)
        guard.record_channel_unavailable(
            CHATGPT_PLAN_CHANNEL, detail="usage_limit_exceeded"
        )

        verdict = guard.admit(CHATGPT_PLAN_CHANNEL)

        assert verdict.allowed is False
        assert verdict.reason == NO_TRADE_MODEL_UNAVAILABLE
        assert "usage_limit_exceeded" in verdict.detail
        # Disabling is per UTC day.
        later = ModelBudgetGuard(usage, clock=lambda: NOW + timedelta(days=1))
        assert later.admit(CHATGPT_PLAN_CHANNEL).allowed is True

    def test_policy_rejects_non_positive_limits(self) -> None:
        with pytest.raises(ValueError, match="call limit"):
            ModelBudgetPolicy(daily_call_limits={CHATGPT_PLAN_CHANNEL: 0})
        with pytest.raises(ValueError, match="cost limit"):
            ModelBudgetPolicy(
                daily_cost_limits={OPENAI_COMPATIBLE_CHANNEL: Decimal("0")}
            )


class TestStoreBackedBudget:
    """The durable side: real recorded calls and persisted day state."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> Iterator[ModelCallStore]:
        s = ModelCallStore(db_path=tmp_path / "calls.duckdb")
        try:
            yield s
        finally:
            s.close()

    def test_usage_counts_only_todays_calls(self, store: ModelCallStore) -> None:
        store.save_call(
            _record(provider=CHATGPT_PLAN_CHANNEL, cost=None, created_at=NOW)
        )
        store.save_call(
            _record(
                provider=CHATGPT_PLAN_CHANNEL,
                cost=None,
                created_at=NOW - timedelta(days=2),
            )
        )
        store.save_call(
            _record(
                provider=OPENAI_COMPATIBLE_CHANNEL,
                cost=Decimal("0.25"),
                created_at=NOW,
            )
        )

        midnight = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
        usage = store.daily_usage(midnight)

        assert usage[CHATGPT_PLAN_CHANNEL].calls == 1
        assert usage[OPENAI_COMPATIBLE_CHANNEL].calls == 1
        assert usage[OPENAI_COMPATIBLE_CHANNEL].cost == Decimal("0.25")

    def test_guard_blocks_after_the_real_limit_is_reached(
        self, store: ModelCallStore
    ) -> None:
        for index in range(3):
            store.save_call(
                _record(
                    provider=CHATGPT_PLAN_CHANNEL,
                    cost=None,
                    created_at=NOW + timedelta(minutes=index),
                )
            )
        guard = ModelBudgetGuard(
            store,
            policy=ModelBudgetPolicy(
                daily_call_limits={CHATGPT_PLAN_CHANNEL: 3}
            ),
            clock=lambda: NOW,
        )

        verdict = guard.admit(CHATGPT_PLAN_CHANNEL)

        assert verdict.allowed is False
        assert verdict.reason == NO_TRADE_MODEL_BUDGET
        assert verdict.calls_today == 3

    def test_day_state_survives_a_new_store_instance(
        self, store: ModelCallStore, tmp_path: Path
    ) -> None:
        guard = ModelBudgetGuard(store, clock=lambda: NOW)
        guard.record_channel_unavailable(
            CHATGPT_PLAN_CHANNEL, detail="usage_limit_exceeded"
        )
        store.close()

        reopened = ModelCallStore(db_path=tmp_path / "calls.duckdb")
        try:
            assert (
                reopened.disabled_channel_reason(
                    CHATGPT_PLAN_CHANNEL, NOW.date().isoformat()
                )
                == "usage_limit_exceeded"
            )
        finally:
            reopened.close()
