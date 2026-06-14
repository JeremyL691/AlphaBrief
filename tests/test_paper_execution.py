from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alphabrief_core import OrderIntent, RiskDecision
from alphabrief_execution import (
    ExecutionAuditLog,
    FillSimulator,
    OrderRouter,
    OrderRouterError,
    PaperBroker,
    PaperBrokerError,
    PortfolioState,
)

NOW = datetime(2026, 6, 14, 10, 0, tzinfo=UTC)


def _intent(**overrides: object) -> OrderIntent:
    payload: dict[str, object] = {
        "intent_id": "intent_1",
        "source": "strategy",
        "symbol": "BTC-USD",
        "side": "buy",
        "order_type": "market",
        "quantity": Decimal("1"),
        "rationale": "test order",
        "created_at": NOW,
    }
    payload.update(overrides)
    return OrderIntent.model_validate(payload)


def _decision(**overrides: object) -> RiskDecision:
    payload: dict[str, object] = {
        "decision_id": "risk_1",
        "intent_id": "intent_1",
        "approved": True,
        "reason": "approved",
        "max_quantity": Decimal("2"),
        "risk_tags": ["approved"],
        "requires_human_review": False,
        "created_at": NOW,
    }
    payload.update(overrides)
    return RiskDecision.model_validate(payload)


def test_order_router_requires_matching_approved_risk_decision() -> None:
    router = OrderRouter(clock=lambda: NOW, order_id_factory=lambda: "order_1")
    intent = _intent()

    with pytest.raises(OrderRouterError, match="RiskDecision"):
        router.route(intent, None, quantity=Decimal("1"))

    with pytest.raises(OrderRouterError, match="does not match"):
        router.route(intent, _decision(intent_id="other"), quantity=Decimal("1"))

    with pytest.raises(OrderRouterError, match="not approved"):
        router.route(intent, _decision(approved=False), quantity=Decimal("1"))


def test_order_router_creates_paper_order_from_approved_decision() -> None:
    router = OrderRouter(clock=lambda: NOW, order_id_factory=lambda: "order_1")

    order = router.route(_intent(), _decision(), quantity=Decimal("1"))

    assert order.order_id == "order_1"
    assert order.risk_decision_id == "risk_1"
    assert order.broker == "paper"
    assert order.status == "created"


def test_fill_simulator_applies_fee_and_slippage() -> None:
    router = OrderRouter(clock=lambda: NOW, order_id_factory=lambda: "order_1")
    order = router.route(_intent(), _decision(), quantity=Decimal("1"))
    simulator = FillSimulator(
        fee_bps=Decimal("10"),
        slippage_bps=Decimal("20"),
        clock=lambda: NOW,
        fill_id_factory=lambda: "fill_1",
    )

    fill = simulator.fill(order, reference_price=Decimal("100"))

    assert fill.fill_id == "fill_1"
    assert fill.price == Decimal("100.200")
    assert fill.gross_value == Decimal("100.200")
    assert fill.fee == Decimal("0.100200")
    assert fill.slippage_cost == Decimal("0.200")


def test_paper_broker_simulates_buy_fill_and_updates_audit_log() -> None:
    broker = PaperBroker(
        portfolio=PortfolioState(cash=Decimal("1000")),
        router=OrderRouter(clock=lambda: NOW, order_id_factory=lambda: "order_1"),
        fill_simulator=FillSimulator(
            clock=lambda: NOW,
            fill_id_factory=lambda: "fill_1",
        ),
        audit_log=ExecutionAuditLog(clock=lambda: NOW),
    )

    result = broker.submit(_intent(), _decision(), reference_price=Decimal("100"))

    assert result.order.risk_decision_id == "risk_1"
    assert result.fill.order_id == "order_1"
    assert result.portfolio.cash == Decimal("900")
    assert result.portfolio.position_quantity("BTC-USD") == Decimal("1")
    assert [entry.event_type for entry in broker.audit_log.entries] == [
        "risk_decision_recorded",
        "order_created",
        "fill_created",
        "portfolio_updated",
    ]


def test_paper_broker_rejects_missing_or_rejected_risk_decision() -> None:
    broker = PaperBroker(portfolio=PortfolioState(cash=Decimal("1000")))

    with pytest.raises(PaperBrokerError, match="RiskDecision"):
        broker.submit(_intent(), None, reference_price=Decimal("100"))

    with pytest.raises(PaperBrokerError, match="not approved"):
        broker.submit(
            _intent(),
            _decision(approved=False),
            reference_price=Decimal("100"),
        )

    assert any(
        entry.event_type == "order_rejected" for entry in broker.audit_log.entries
    )


def test_paper_broker_can_sell_existing_position_and_realize_pnl() -> None:
    broker = PaperBroker(
        portfolio=PortfolioState(cash=Decimal("1000")),
        router=OrderRouter(clock=lambda: NOW, order_id_factory=lambda: "order_buy"),
        fill_simulator=FillSimulator(clock=lambda: NOW),
    )
    broker.submit(_intent(), _decision(), reference_price=Decimal("100"))
    broker.router = OrderRouter(
        clock=lambda: NOW,
        order_id_factory=lambda: "order_sell",
    )
    sell_intent = _intent(
        intent_id="intent_2",
        side="sell",
        quantity=Decimal("1"),
    )
    sell_decision = _decision(
        decision_id="risk_2",
        intent_id="intent_2",
        max_quantity=Decimal("2"),
    )

    result = broker.submit(sell_intent, sell_decision, reference_price=Decimal("110"))

    assert result.portfolio.position_quantity("BTC-USD") == Decimal("0")
    assert result.portfolio.cash == Decimal("1010")
    assert result.portfolio.realized_pnl == Decimal("10")


def test_portfolio_does_not_double_count_slippage_in_cash() -> None:
    """Slippage is already embedded in fill.price/gross_value."""
    simulator = FillSimulator(
        fee_bps=Decimal("10"),
        slippage_bps=Decimal("100"),
        clock=lambda: NOW,
        fill_id_factory=lambda: "fill_1",
    )
    router = OrderRouter(clock=lambda: NOW, order_id_factory=lambda: "order_1")
    order = router.route(
        _intent(quantity=Decimal("1")), _decision(), quantity=Decimal("1")
    )
    fill = simulator.fill(order, reference_price=Decimal("100"))

    portfolio = PortfolioState(cash=Decimal("1000"))
    new_portfolio = portfolio.apply_fill(fill)

    expected_cost = fill.gross_value + fill.fee
    assert new_portfolio.cash == Decimal("1000") - expected_cost


def test_portfolio_realized_pnl_does_not_double_count_slippage() -> None:
    """Realized PnL should not subtract slippage_cost on top of slipped price."""
    simulator = FillSimulator(
        fee_bps=Decimal("10"),
        slippage_bps=Decimal("100"),
        clock=lambda: NOW,
        fill_id_factory=lambda: "fill_buy",
    )
    router = OrderRouter(clock=lambda: NOW, order_id_factory=lambda: "order_buy")
    order = router.route(
        _intent(quantity=Decimal("1")), _decision(), quantity=Decimal("1")
    )
    fill = simulator.fill(order, reference_price=Decimal("100"))
    portfolio = PortfolioState(cash=Decimal("1000")).apply_fill(fill)

    sell_sim = FillSimulator(
        fee_bps=Decimal("10"),
        slippage_bps=Decimal("100"),
        clock=lambda: NOW,
        fill_id_factory=lambda: "fill_sell",
    )
    sell_router = OrderRouter(clock=lambda: NOW, order_id_factory=lambda: "order_sell")
    sell_order = sell_router.route(
        _intent(intent_id="intent_2", side="sell", quantity=Decimal("1")),
        _decision(decision_id="risk_2", intent_id="intent_2"),
        quantity=Decimal("1"),
    )
    sell_fill = sell_sim.fill(sell_order, reference_price=Decimal("100"))
    final = portfolio.apply_fill(sell_fill)

    expected_realized = (
        (sell_fill.price - fill.price) * Decimal("1")
        - sell_fill.fee
    )
    assert final.realized_pnl == expected_realized


def test_order_router_rejects_human_review_requirement() -> None:
    router = OrderRouter(clock=lambda: NOW, order_id_factory=lambda: "order_1")
    intent = _intent()
    decision = _decision(approved=True, requires_human_review=True)

    with pytest.raises(OrderRouterError, match="human review"):
        router.route(intent, decision, quantity=Decimal("1"))


def test_target_pct_buy_accounts_for_fees_and_slippage() -> None:
    """Buy quantity from target_position_pct should include fee and slippage buffer."""
    broker = PaperBroker(
        portfolio=PortfolioState(cash=Decimal("1000")),
        router=OrderRouter(clock=lambda: NOW, order_id_factory=lambda: "order_1"),
        fill_simulator=FillSimulator(
            fee_bps=Decimal("50"),
            slippage_bps=Decimal("100"),
            clock=lambda: NOW,
            fill_id_factory=lambda: "fill_1",
        ),
    )
    intent = _intent(quantity=None, target_position_pct=Decimal("1"))
    quantity = broker._resolve_quantity(intent, reference_price=Decimal("100"))

    raw_quantity = Decimal("1000") / Decimal("100")
    assert quantity < raw_quantity

    result = broker.submit(
        intent, _decision(max_quantity=Decimal("20")), reference_price=Decimal("100")
    )
    assert result.portfolio.cash >= Decimal("0")
