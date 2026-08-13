"""Tests for AI trading execution backends."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_core import OrderIntent, RiskDecision
from alphabrief_execution import FillSimulator, OrderRouter, PaperBroker, PortfolioState
from alphabrief_execution.broker.port import (
    AccountSnapshot,
    BrokerAdapter,
    BrokerHealth,
    BrokerOrderSide,
    BrokerOrderStatus,
    CancelResult,
    Fill,
    OrderState,
    Position,
    SubmitRequest,
    SubmitResult,
)
from alphabrief_models import FakeProviderAdapter, ModelGateway
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_trader import (
    AiTradingStore,
    DailyTradingCycle,
    DisciplineConfig,
    ExternalPaperExecutionBackend,
    MarketSnapshot,
    TradingCommittee,
)


class _FakeAdapter(BrokerAdapter):
    def __init__(self) -> None:
        self.requests: list[SubmitRequest] = []
        self.client_order_ids: list[str] = []

    async def health(self) -> BrokerHealth:
        return BrokerHealth(
            healthy=True,
            detail="fake",
            checked_at=datetime.now(UTC),
        )

    async def submit(
        self, request: SubmitRequest, *, client_order_id: str
    ) -> SubmitResult:
        self.requests.append(request)
        self.client_order_ids.append(client_order_id)
        return SubmitResult(
            broker_order_id=f"broker-{client_order_id}",
            client_order_id=client_order_id,
            status=BrokerOrderStatus.NEW,
            accepted_at=datetime.now(UTC),
        )

    async def cancel(self, broker_order_id: str) -> CancelResult:
        raise NotImplementedError

    async def get_order(self, broker_order_id: str) -> OrderState:
        raise NotImplementedError

    async def list_orders(
        self, status: BrokerOrderStatus | None = None
    ) -> list[OrderState]:
        return []

    async def list_fills(self, since: datetime | None = None) -> list[Fill]:
        return []

    async def get_positions(self) -> list[Position]:
        return []

    async def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(
            account_id="paper",
            cash=Decimal("1000"),
            equity=Decimal("1000"),
            buying_power=Decimal("1000"),
            currency="USD",
            captured_at=datetime.now(UTC),
        )


def _intent() -> OrderIntent:
    return OrderIntent(
        intent_id="ai_test",
        source="model",
        symbol="SPY",
        side="buy",
        order_type="market",
        target_position_pct=Decimal("0.10"),
        rationale="test",
        created_at=datetime.now(UTC),
    )


def _decision(*, max_quantity: Decimal | None = None) -> RiskDecision:
    return RiskDecision(
        decision_id="risk_test",
        intent_id="ai_test",
        approved=True,
        reason="approved",
        max_quantity=max_quantity,
        risk_tags=["approved"],
        requires_human_review=False,
        source_module="test",
        created_at=datetime.now(UTC),
    )


@pytest.fixture(autouse=True)
def _isolated_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point the runtime data directory at tmp so the decision-binding
    store (M08-W07) never touches the developer's real data directory."""
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))


class TestExternalPaperExecutionBackend:
    def test_estimates_quantity_from_account_buying_power(self) -> None:
        adapter = _FakeAdapter()
        backend = ExternalPaperExecutionBackend(adapter)

        quantity = backend.estimate_quantity(
            _intent(),
            reference_price=Decimal("50"),
        )

        assert quantity == Decimal("2.00")

    def test_submit_uses_intent_id_as_client_order_id(self) -> None:
        adapter = _FakeAdapter()
        backend = ExternalPaperExecutionBackend(adapter)
        intent = _intent()

        result = backend.submit(
            intent,
            _decision(),
            reference_price=Decimal("50"),
            now=datetime.now(UTC),
            estimated_quantity=Decimal("2"),
        )

        assert result.execution_backend == "external_paper"
        assert result.order_id == "broker-ai_test"
        assert result.broker_order_id == "broker-ai_test"
        assert result.client_order_id == "ai_test"
        assert result.broker_status == "new"
        assert result.filled is False
        assert adapter.client_order_ids == ["ai_test"]
        assert adapter.requests[0].symbol == "SPY"
        assert adapter.requests[0].side == BrokerOrderSide.BUY
        assert adapter.requests[0].quantity == Decimal("2")

    def test_submit_clamps_to_risk_max_quantity(self) -> None:
        adapter = _FakeAdapter()
        backend = ExternalPaperExecutionBackend(adapter)

        backend.submit(
            _intent(),
            _decision(max_quantity=Decimal("1")),
            reference_price=Decimal("50"),
            now=datetime.now(UTC),
            estimated_quantity=Decimal("2"),
        )

        assert adapter.requests[0].quantity == Decimal("1")

    def test_daily_cycle_records_external_broker_metadata(self, tmp_path: Path) -> None:
        adapter = _FakeAdapter()
        provider = FakeProviderAdapter(
            provider_name="fake",
            model_name="fake-1",
            capabilities=["structured_output"],
            structured_output={
                "analysis": "Bullish continuation.",
                "view": "bullish",
                "confidence": 0.8,
                "evidence": ["trend"],
                "risks": [],
                "suggested_action": "buy",
                "target_position_pct": "0.10",
                "veto": False,
                "needs_human_review": False,
            },
        )
        store = AiTradingStore(db_path=tmp_path / "alphabrief.db")
        try:
            cycle = DailyTradingCycle(
                committee=TradingCommittee(
                    gateway=ModelGateway(providers=[provider]),
                    discipline=DisciplineConfig(),
                ),
                risk_gate=RiskGate(
                    limits=RiskLimitConfig(
                        trading_enabled=True,
                        symbol_allowlist=frozenset({"SPY"}),
                        max_order_value=Decimal("1000"),
                    )
                ),
                broker=PaperBroker(
                    portfolio=PortfolioState(cash=Decimal("100000")),
                    router=OrderRouter(),
                    fill_simulator=FillSimulator(),
                ),
                store=store,
                snapshot_loader=lambda symbol: MarketSnapshot(
                    symbol=symbol,
                    reference_price=Decimal("100"),
                    data_version="test",
                    captured_at=datetime.now(UTC),
                ),
                execution_backend=ExternalPaperExecutionBackend(adapter),
                enabled=True,
            )

            record = cycle.run(["SPY"])
        finally:
            store.close()

        assert record.outcome == "executed"
        attempt = record.attempts[0]
        assert attempt.execution_backend == "external_paper"
        assert attempt.order_id == "broker-" + attempt.intent_id
        assert attempt.broker_order_id == "broker-" + attempt.intent_id
        assert attempt.client_order_id == attempt.intent_id
        assert attempt.broker_status == "new"
        assert attempt.filled is False
