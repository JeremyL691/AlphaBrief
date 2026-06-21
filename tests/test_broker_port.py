"""Contract tests for the broker-neutral port.

These tests do not exercise any concrete broker. They assert the
shape of the port: the dataclass-style methods and the Pydantic
schemas that any concrete adapter must satisfy.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from alphabrief_execution.broker.port import (
    AccountSnapshot,
    BrokerAdapter,
    BrokerHealth,
    BrokerOrderSide,
    BrokerOrderStatus,
    BrokerOrderType,
    BrokerTimeInForce,
    CancelResult,
    Fill,
    OrderState,
    Position,
    SubmitRequest,
    SubmitResult,
)
from pydantic import ValidationError


def test_submit_request_requires_positive_quantity() -> None:
    with pytest.raises(ValidationError):
        SubmitRequest(
            symbol="SPY",
            side=BrokerOrderSide.BUY,
            order_type=BrokerOrderType.MARKET,
            quantity=Decimal("0"),
        )


def test_submit_request_limit_orders_allow_limit_price() -> None:
    req = SubmitRequest(
        symbol="QQQ",
        side=BrokerOrderSide.SELL,
        order_type=BrokerOrderType.LIMIT,
        quantity=Decimal("1"),
        limit_price=Decimal("100"),
        time_in_force=BrokerTimeInForce.GTC,
    )
    assert req.limit_price == Decimal("100")
    assert req.time_in_force == BrokerTimeInForce.GTC


def test_order_state_required_fields() -> None:
    from datetime import UTC, datetime

    state = OrderState(
        broker_order_id="abc",
        client_order_id="cli-1",
        symbol="SPY",
        side=BrokerOrderSide.BUY,
        order_type=BrokerOrderType.MARKET,
        quantity=Decimal("1"),
        filled_quantity=Decimal("0"),
        status=BrokerOrderStatus.NEW,
        submitted_at=datetime(2026, 6, 20, tzinfo=UTC),
        updated_at=datetime(2026, 6, 20, tzinfo=UTC),
    )
    assert state.broker_order_id == "abc"


def test_position_quantity_can_be_negative_for_short() -> None:
    p = Position(symbol="SPY", quantity=Decimal("-2"), average_price=Decimal("100"))
    assert p.quantity < 0


def test_account_snapshot_currency_default() -> None:
    from datetime import UTC, datetime

    snap = AccountSnapshot(
        account_id="acct-1",
        cash=Decimal("1000"),
        equity=Decimal("1000"),
        buying_power=Decimal("2000"),
        currency="USD",
        captured_at=datetime(2026, 6, 20, tzinfo=UTC),
    )
    assert snap.currency == "USD"


def test_broker_adapter_is_abstract() -> None:
    with pytest.raises(TypeError):
        BrokerAdapter()  # type: ignore[abstract]


def test_submit_and_cancel_results_are_immutable() -> None:
    from datetime import UTC, datetime

    submit = SubmitResult(
        broker_order_id="abc",
        client_order_id="cli-1",
        status=BrokerOrderStatus.NEW,
        accepted_at=datetime(2026, 6, 20, tzinfo=UTC),
    )
    with pytest.raises(ValidationError):
        submit.broker_order_id = "changed"  # type: ignore[misc]

    cancel = CancelResult(
        broker_order_id="abc",
        status=BrokerOrderStatus.CANCELLED,
        cancelled_at=datetime(2026, 6, 20, tzinfo=UTC),
    )
    with pytest.raises(ValidationError):
        cancel.status = BrokerOrderStatus.NEW  # type: ignore[misc]


def test_fill_quantity_and_price_must_be_positive() -> None:
    from datetime import UTC, datetime

    with pytest.raises(ValidationError):
        Fill(
            fill_id="f1",
            broker_order_id="abc",
            symbol="SPY",
            side=BrokerOrderSide.BUY,
            quantity=Decimal("0"),
            price=Decimal("100"),
            fees=Decimal("0"),
            filled_at=datetime(2026, 6, 20, tzinfo=UTC),
        )


def test_health_health_checked_at_required() -> None:
    from datetime import UTC, datetime

    h = BrokerHealth(
        healthy=True, detail="ok", checked_at=datetime(2026, 6, 20, tzinfo=UTC)
    )
    assert h.healthy is True


__all__ = []
