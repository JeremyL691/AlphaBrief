"""Strict OANDA order and dependent-order contracts (M06-W01).

Models the supported order types, time-in-force values, trigger
conditions, signed units, precision-normalized prices and distances,
and TP/SL/trailing-stop/GSLO dependent orders without silent semantic
conversion:

- positive units encode buy, negative units encode sell, zero is
  rejected;
- quantities, prices, and distances normalize exactly from instrument
  metadata (trade units precision / display precision) before request
  serialization;
- DAY and every unsupported or account-incompatible combination fail
  validation instead of being silently mapped or rounded.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from alphabrief_execution.broker.oanda.instruments import InstrumentMetadata

#: Supported OANDA order types (no silent approximations).
OandaOrderType = Literal["MARKET", "LIMIT", "STOP", "MARKET_IF_TOUCHED"]

#: Supported time-in-force values; DAY is intentionally not included.
OandaTimeInForce = Literal["FOK", "IOC", "GTC", "GTD"]

#: Position-fill values.
OandaPositionFill = Literal["OPEN_ONLY", "REDUCE_FIRST", "REDUCE_ONLY", "DEFAULT"]

#: Dependent-order kinds.
DependentKind = Literal[
    "take_profit", "stop_loss", "trailing_stop_loss", "guaranteed_stop_loss"
]


class DependentOrder(BaseModel):
    """One dependent order attached to a parent order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: DependentKind
    price: Decimal | None = None
    distance: Decimal | None = None
    time_in_force: OandaTimeInForce = "GTC"

    @field_validator("price", "distance", mode="before")
    @classmethod
    def decimals_must_not_be_float(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("order prices/distances must not be floats")
        return value

    @model_validator(mode="after")
    def price_or_distance_exactly_one(self) -> DependentOrder:
        if (self.price is None) == (self.distance is None):
            raise ValueError("dependent order requires exactly one of price/distance")
        if self.price is not None and self.price <= 0:
            raise ValueError("dependent order price must be positive")
        if self.distance is not None and self.distance <= 0:
            raise ValueError("dependent order distance must be positive")
        return self


class OandaOrderRequest(BaseModel):
    """One strict OANDA order request (pre-normalization)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: OandaOrderType
    instrument: str = Field(min_length=1)
    units: Decimal
    time_in_force: OandaTimeInForce = "GTC"
    price: Decimal | None = None
    gtd_time: datetime | None = None
    position_fill: OandaPositionFill = "DEFAULT"
    take_profit: DependentOrder | None = None
    stop_loss: DependentOrder | None = None
    trailing_stop_loss: DependentOrder | None = None
    guaranteed_stop_loss: DependentOrder | None = None

    @field_validator("units", mode="before")
    @classmethod
    def units_must_not_be_float(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("units must not be floats")
        return value

    @field_validator("price", mode="before")
    @classmethod
    def price_must_not_be_float(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("price must not be floats")
        return value


class NormalizedOrder(BaseModel):
    """One fully validated, precision-normalized order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: OandaOrderType
    instrument: str = Field(min_length=1)
    units: Decimal
    time_in_force: OandaTimeInForce
    price: Decimal | None = None
    gtd_time: datetime | None = None
    position_fill: OandaPositionFill = "DEFAULT"
    take_profit: DependentOrder | None = None
    stop_loss: DependentOrder | None = None
    trailing_stop_loss: DependentOrder | None = None
    guaranteed_stop_loss: DependentOrder | None = None


def _normalize_quantity(units: Decimal, instrument: InstrumentMetadata) -> Decimal:
    """Normalize units to whole trade units (OANDA counts units)."""
    if units == 0:
        raise ValueError("units must not be zero: positive=buy, negative=sell")
    precision = instrument.trade_units_precision
    if precision == 0:
        normalized = units.to_integral_value()
    else:
        quantum = Decimal(1).scaleb(-precision)
        normalized = units.quantize(quantum, rounding=ROUND_DOWN)
    if normalized == 0:
        raise ValueError(
            "units normalize to zero at instrument precision; "
            "the order is rejected instead of silently dropped"
        )
    return normalized


def _normalize_price(
    price: Decimal, instrument: InstrumentMetadata, field: str
) -> Decimal:
    """Normalize a price to the instrument display precision (no silent rounding)."""
    if price <= 0:
        raise ValueError(f"{field} must be positive")
    quantum = Decimal(1).scaleb(-instrument.display_precision)
    normalized = price.quantize(quantum, rounding=ROUND_DOWN)
    if normalized != price:
        raise ValueError(
            f"{field} {price} exceeds instrument precision "
            f"{instrument.display_precision} and must not be silently rounded"
        )
    return normalized


def normalize_order(
    request: OandaOrderRequest,
    instrument: InstrumentMetadata,
) -> NormalizedOrder:
    """Validate and precision-normalize one order request.

    Raises ``ValueError`` for zero units, sign violations, prices beyond
    the instrument precision, and every unsupported or
    account-incompatible combination — nothing is silently mapped or
    rounded beyond policy.
    """
    units = _normalize_quantity(request.units, instrument)

    price: Decimal | None = None
    if request.price is not None:
        price = _normalize_price(request.price, instrument, "price")
        if request.type in ("LIMIT", "STOP") and price is None:
            raise ValueError(f"{request.type} orders require a price")

    if request.type == "MARKET" and price is not None:
        raise ValueError("MARKET orders must not carry a price")
    if request.time_in_force == "GTD" and request.gtd_time is None:
        raise ValueError("GTD orders require gtd_time")
    if request.gtd_time is not None and request.time_in_force != "GTD":
        raise ValueError("gtd_time requires time_in_force GTD")
    if request.take_profit is not None and request.take_profit.kind != "take_profit":
        raise ValueError("take_profit field kind mismatch")
    if request.guaranteed_stop_loss is not None:
        gsl_mode = str(
            instrument.raw_payload.get("guaranteedStopLossOrderMode", "")
        ).upper()
        if gsl_mode not in ("REQUIRED", "ENABLED"):
            raise ValueError("GSLO unsupported by instrument")

    return NormalizedOrder(
        type=request.type,
        instrument=request.instrument,
        units=units,
        time_in_force=request.time_in_force,
        price=price,
        gtd_time=request.gtd_time,
        position_fill=request.position_fill,
        take_profit=request.take_profit,
        stop_loss=request.stop_loss,
        trailing_stop_loss=request.trailing_stop_loss,
        guaranteed_stop_loss=request.guaranteed_stop_loss,
    )


def serialize_order(
    request: OandaOrderRequest,
    instrument: InstrumentMetadata,
) -> dict[str, Any]:
    """Serialize one validated order to the exact OANDA v20 payload.

    Units are signed (buy positive, sell negative); no ``side`` field is
    sent; dependent orders use their OANDA ``*OnFill`` keys; DAY was
    rejected at the model level so it can never be silently mapped.
    """
    normalized = normalize_order(request, instrument)
    payload: dict[str, Any] = {
        "type": normalized.type,
        "instrument": normalized.instrument,
        "units": str(normalized.units),
        "timeInForce": normalized.time_in_force,
        "positionFill": normalized.position_fill,
    }
    if normalized.price is not None:
        payload["price"] = str(normalized.price)
    if normalized.gtd_time is not None:
        payload["gtdTime"] = normalized.gtd_time.astimezone(UTC).isoformat().replace(
            "+00:00", "Z"
        )
    dependent = {
        "take_profit": "takeProfitOnFill",
        "stop_loss": "stopLossOnFill",
        "trailing_stop_loss": "trailingStopLossOnFill",
        "guaranteed_stop_loss": "guaranteedStopLossOnFill",
    }
    for attr, key in dependent.items():
        order = getattr(normalized, attr)
        if order is None:
            continue
        spec: dict[str, Any] = {"timeInForce": order.time_in_force}
        if order.price is not None:
            spec["price"] = str(order.price)
        if order.distance is not None:
            spec["distance"] = str(order.distance)
        payload[key] = spec
    return payload


def order_side(units: Decimal) -> Literal["buy", "sell"]:
    """Return the side encoded by signed units (positive buy, negative sell)."""
    if units == 0:
        raise ValueError("units must not be zero")
    return "buy" if units > 0 else "sell"


__all__ = [
    "DependentKind",
    "DependentOrder",
    "NormalizedOrder",
    "OandaOrderRequest",
    "OandaOrderType",
    "OandaPositionFill",
    "OandaTimeInForce",
    "normalize_order",
    "order_side",
    "serialize_order",
]
