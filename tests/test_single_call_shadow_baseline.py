"""Tests for the single-call shadow baseline (PROJECT_GUIDE 5.11).

The single-call baseline:
1. Reads the exact pre-model input the committee saw (no analyst opinions).
2. Makes one manager model call through ModelGateway.
3. Uses the 'shadow' call kind under durable budget reservation.
4. Strictly parses _PartialManagerDecision and checks evidence grounding.
5. Records in ShadowStore as source='model' (or 'skipped'/'failed') and NEVER
   places an order.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from _helpers import FakeExecutionBackend
from alphabrief_api.db.model_call import ModelCallStore
from alphabrief_models import (
    ModelBudgetGuard,
    ModelGateway,
    ModelRequest,
    ModelResponse,
)
from alphabrief_models.gateway import ModelCallRecord, ModelValidationRecord
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_trader import MarketSnapshot
from alphabrief_trader.committee import (
    TradingCommittee,
)
from alphabrief_trader.committee_prompts import SINGLE_CALL_PROMPT_VERSION
from alphabrief_trader.daily_cycle import DailyTradingCycle
from alphabrief_trader.db_store import AiTradingStore
from alphabrief_trader.evidence_catalog import build_evidence_catalog
from alphabrief_trader.shadow import (
    SHADOW_BENCHMARKS,
    ShadowDecision,
)
from alphabrief_trader.shadow_store import ShadowStore
from committee_provider import GroundedProvider

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _sink(store: ModelCallStore) -> Callable[[ModelCallRecord], None]:
    def save(record: ModelCallRecord) -> None:
        store.save_call(record)

    return save


def _validation_sink(store: ModelCallStore) -> Callable[[ModelValidationRecord], None]:
    def save(record: ModelValidationRecord) -> None:
        store.save_validation(record)

    return save


def _snapshot(symbol: str = "EUR_USD") -> MarketSnapshot:
    return MarketSnapshot(
        symbol=symbol,
        reference_price=Decimal("1.1000"),
        data_version="v1",
        captured_at=NOW,
        momentum_20d_pct=Decimal("1.2"),
    )


class SingleCallRecordingProvider(GroundedProvider):
    """Provider that captures all requests and returns configurable responses."""

    def __init__(
        self,
        *,
        manager_decision: dict[str, Any] | None = None,
        raw_output: str | None = None,
    ) -> None:
        super().__init__(
            provider_name="chatgpt_plan",
            capabilities=["structured_output"],
            structured_output=manager_decision
            or {
                "action": "open_long",
                "confidence": 0.75,
                "stop_atr_multiple": 1.5,
                "take_profit_r_multiple": 2.0,
                "rationale": "Strong momentum and clear support.",
                "evidence_ids": [],
            },
        )
        self.recorded_requests: list[ModelRequest] = []
        self._raw_output = raw_output

    def call(self, request: ModelRequest) -> ModelResponse:
        self.recorded_requests.append(request)
        if self._raw_output is not None and request.call_kind == "shadow":
            return ModelResponse(
                request_id=request.request_id,
                provider=self.provider_name,
                model=self.model_name,
                output_text=self._raw_output,
                status="succeeded",
                finish_reason="stop",
            )
        return super().call(request)


class TestSingleCallBaseline:
    @pytest.fixture
    def stores(
        self, tmp_path: Path
    ) -> Iterator[tuple[AiTradingStore, ModelCallStore, ShadowStore]]:
        trading_store = AiTradingStore(tmp_path / "trading.duckdb")
        call_store = ModelCallStore(tmp_path / "calls.duckdb")
        shadow_store = ShadowStore(tmp_path / "shadow.duckdb")
        try:
            yield trading_store, call_store, shadow_store
        finally:
            shadow_store.close()
            call_store.close()
            trading_store.close()

    def test_single_call_successful_long_decision(
        self, stores: tuple[AiTradingStore, ModelCallStore, ShadowStore]
    ) -> None:
        trading_store, call_store, shadow_store = stores
        snap = _snapshot("EUR_USD")
        catalog = build_evidence_catalog(snap)
        evidence_id = next(iter(catalog.keys()))

        provider = SingleCallRecordingProvider(
            manager_decision={
                "action": "open_long",
                "confidence": 0.85,
                "stop_atr_multiple": 1.5,
                "take_profit_r_multiple": 2.0,
                "rationale": "High confidence long.",
                "evidence_ids": [evidence_id],
            }
        )
        gateway = ModelGateway(
            [provider],
            daily_budget=ModelBudgetGuard(call_store, clock=lambda: NOW),
            record_sink=_sink(call_store),
        )
        gateway.set_validation_sink(_validation_sink(call_store))
        committee = TradingCommittee(gateway)

        recorded_shadows: list[ShadowDecision] = []

        def _record_shadows(decisions: list[ShadowDecision]) -> None:
            recorded_shadows.extend(decisions)
            shadow_store.save_decisions(decisions)

        backend = FakeExecutionBackend()
        cycle = DailyTradingCycle(
            committee=committee,
            risk_gate=RiskGate(RiskLimitConfig()),
            execution_backend=backend,
            store=trading_store,
            snapshot_loader=lambda s: snap,
            enabled=True,
            trading_mode="on",
            clock=lambda: NOW,
            shadow_recorder=_record_shadows,
            single_call_runner=committee.run_single_call,
        )

        cycle.run(["EUR_USD"])

        by_benchmark = {d.benchmark: d for d in recorded_shadows}
        assert set(by_benchmark.keys()) == set(SHADOW_BENCHMARKS)
        single_call = by_benchmark["single_call"]
        assert single_call.benchmark == "single_call"
        assert single_call.side == "long"
        assert single_call.source == "model"
        assert "action=open_long" in single_call.detail
        assert "confidence=0.85" in single_call.detail
        assert "call_id=" in single_call.detail
        assert "validation_id=" in single_call.detail

        # Single call must NEVER place an order!
        shadow_reqs = [r for r in provider.recorded_requests if r.call_kind == "shadow"]
        assert len(shadow_reqs) == 1
        assert shadow_reqs[0].prompt_version == SINGLE_CALL_PROMPT_VERSION

        # Verify validation record in store
        validations = call_store.list_validations(gateway.call_records[-1].call_id)
        assert len(validations) == 1
        assert validations[0]["verdict"] == "accepted"

    def test_single_call_successful_short_decision(
        self, stores: tuple[AiTradingStore, ModelCallStore, ShadowStore]
    ) -> None:
        trading_store, call_store, shadow_store = stores
        snap = _snapshot("EUR_USD")
        catalog = build_evidence_catalog(snap)
        evidence_id = next(iter(catalog.keys()))

        provider = SingleCallRecordingProvider(
            manager_decision={
                "action": "open_short",
                "confidence": 0.70,
                "stop_atr_multiple": 1.5,
                "take_profit_r_multiple": 2.0,
                "rationale": "High confidence short.",
                "evidence_ids": [evidence_id],
            }
        )
        gateway = ModelGateway(
            [provider],
            daily_budget=ModelBudgetGuard(call_store, clock=lambda: NOW),
            record_sink=_sink(call_store),
        )
        committee = TradingCommittee(gateway)

        recorded_shadows: list[ShadowDecision] = []
        cycle = DailyTradingCycle(
            committee=committee,
            risk_gate=RiskGate(RiskLimitConfig()),
            execution_backend=FakeExecutionBackend(),
            store=trading_store,
            snapshot_loader=lambda s: snap,
            enabled=True,
            trading_mode="off",
            clock=lambda: NOW,
            shadow_recorder=recorded_shadows.extend,
            single_call_runner=committee.run_single_call,
        )
        cycle.run(["EUR_USD"])

        by_benchmark = {d.benchmark: d for d in recorded_shadows}
        single_call = by_benchmark["single_call"]
        assert single_call.side == "short"
        assert single_call.source == "model"

    def test_single_call_low_confidence_is_flat(
        self, stores: tuple[AiTradingStore, ModelCallStore, ShadowStore]
    ) -> None:
        trading_store, call_store, shadow_store = stores
        snap = _snapshot("EUR_USD")
        provider = SingleCallRecordingProvider(
            manager_decision={
                "action": "open_long",
                "confidence": 0.45,  # < 0.55 floor
                "stop_atr_multiple": 1.5,
                "take_profit_r_multiple": 2.0,
                "rationale": "Low conviction.",
                "evidence_ids": [],
            }
        )
        gateway = ModelGateway(
            [provider],
            daily_budget=ModelBudgetGuard(call_store, clock=lambda: NOW),
            record_sink=_sink(call_store),
        )
        committee = TradingCommittee(gateway)

        recorded_shadows: list[ShadowDecision] = []
        cycle = DailyTradingCycle(
            committee=committee,
            risk_gate=RiskGate(RiskLimitConfig()),
            execution_backend=FakeExecutionBackend(),
            store=trading_store,
            snapshot_loader=lambda s: snap,
            enabled=True,
            trading_mode="off",
            clock=lambda: NOW,
            shadow_recorder=recorded_shadows.extend,
            single_call_runner=committee.run_single_call,
        )
        cycle.run(["EUR_USD"])

        by_benchmark = {d.benchmark: d for d in recorded_shadows}
        single_call = by_benchmark["single_call"]
        assert single_call.side == "flat"
        assert single_call.source == "model"
        assert "confidence=0.45" in single_call.detail

    def test_single_call_hold_or_no_trade_is_flat(
        self, stores: tuple[AiTradingStore, ModelCallStore, ShadowStore]
    ) -> None:
        trading_store, call_store, shadow_store = stores
        snap = _snapshot("EUR_USD")
        provider = SingleCallRecordingProvider(
            manager_decision={
                "action": "no_trade",
                "confidence": 0.90,
                "stop_atr_multiple": 1.5,
                "take_profit_r_multiple": 2.0,
                "rationale": "Market choppy, no trade.",
                "evidence_ids": [],
            }
        )
        gateway = ModelGateway(
            [provider],
            daily_budget=ModelBudgetGuard(call_store, clock=lambda: NOW),
            record_sink=_sink(call_store),
        )
        committee = TradingCommittee(gateway)

        recorded_shadows: list[ShadowDecision] = []
        cycle = DailyTradingCycle(
            committee=committee,
            risk_gate=RiskGate(RiskLimitConfig()),
            execution_backend=FakeExecutionBackend(),
            store=trading_store,
            snapshot_loader=lambda s: snap,
            enabled=True,
            trading_mode="off",
            clock=lambda: NOW,
            shadow_recorder=recorded_shadows.extend,
            single_call_runner=committee.run_single_call,
        )
        cycle.run(["EUR_USD"])

        by_benchmark = {d.benchmark: d for d in recorded_shadows}
        single_call = by_benchmark["single_call"]
        assert single_call.side == "flat"
        assert single_call.source == "model"
        assert "action=no_trade" in single_call.detail

    def test_single_call_prompt_never_sees_analyst_opinions(
        self, stores: tuple[AiTradingStore, ModelCallStore, ShadowStore]
    ) -> None:
        trading_store, call_store, shadow_store = stores
        snap = _snapshot("EUR_USD")
        provider = SingleCallRecordingProvider()
        gateway = ModelGateway(
            [provider],
            daily_budget=ModelBudgetGuard(call_store, clock=lambda: NOW),
            record_sink=_sink(call_store),
        )
        committee = TradingCommittee(gateway)

        cycle = DailyTradingCycle(
            committee=committee,
            risk_gate=RiskGate(RiskLimitConfig()),
            execution_backend=FakeExecutionBackend(),
            store=trading_store,
            snapshot_loader=lambda s: snap,
            enabled=True,
            trading_mode="off",
            clock=lambda: NOW,
            shadow_recorder=lambda d: None,
            single_call_runner=committee.run_single_call,
        )
        cycle.run(["EUR_USD"])

        shadow_requests = [
            r for r in provider.recorded_requests if r.call_kind == "shadow"
        ]
        assert len(shadow_requests) == 1
        prompt = shadow_requests[0].input_text

        # Must NOT include analyst votes or earlier analyst output
        assert "Earlier analyst votes" not in prompt
        assert "technical" not in prompt
        assert "macro_news" not in prompt
        assert "intermarket" not in prompt
        assert "单次调用基准" in prompt

    def test_single_call_uses_same_snapshot_as_committee(
        self, stores: tuple[AiTradingStore, ModelCallStore, ShadowStore]
    ) -> None:
        trading_store, call_store, shadow_store = stores
        snap = _snapshot("EUR_USD")

        # Refresher alters the snapshot after the model
        calls = 0

        def refresher(s: MarketSnapshot) -> MarketSnapshot:
            nonlocal calls
            calls += 1
            if calls > 1:
                return s.model_copy(update={"reference_price": Decimal("999.00")})
            return s

        provider = SingleCallRecordingProvider()
        gateway = ModelGateway(
            [provider],
            daily_budget=ModelBudgetGuard(call_store, clock=lambda: NOW),
            record_sink=_sink(call_store),
        )
        committee = TradingCommittee(gateway)

        recorded_shadows: list[ShadowDecision] = []
        cycle = DailyTradingCycle(
            committee=committee,
            risk_gate=RiskGate(RiskLimitConfig()),
            execution_backend=FakeExecutionBackend(),
            store=trading_store,
            snapshot_loader=lambda s: snap,
            snapshot_refresher=refresher,
            enabled=True,
            trading_mode="off",
            clock=lambda: NOW,
            shadow_recorder=recorded_shadows.extend,
            single_call_runner=committee.run_single_call,
        )
        cycle.run(["EUR_USD"])

        by_benchmark = {d.benchmark: d for d in recorded_shadows}
        single_call = by_benchmark["single_call"]
        # Entry price must be the original snapshot's price (1.1000), NOT 999.00!
        assert single_call.entry_mid == Decimal("1.1000")

    def test_single_call_budget_exhausted_is_skipped(
        self, stores: tuple[AiTradingStore, ModelCallStore, ShadowStore]
    ) -> None:
        trading_store, call_store, shadow_store = stores
        snap = _snapshot("EUR_USD")

        guard = ModelBudgetGuard(call_store, clock=lambda: NOW)
        syms = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD"]
        idx = 0
        for sym in syms:
            for _ in range(5):
                assert guard.reserve(
                    "chatgpt_plan",
                    f"pre_{idx}",
                    round_key="round-full",
                    symbol=sym,
                    call_kind="normal",
                ).allowed
                idx += 1
            for _ in range(2):
                assert guard.reserve(
                    "chatgpt_plan",
                    f"pre_{idx}",
                    round_key="round-full",
                    symbol=sym,
                    call_kind="repair",
                ).allowed
                idx += 1

        provider = SingleCallRecordingProvider()
        gateway = ModelGateway(
            [provider],
            daily_budget=guard,
            record_sink=_sink(call_store),
        )
        committee = TradingCommittee(gateway)

        recorded_shadows: list[ShadowDecision] = []
        cycle = DailyTradingCycle(
            committee=committee,
            risk_gate=RiskGate(RiskLimitConfig()),
            execution_backend=FakeExecutionBackend(),
            store=trading_store,
            snapshot_loader=lambda s: snap,
            enabled=True,
            trading_mode="off",
            clock=lambda: NOW,
            shadow_recorder=recorded_shadows.extend,
            single_call_runner=committee.run_single_call,
        )
        cycle.run(["EUR_USD"], cycle_key="round-full")

        by_benchmark = {d.benchmark: d for d in recorded_shadows}
        single_call = by_benchmark["single_call"]
        assert single_call.benchmark == "single_call"
        assert single_call.source == "skipped"
        assert single_call.side == "flat"
        assert "skipped" in single_call.detail

    def test_single_call_malformed_json_is_failed(
        self, stores: tuple[AiTradingStore, ModelCallStore, ShadowStore]
    ) -> None:
        trading_store, call_store, shadow_store = stores
        snap = _snapshot("EUR_USD")

        provider = SingleCallRecordingProvider(raw_output="not valid json at all")
        gateway = ModelGateway(
            [provider],
            daily_budget=ModelBudgetGuard(call_store, clock=lambda: NOW),
            record_sink=_sink(call_store),
        )
        committee = TradingCommittee(gateway)

        recorded_shadows: list[ShadowDecision] = []
        cycle = DailyTradingCycle(
            committee=committee,
            risk_gate=RiskGate(RiskLimitConfig()),
            execution_backend=FakeExecutionBackend(),
            store=trading_store,
            snapshot_loader=lambda s: snap,
            enabled=True,
            trading_mode="off",
            clock=lambda: NOW,
            shadow_recorder=recorded_shadows.extend,
            single_call_runner=committee.run_single_call,
        )
        cycle.run(["EUR_USD"])

        by_benchmark = {d.benchmark: d for d in recorded_shadows}
        single_call = by_benchmark["single_call"]
        assert single_call.benchmark == "single_call"
        assert single_call.source == "failed"
        assert single_call.side == "flat"
        assert "schema_validation_failed" in single_call.detail

    def test_single_call_invalid_evidence_is_failed(
        self, stores: tuple[AiTradingStore, ModelCallStore, ShadowStore]
    ) -> None:
        trading_store, call_store, shadow_store = stores
        snap = _snapshot("EUR_USD")

        provider = SingleCallRecordingProvider(
            manager_decision={
                "action": "open_long",
                "confidence": 0.80,
                "stop_atr_multiple": 1.5,
                "take_profit_r_multiple": 2.0,
                "rationale": "Valid JSON but cites fake evidence ID.",
                "evidence_ids": ["nonexistent_id_12345"],
            }
        )
        gateway = ModelGateway(
            [provider],
            daily_budget=ModelBudgetGuard(call_store, clock=lambda: NOW),
            record_sink=_sink(call_store),
        )
        committee = TradingCommittee(gateway)

        recorded_shadows: list[ShadowDecision] = []
        cycle = DailyTradingCycle(
            committee=committee,
            risk_gate=RiskGate(RiskLimitConfig()),
            execution_backend=FakeExecutionBackend(),
            store=trading_store,
            snapshot_loader=lambda s: snap,
            enabled=True,
            trading_mode="off",
            clock=lambda: NOW,
            shadow_recorder=recorded_shadows.extend,
            single_call_runner=committee.run_single_call,
        )
        cycle.run(["EUR_USD"])

        by_benchmark = {d.benchmark: d for d in recorded_shadows}
        single_call = by_benchmark["single_call"]
        assert single_call.benchmark == "single_call"
        assert single_call.source == "failed"
        assert single_call.side == "flat"
        assert "grounding_failed" in single_call.detail
