"""Tests for the routed broker adapter and simulated fallback.

Covers:
- symbol -> venue classification (OANDA vs Alpaca)
- RoutingBrokerAdapter delegates submits by venue and degrades to the
  simulated adapter when a venue has no live adapter
- SimulatedBrokerAdapter fills through the deterministic PaperBroker
  and reports positions / account state
- execution-backend quantity clamping to the USD notional cap
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alphabrief_core import OrderIntent
from alphabrief_execution.broker.port import (
    BrokerOrderSide,
    BrokerOrderStatus,
    BrokerOrderType,
    BrokerTimeInForce,
    SubmitRequest,
    SubmitResult,
)
from alphabrief_execution.broker.routing import (
    RoutingBrokerAdapter,
    SimulatedBrokerAdapter,
    route_symbol_to_venue,
)
from alphabrief_trader.execution_backend import (
    ExternalPaperExecutionBackend,
    LocalPaperExecutionBackend,
)


class TestSymbolRouting:
    @pytest.mark.parametrize(
        ("symbol", "venue"),
        [
            ("EUR_USD", "oanda_paper"),
            ("GBP_JPY", "oanda_paper"),
            ("XAU_USD", "oanda_paper"),
            ("US30_USD", "oanda_paper"),
            ("AAPL", "alpaca_paper"),
            ("SPY", "alpaca_paper"),
            ("BTC-USD", "alpaca_paper"),
            ("ETH-USD", "alpaca_paper"),
        ],
    )
    def test_route_symbol_to_venue(self, symbol: str, venue: str) -> None:
        assert route_symbol_to_venue(symbol) == venue


class TestSimulatedBrokerAdapter:
    def test_submit_fills_and_reports_position(self) -> None:
        adapter = SimulatedBrokerAdapter()
        adapter.record_reference_price("AAPL", Decimal("200"))
        request = SubmitRequest(
            symbol="AAPL",
            side=BrokerOrderSide.BUY,
            order_type=BrokerOrderType.MARKET,
            quantity=Decimal("10"),
            time_in_force=BrokerTimeInForce.DAY,
        )
        result = asyncio.run(adapter.submit(request, client_order_id="c1"))
        assert result.status == BrokerOrderStatus.FILLED
        assert result.client_order_id == "c1"

        positions = asyncio.run(adapter.get_positions())
        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"
        assert positions[0].quantity == Decimal("10")
        assert positions[0].average_price == Decimal("200")

        account = asyncio.run(adapter.get_account())
        assert account.cash == Decimal("100000") - Decimal("2000")
        assert account.equity == Decimal("100000")

    def test_submit_without_recorded_price_uses_default(self) -> None:
        adapter = SimulatedBrokerAdapter(default_price=Decimal("50"))
        request = SubmitRequest(
            symbol="BTC-USD",
            side=BrokerOrderSide.BUY,
            order_type=BrokerOrderType.MARKET,
            quantity=Decimal("2"),
            time_in_force=BrokerTimeInForce.DAY,
        )
        result = asyncio.run(adapter.submit(request, client_order_id="c2"))
        assert result.status == BrokerOrderStatus.FILLED
        positions = asyncio.run(adapter.get_positions())
        assert positions[0].average_price == Decimal("50")


class TestRoutingBrokerAdapter:
    def test_delegates_submit_to_venue_adapter(self) -> None:
        class _RecordingAdapter(SimulatedBrokerAdapter):
            def __init__(self) -> None:
                super().__init__()
                self.submitted: list[str] = []

            async def submit(
                self, request: SubmitRequest, *, client_order_id: str
            ) -> SubmitResult:
                self.submitted.append(request.symbol)
                return await super().submit(request, client_order_id=client_order_id)

        oanda = _RecordingAdapter()
        alpaca = _RecordingAdapter()
        routed = RoutingBrokerAdapter(oanda=oanda, alpaca=alpaca)

        fx = SubmitRequest(
            symbol="EUR_USD",
            side=BrokerOrderSide.BUY,
            order_type=BrokerOrderType.MARKET,
            quantity=Decimal("1000"),
            time_in_force=BrokerTimeInForce.DAY,
        )
        stock = SubmitRequest(
            symbol="AAPL",
            side=BrokerOrderSide.BUY,
            order_type=BrokerOrderType.MARKET,
            quantity=Decimal("5"),
            time_in_force=BrokerTimeInForce.DAY,
        )
        asyncio.run(routed.submit(fx, client_order_id="f1"))
        asyncio.run(routed.submit(stock, client_order_id="s1"))
        assert oanda.submitted == ["EUR_USD"]
        assert alpaca.submitted == ["AAPL"]

    def test_missing_venue_degrades_to_simulated(self) -> None:
        routed = RoutingBrokerAdapter(oanda=None, alpaca=None)
        request = SubmitRequest(
            symbol="NVDA",
            side=BrokerOrderSide.BUY,
            order_type=BrokerOrderType.MARKET,
            quantity=Decimal("3"),
            time_in_force=BrokerTimeInForce.DAY,
        )
        result = asyncio.run(routed.submit(request, client_order_id="d1"))
        assert result.status == BrokerOrderStatus.FILLED
        # The simulated adapter received the order: a position exists.
        positions = asyncio.run(routed.get_positions())
        assert positions[0].symbol == "NVDA"

    def test_health_reports_venues(self) -> None:
        routed = RoutingBrokerAdapter(oanda=None, alpaca=None)
        health = asyncio.run(routed.health())
        assert health.healthy is True
        assert "simulated" in health.detail

    def test_get_account_with_no_live_venue_returns_simulated(self) -> None:
        routed = RoutingBrokerAdapter(oanda=None, alpaca=None)
        account = asyncio.run(routed.get_account())
        assert account.account_id == "simulated-paper"
        assert account.cash == Decimal("100000")


class TestExecutionBackendClamp:
    def _intent(self, symbol: str = "AAPL") -> OrderIntent:
        return OrderIntent(
            intent_id="clamp-test",
            source="model",
            symbol=symbol,
            side="buy",
            order_type="market",
            target_position_pct=Decimal("0.25"),
            rationale="clamp test",
            created_at=datetime(2026, 8, 1, tzinfo=UTC),
        )

    def test_local_backend_clamps_to_notional_cap(self) -> None:
        from alphabrief_execution import (
            FillSimulator,
            OrderRouter,
            PaperBroker,
            PortfolioState,
        )

        broker = PaperBroker(
            portfolio=PortfolioState(cash=Decimal("100000")),
            router=OrderRouter(),
            fill_simulator=FillSimulator(),
        )
        backend = LocalPaperExecutionBackend(
            broker, max_order_value=Decimal("2000")
        )
        # 0.25 x $100k = $25k notional -> clamped to $2000 / $200 = 10 shares.
        quantity = backend.estimate_quantity(
            self._intent(), reference_price=Decimal("200")
        )
        assert quantity == Decimal("10")

    def test_external_backend_clamps_to_notional_cap(self) -> None:
        adapter = SimulatedBrokerAdapter()
        backend = ExternalPaperExecutionBackend(
            adapter, max_order_value=Decimal("2000")
        )
        quantity = backend.estimate_quantity(
            self._intent("BTC-USD"), reference_price=Decimal("40000")
        )
        # $2000 / $40000 = 0.05 BTC.
        assert quantity == Decimal("0.05")

    def test_no_cap_keeps_legacy_behavior(self) -> None:
        from alphabrief_execution import (
            FillSimulator,
            OrderRouter,
            PaperBroker,
            PortfolioState,
        )

        broker = PaperBroker(
            portfolio=PortfolioState(cash=Decimal("100000")),
            router=OrderRouter(),
            fill_simulator=FillSimulator(),
        )
        backend = LocalPaperExecutionBackend(broker)
        quantity = backend.estimate_quantity(
            self._intent(), reference_price=Decimal("200")
        )
        assert quantity == Decimal("125")  # 0.25 x 100k / 200
