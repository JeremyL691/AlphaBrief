"""M06-W01: OANDA order model property tests (AC-M06-W01-01).

Positive units encode buy, negative units encode sell, zero is rejected,
and quantities, prices, and distances normalize exactly from instrument
metadata before request serialization.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from alphabrief_execution.broker.oanda.instruments import InstrumentMetadata
from alphabrief_execution.broker.oanda.orders import (
    OandaOrderRequest,
    normalize_order,
    order_side,
)


def _instrument(
    display_precision: int = 5,
    trade_units_precision: int = 0,
) -> InstrumentMetadata:
    return InstrumentMetadata(
        name="EUR_USD",
        display_name="EUR/USD",
        raw_type="CURRENCY",
        display_precision=display_precision,
        trade_units_precision=trade_units_precision,
        minimum_trade_size=Decimal("1"),
        maximum_order_units=Decimal("0"),
        maximum_position_size=Decimal("0"),
        margin_rate=Decimal("0.05"),
        pip_location=-4,
    )


def _request(units: Decimal, price: Decimal | None = None) -> OandaOrderRequest:
    return OandaOrderRequest(
        type="MARKET" if price is None else "LIMIT",
        instrument="EUR_USD",
        units=units,
        price=price,
    )


def _generated_units() -> list[Decimal]:
    """Deterministic generated property values (negative and positive).

    Whole-unit magnitudes keep every generated value valid at
    ``trade_units_precision=0``.
    """
    values: list[Decimal] = []
    for exponent in range(0, 6):
        for mantissa in (1, 3, 7):
            magnitude = Decimal(mantissa).scaleb(exponent)
            values.append(magnitude)
            values.append(-magnitude)
    return values


def test_negative_units_encode_sell_property() -> None:
    for units in _generated_units():
        if units > 0:
            continue
        assert order_side(units) == "sell"
        normalized = normalize_order(_request(units), _instrument())
        assert normalized.units < 0


def test_positive_units_encode_buy_property() -> None:
    for units in _generated_units():
        if units < 0:
            continue
        assert order_side(units) == "buy"
        normalized = normalize_order(_request(units), _instrument())
        assert normalized.units > 0


def test_zero_units_are_rejected() -> None:
    with pytest.raises(ValueError, match="must not be zero"):
        normalize_order(_request(Decimal("0")), _instrument())
    with pytest.raises(ValueError, match="must not be zero"):
        order_side(Decimal("0"))


def test_float_units_are_rejected() -> None:
    with pytest.raises(ValueError):
        OandaOrderRequest(
            type="MARKET",
            instrument="EUR_USD",
            units=1.5,  # type: ignore[arg-type]
        )


def test_whole_unit_precision_normalizes_exactly_property() -> None:
    """trade_units_precision=0 normalizes to whole units (no silent rounding)."""
    for mantissa in (1, 9, 99, 999):
        units = Decimal(f"{mantissa}.9")
        normalized = normalize_order(_request(units), _instrument())
        assert normalized.units == units.to_integral_value()


def test_units_normalizing_to_zero_are_rejected() -> None:
    """A fractional unit that rounds to zero is rejected, not dropped."""
    with pytest.raises(ValueError, match="normalize to zero"):
        normalize_order(_request(Decimal("0.4")), _instrument())


def test_price_beyond_instrument_precision_is_rejected() -> None:
    instrument = _instrument(display_precision=5)
    with pytest.raises(ValueError, match="must not be silently rounded"):
        normalize_order(_request(Decimal("1"), Decimal("1.123456")), instrument)


def test_price_within_precision_normalizes_exactly() -> None:
    instrument = _instrument(display_precision=5)
    normalized = normalize_order(
        _request(Decimal("1000"), Decimal("1.12345")), instrument
    )
    assert normalized.price == Decimal("1.12345")


def test_nonpositive_price_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        normalize_order(_request(Decimal("1000"), Decimal("0")), _instrument())
