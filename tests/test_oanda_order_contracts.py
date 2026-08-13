"""M06-W01: OANDA order serialization contract fixtures (AC-M06-W01-02/03).

Market, Limit, Stop, Market-if-Touched, dependent orders, FOK, IOC, GTC,
GTD, and supported trigger combinations serialize to exact contract
fixtures; DAY and every unsupported or account-incompatible combination
fail validation and are never silently mapped, rounded, submitted, or
sent for human review.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alphabrief_execution.broker.oanda.instruments import InstrumentMetadata
from alphabrief_execution.broker.oanda.orders import (
    DependentOrder,
    OandaOrderRequest,
    normalize_order,
    serialize_order,
)


def _instrument(gsl_mode: str = "ENABLED") -> InstrumentMetadata:
    return InstrumentMetadata(
        name="EUR_USD",
        display_name="EUR/USD",
        raw_type="CURRENCY",
        display_precision=5,
        trade_units_precision=0,
        minimum_trade_size=Decimal("1"),
        maximum_order_units=Decimal("0"),
        maximum_position_size=Decimal("0"),
        margin_rate=Decimal("0.05"),
        pip_location=-4,
        raw_payload={"guaranteedStopLossOrderMode": gsl_mode},
    )


def _buy(units: str = "1000") -> Decimal:
    return Decimal(units)


# ---------------------------------------------------------------------------
# AC-M06-W01-02: serialization fixtures
# ---------------------------------------------------------------------------


def test_market_order_fixture() -> None:
    request = OandaOrderRequest(
        type="MARKET",
        instrument="EUR_USD",
        units=_buy(),
        time_in_force="FOK",
    )
    payload = serialize_order(request, _instrument())
    assert payload == {
        "type": "MARKET",
        "instrument": "EUR_USD",
        "units": "1000",
        "timeInForce": "FOK",
        "positionFill": "DEFAULT",
    }
    # No side field: direction is encoded by signed units.
    assert "side" not in payload


def test_sell_order_uses_negative_units() -> None:
    request = OandaOrderRequest(
        type="MARKET",
        instrument="EUR_USD",
        units=Decimal("-1000"),
        time_in_force="IOC",
    )
    payload = serialize_order(request, _instrument())
    assert payload["units"] == "-1000"
    assert "side" not in payload


def test_limit_order_fixture() -> None:
    request = OandaOrderRequest(
        type="LIMIT",
        instrument="EUR_USD",
        units=_buy(),
        price=Decimal("1.12345"),
        time_in_force="GTC",
    )
    payload = serialize_order(request, _instrument())
    assert payload["type"] == "LIMIT"
    assert payload["price"] == "1.12345"
    assert payload["timeInForce"] == "GTC"


def test_stop_order_fixture() -> None:
    request = OandaOrderRequest(
        type="STOP",
        instrument="EUR_USD",
        units=_buy(),
        price=Decimal("1.10000"),
        time_in_force="GTC",
    )
    payload = serialize_order(request, _instrument())
    assert payload["type"] == "STOP"
    assert payload["price"] == "1.10000"


def test_market_if_touched_fixture() -> None:
    request = OandaOrderRequest(
        type="MARKET_IF_TOUCHED",
        instrument="EUR_USD",
        units=_buy(),
        price=Decimal("1.10500"),
        time_in_force="GTC",
    )
    payload = serialize_order(request, _instrument())
    assert payload["type"] == "MARKET_IF_TOUCHED"
    assert payload["price"] == "1.10500"


def test_gtd_order_fixture() -> None:
    request = OandaOrderRequest(
        type="LIMIT",
        instrument="EUR_USD",
        units=_buy(),
        price=Decimal("1.12345"),
        time_in_force="GTD",
        gtd_time=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
    )
    payload = serialize_order(request, _instrument())
    assert payload["timeInForce"] == "GTD"
    assert payload["gtdTime"] == "2026-08-20T12:00:00Z"


def test_dependent_orders_fixture() -> None:
    request = OandaOrderRequest(
        type="MARKET",
        instrument="EUR_USD",
        units=_buy(),
        time_in_force="GTC",
        take_profit=DependentOrder(kind="take_profit", price=Decimal("1.15000")),
        stop_loss=DependentOrder(kind="stop_loss", price=Decimal("1.05000")),
        trailing_stop_loss=DependentOrder(
            kind="trailing_stop_loss", distance=Decimal("0.01000")
        ),
        guaranteed_stop_loss=DependentOrder(
            kind="guaranteed_stop_loss", distance=Decimal("0.02000")
        ),
    )
    payload = serialize_order(request, _instrument())
    assert payload["takeProfitOnFill"] == {
        "price": "1.15000",
        "timeInForce": "GTC",
    }
    assert payload["stopLossOnFill"] == {"price": "1.05000", "timeInForce": "GTC"}
    assert payload["trailingStopLossOnFill"] == {
        "distance": "0.01000",
        "timeInForce": "GTC",
    }
    assert payload["guaranteedStopLossOnFill"] == {
        "distance": "0.02000",
        "timeInForce": "GTC",
    }


# ---------------------------------------------------------------------------
# AC-M06-W01-03: DAY and unsupported combinations fail validation
# ---------------------------------------------------------------------------


def test_day_time_in_force_is_rejected_not_mapped() -> None:
    with pytest.raises(ValueError):
        OandaOrderRequest(
            type="MARKET",
            instrument="EUR_USD",
            units=_buy(),
            time_in_force="DAY",  # type: ignore[arg-type]
        )


def test_market_order_with_price_is_rejected() -> None:
    request = OandaOrderRequest(
        type="MARKET",
        instrument="EUR_USD",
        units=_buy(),
        price=Decimal("1.10000"),
    )
    with pytest.raises(ValueError, match="MARKET orders must not carry a price"):
        normalize_order(request, _instrument())


def test_gtd_requires_gtd_time() -> None:
    request = OandaOrderRequest(
        type="LIMIT",
        instrument="EUR_USD",
        units=_buy(),
        price=Decimal("1.12345"),
        time_in_force="GTD",
    )
    with pytest.raises(ValueError, match="require gtd_time"):
        normalize_order(request, _instrument())


def test_gtd_time_without_gtd_tif_is_rejected() -> None:
    request = OandaOrderRequest(
        type="LIMIT",
        instrument="EUR_USD",
        units=_buy(),
        price=Decimal("1.12345"),
        time_in_force="GTC",
        gtd_time=datetime(2026, 8, 20, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="requires time_in_force GTD"):
        normalize_order(request, _instrument())


def test_dependent_order_requires_exactly_one_price_or_distance() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        DependentOrder(kind="take_profit")
    with pytest.raises(ValueError, match="exactly one"):
        DependentOrder(
            kind="take_profit", price=Decimal("1.15"), distance=Decimal("0.01")
        )


def test_gslo_unsupported_by_instrument_is_rejected() -> None:
    request = OandaOrderRequest(
        type="MARKET",
        instrument="EUR_USD",
        units=_buy(),
        guaranteed_stop_loss=DependentOrder(
            kind="guaranteed_stop_loss", distance=Decimal("0.02000")
        ),
    )
    with pytest.raises(ValueError, match="GSLO unsupported"):
        normalize_order(request, _instrument(gsl_mode="DISABLED"))


def test_price_beyond_precision_fails_before_submission() -> None:
    """Never rounded beyond policy: the exact request fails validation."""
    request = OandaOrderRequest(
        type="LIMIT",
        instrument="EUR_USD",
        units=_buy(),
        price=Decimal("1.123456"),
    )
    with pytest.raises(ValueError, match="must not be silently rounded"):
        normalize_order(request, _instrument())
