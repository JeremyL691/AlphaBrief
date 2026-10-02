"""Gateway dispatch is bounded by durable per-channel UTC admissions."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier

import pytest
from alphabrief_api.db.model_call import ModelCallStore
from alphabrief_models.chatgpt_plan import ChatGptPlanError
from alphabrief_models.gateway import (
    ModelCallRecord,
    ModelGateway,
    ModelRequest,
    ModelResponse,
)
from alphabrief_models.model_budget import ModelBudgetGuard, ModelBudgetPolicy
from committee_provider import GroundedProvider

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
D = Decimal


def request(identity: str = "request") -> ModelRequest:
    return ModelRequest(
        request_id=identity,
        task_type="symbol_research",
        prompt_version="budget-test",
        input_text="bounded input",
        required_capabilities=["structured_output"],
    )


class Provider(GroundedProvider):
    def __init__(
        self,
        channel: str = "chatgpt_plan",
        *,
        cost: Decimal | None = None,
        charged: Decimal | None = None,
        quota: bool = False,
    ) -> None:
        super().__init__(
            provider_name=channel,
            model_name="test",
            capabilities=["structured_output"],
            output_text="test",
        )
        self.sent = 0
        self.cost = cost
        self.charged = charged
        self.quota = quota

    def budget_cost(self, request: ModelRequest) -> Decimal | None:
        return self.cost

    def call(self, request: ModelRequest) -> ModelResponse:
        self.sent += 1
        if self.quota:
            raise ChatGptPlanError("usage_limit_exceeded", "test quota")
        return super().call(request).model_copy(update={"cost_estimate": self.charged})


def sink(store: ModelCallStore) -> Callable[[ModelCallRecord], None]:
    def save(record: ModelCallRecord) -> None:
        store.save_call(record)

    return save


def guard(store: ModelCallStore, *, limit: int = 150) -> ModelBudgetGuard:
    return ModelBudgetGuard(
        store,
        policy=ModelBudgetPolicy(
            daily_call_limits={"chatgpt_plan": limit},
            daily_cost_limits={"openai_compatible": D(1)},
        ),
        clock=lambda: NOW,
    )


def test_last_daily_slot_is_not_multiplied_by_committee_calls(tmp_path: Path) -> None:
    store = ModelCallStore(tmp_path / "calls.duckdb")
    budget = guard(store)
    try:
        for i in range(149):
            assert budget.reserve("chatgpt_plan", f"prior-{i}").allowed
        provider = Provider()
        gateway = ModelGateway(
            [provider],
            daily_budget=budget,
            record_sink=sink(store),
            clock=lambda: NOW,
        )
        results = [gateway.invoke(request(str(i))) for i in range(5)]
        assert provider.sent == 1
        assert results[0].response is not None
        assert all(
            r.response is None and r.record.classification == "budget_exhausted"
            for r in results[1:]
        )
        assert store.daily_usage(NOW.replace(hour=0))["chatgpt_plan"].calls == 150
        assert len(store.list_calls()) == 5  # All refusals remain auditable.
    finally:
        store.close()


def test_unknown_outcome_retains_slot_across_restart_and_rolls_over_utc(
    tmp_path: Path,
) -> None:
    database = tmp_path / "calls.duckdb"
    store = ModelCallStore(database)
    assert guard(store, limit=1).reserve("chatgpt_plan", "unknown").allowed
    store.close()
    store = ModelCallStore(database)
    try:
        assert not guard(store, limit=1).reserve("chatgpt_plan", "retry").allowed
        following = ModelBudgetGuard(
            store,
            policy=ModelBudgetPolicy(daily_call_limits={"chatgpt_plan": 1}),
            clock=lambda: NOW + timedelta(days=1),
        )
        assert following.reserve("chatgpt_plan", "next-day").allowed
        assert not following.reserve("chatgpt_plan", "next-day").allowed
    finally:
        store.close()


@pytest.mark.parametrize("charged", [None, D("0.25")])
def test_paid_reservation_is_settled_only_with_cost_evidence(
    tmp_path: Path, charged: Decimal | None
) -> None:
    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        provider = Provider("openai_compatible", cost=D("0.75"), charged=charged)
        gateway = ModelGateway(
            [provider],
            daily_budget=guard(store),
            record_sink=sink(store),
            clock=lambda: NOW,
        )
        assert gateway.invoke(request()).response is not None
        usage = store.daily_usage(NOW.replace(hour=0))["openai_compatible"]
        assert usage.cost == (D("0.75") if charged is None else charged)
        result = gateway.invoke(request("second"))
        assert (result.response is not None) == (charged is not None)
        assert provider.sent == (1 if charged is None else 2)
        assert store.daily_usage(NOW.replace(hour=0))["openai_compatible"].cost <= 1
    finally:
        store.close()


@pytest.mark.parametrize("cost", [None, D("-1"), D("NaN"), D("1.01")])
def test_paid_unknown_or_over_budget_never_dispatches(
    tmp_path: Path, cost: Decimal | None
) -> None:
    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        provider = Provider("openai_compatible", cost=cost)
        result = ModelGateway(
            [provider], daily_budget=guard(store), record_sink=sink(store)
        ).invoke(request())
        assert result.response is None and provider.sent == 0
        assert store.daily_usage(NOW.replace(hour=0)) == {}
    finally:
        store.close()


@pytest.mark.parametrize("fallback", [False, True])
def test_quota_disables_actual_channel_before_next_request(
    tmp_path: Path, fallback: bool
) -> None:
    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        primary = Provider(quota=True)
        secondary = Provider("openai_compatible", cost=D("0.5"), charged=D("0.5"))
        gateway = ModelGateway(
            [primary, secondary],
            fallback_enabled=fallback,
            daily_budget=guard(store),
            record_sink=sink(store),
            clock=lambda: NOW,
        )
        first = gateway.invoke(request("first"))
        second = gateway.invoke(request("second"))
        assert primary.sent == 1
        assert (
            store.disabled_channel_reason("chatgpt_plan", NOW.date().isoformat())
            == "usage_limit_exceeded"
        )
        assert secondary.sent == (2 if fallback else 0)
        assert (first.response is not None) == fallback
        assert (second.response is not None) == fallback
        if fallback:
            assert gateway.invoke(request("third")).response is None
            assert secondary.sent == 2
    finally:
        store.close()


def test_two_store_connections_cannot_both_take_last_slot(tmp_path: Path) -> None:
    database = tmp_path / "calls.duckdb"
    stores = [ModelCallStore(database), ModelCallStore(database)]
    barrier = Barrier(2)
    try:

        def reserve(index: int) -> bool:
            barrier.wait(timeout=5)
            return (
                guard(stores[index], limit=1)
                .reserve("chatgpt_plan", str(index))
                .allowed
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, range(2)))
        assert sum(results) == 1
        assert stores[0].daily_usage(NOW.replace(hour=0))["chatgpt_plan"].calls == 1
    finally:
        for store in stores:
            store.close()


def test_unknown_paid_usage_disables_even_when_reservation_is_small(
    tmp_path: Path,
) -> None:
    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        provider = Provider("openai_compatible", cost=D("0.01"))
        gateway = ModelGateway(
            [provider],
            daily_budget=guard(store),
            record_sink=sink(store),
            clock=lambda: NOW,
        )
        assert gateway.invoke(request()).response is not None
        assert gateway.invoke(request("second")).response is None
        assert provider.sent == 1
        assert (
            store.disabled_channel_reason("openai_compatible", NOW.date().isoformat())
            == "paid_usage_unknown"
        )
        assert store.daily_usage(NOW.replace(hour=0))["openai_compatible"].cost == D(
            "0.01"
        )
    finally:
        store.close()


@pytest.mark.parametrize("price", ["-1", "NaN", "Infinity", "bad", "1.0"])
def test_invalid_price_configuration_fails_closed(tmp_path: Path, price: str) -> None:
    from alphabrief_models.channels import load_model_settings

    config = tmp_path / "settings.yaml"
    # The unquoted float case must also fail; money config uses strings.
    value = price if price == "1.0" else '"' + price + '"'
    config.write_text("model:\n  input_cost_per_million: " + value + "\n")
    with pytest.raises(ValueError):
        load_model_settings(config)


def test_compatible_transport_uses_cap_and_cost_from_configured_prices() -> None:
    import json
    from typing import Any

    from alphabrief_models.chatgpt_plan import HttpResponse
    from alphabrief_models.openai_compatible import (
        FallbackConfig,
        OpenAiCompatibleAdapter,
    )

    captured: list[dict[str, Any]] = []

    def send(
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        assert body is not None
        captured.append(json.loads(body))
        return HttpResponse(
            200,
            json.dumps(
                {
                    "choices": [{"message": {"content": "test"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                }
            ).encode(),
        )

    config = FallbackConfig(
        "https://example.com/v1", "test-key", "test-model", D(1), D(2), 64
    )
    adapter = OpenAiCompatibleAdapter(config, http_send=send)
    result = adapter.call(request())
    assert captured[0]["max_completion_tokens"] == 64
    assert result.cost_estimate == D("0.000014")
    estimate = adapter.budget_cost(request())
    assert estimate is not None and result.cost_estimate is not None
    assert estimate > result.cost_estimate
    tiny = FallbackConfig(
        "https://example.com/v1",
        "test-key",
        "test",
        D("0.000000001"),
        D("0.000000001"),
    ).estimate_cost(input_tokens=1, output_tokens=1)
    assert tiny is not None and tiny > 0


def test_unavailable_admission_store_never_dispatches(tmp_path: Path) -> None:
    store = ModelCallStore(tmp_path / "calls.duckdb")
    budget = guard(store)
    store.close()
    provider = Provider()
    result = ModelGateway([provider], daily_budget=budget).invoke(request())
    assert result.response is None and provider.sent == 0
    assert result.record.classification == "budget_exhausted"


def test_legacy_paid_call_with_unknown_cost_cannot_be_treated_as_free(
    tmp_path: Path,
) -> None:
    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        provider = Provider("openai_compatible", cost=D("0.01"))
        # An old successful call exists without an admission or cost evidence.
        ModelGateway([provider], record_sink=sink(store), clock=lambda: NOW).invoke(
            request("legacy")
        )
        result = ModelGateway(
            [provider], daily_budget=guard(store), record_sink=sink(store)
        ).invoke(request("new"))
        assert result.response is None and provider.sent == 1
        assert not store.daily_usage(NOW.replace(hour=0))[
            "openai_compatible"
        ].cost_known
    finally:
        store.close()


def test_cross_midnight_completion_is_charged_to_admission_day(tmp_path: Path) -> None:
    store = ModelCallStore(tmp_path / "calls.duckdb")
    try:
        provider = Provider()
        ModelGateway(
            [provider],
            daily_budget=guard(store, limit=1),
            record_sink=sink(store),
            clock=lambda: NOW + timedelta(days=1),
        ).invoke(request())
        assert store.daily_usage(NOW.replace(hour=0))["chatgpt_plan"].calls == 1
        assert store.daily_usage((NOW + timedelta(days=1)).replace(hour=0)) == {}
        assert not guard(store, limit=1).reserve("chatgpt_plan", "same-day").allowed
    finally:
        store.close()


def test_manager_repair_budget_refusal_stops_and_produces_no_order(
    tmp_path: Path,
) -> None:
    from _helpers import FakeExecutionBackend
    from alphabrief_risk import RiskGate, RiskLimitConfig
    from alphabrief_trader.committee import TradingCommittee
    from alphabrief_trader.daily_cycle import DailyTradingCycle
    from alphabrief_trader.db_store import AiTradingStore
    from alphabrief_trader.schemas import MarketSnapshot

    class ManagerMalformed(Provider):
        def call(self, request: ModelRequest) -> ModelResponse:
            response = super().call(request)
            if self.sent == 5:
                return response
            return response.model_copy(
                update={
                    "structured_output": {
                        "stance": "long",
                        "confidence": 0.7,
                        "horizon_hours": 24,
                        "key_points": ["Bounded test view"],
                        "evidence_ids": [],
                        "veto": False,
                    }
                }
            )

    calls = ModelCallStore(tmp_path / "calls.duckdb")
    cycles = AiTradingStore(db_path=tmp_path / "cycles.duckdb")
    try:
        provider = ManagerMalformed()
        backend = FakeExecutionBackend()
        budget = guard(calls, limit=5)
        committee = TradingCommittee(
            ModelGateway(
                [provider],
                daily_budget=budget,
                record_sink=sink(calls),
                clock=lambda: NOW,
            ),
            max_turns=5,
            challenge_rounds=0,
            repair_attempts=3,
            clock=lambda: NOW,
        )
        cycle = DailyTradingCycle(
            committee=committee,
            risk_gate=RiskGate(
                limits=RiskLimitConfig(symbol_allowlist=frozenset({"EUR_USD"}))
            ),
            execution_backend=backend,
            store=cycles,
            snapshot_loader=lambda symbol: MarketSnapshot(
                symbol=symbol, reference_price=D("1.1"), captured_at=NOW
            ),
            model_budget=budget,
            trading_mode="on",
            enabled=True,
            clock=lambda: NOW,
        )
        result = cycle.run(["EUR_USD"])
        assert result.outcome == "skipped_model_budget"
        assert "NO_TRADE_MODEL_BUDGET" in result.summary
        assert result.plans == []
        assert result.attempts == []
        assert backend.submission_count == 0
        assert provider.sent == 5
        assert len(calls.list_calls()) == 6  # Only one rejected repair, then stop.
        assert calls.daily_usage(NOW.replace(hour=0))["chatgpt_plan"].calls == 5
    finally:
        cycles.close()
        calls.close()


@pytest.mark.parametrize("cap", [True, 0, -1, 1.5])
def test_output_cap_cannot_be_fractional_or_unbounded(cap: object) -> None:
    from typing import Any, cast

    from alphabrief_models.openai_compatible import FallbackConfig

    with pytest.raises(ValueError):
        FallbackConfig(
            "https://example.com/v1",
            "test-key",
            "test",
            max_output_tokens=cast(Any, cap),
        )


def test_fallback_quota_does_not_disable_the_primary_channel(tmp_path: Path) -> None:
    from _helpers import FakeExecutionBackend
    from alphabrief_risk import RiskGate, RiskLimitConfig
    from alphabrief_trader.committee import TradingCommittee
    from alphabrief_trader.daily_cycle import DailyTradingCycle
    from alphabrief_trader.db_store import AiTradingStore
    from alphabrief_trader.schemas import MarketSnapshot

    calls = ModelCallStore(tmp_path / "calls.duckdb")
    cycles = AiTradingStore(db_path=tmp_path / "cycles.duckdb")
    try:
        budget = guard(calls, limit=1)
        assert budget.reserve("chatgpt_plan", "prior").allowed
        primary = Provider()
        fallback = Provider("openai_compatible", cost=D("0.01"), quota=True)
        committee = TradingCommittee(
            ModelGateway(
                [primary, fallback],
                fallback_enabled=True,
                daily_budget=budget,
                record_sink=sink(calls),
                clock=lambda: NOW,
            ),
            max_turns=5,
            challenge_rounds=0,
            clock=lambda: NOW,
        )
        backend = FakeExecutionBackend()
        cycle = DailyTradingCycle(
            committee=committee,
            risk_gate=RiskGate(limits=RiskLimitConfig()),
            execution_backend=backend,
            store=cycles,
            snapshot_loader=lambda symbol: MarketSnapshot(
                symbol=symbol, reference_price=D("1.1"), captured_at=NOW
            ),
            model_budget=budget,
            trading_mode="on",
            enabled=True,
            clock=lambda: NOW,
        )
        result = cycle.run(["EUR_USD"])
        assert primary.sent == 0 and fallback.sent == 1
        assert (
            calls.disabled_channel_reason("chatgpt_plan", NOW.date().isoformat())
            is None
        )
        assert (
            calls.disabled_channel_reason("openai_compatible", NOW.date().isoformat())
            == "usage_limit_exceeded"
        )
        assert result.outcome == "skipped_model_unavailable"
        assert "NO_TRADE_MODEL_UNAVAILABLE" in result.summary
        assert result.attempts == [] and backend.submission_count == 0
    finally:
        cycles.close()
        calls.close()
