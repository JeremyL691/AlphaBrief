"""Fill simulation for paper orders."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from alphabrief_core import Order, OrderSide
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BPS_DENOMINATOR = Decimal("10000")


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("decimal fields must not be provided as float values")
    return value


class Fill(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fill_id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    side: OrderSide
    quantity: Decimal
    price: Decimal
    gross_value: Decimal
    fee: Decimal
    slippage_cost: Decimal
    filled_at: datetime

    @field_validator(
        "quantity",
        "price",
        "gross_value",
        "fee",
        "slippage_cost",
        mode="before",
    )
    @classmethod
    def _decimal_fields_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)

    @field_validator("filled_at")
    @classmethod
    def _filled_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("filled_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _validate_fill(self) -> "Fill":
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.price <= 0:
            raise ValueError("price must be positive")
        if self.gross_value <= 0:
            raise ValueError("gross_value must be positive")
        if self.fee < 0:
            raise ValueError("fee must be non-negative")
        if self.slippage_cost < 0:
            raise ValueError("slippage_cost must be non-negative")
        return self


class FillSimulator:
    """Create deterministic fills for paper orders."""

    def __init__(
        self,
        *,
        fee_bps: Decimal = Decimal("0"),
        slippage_bps: Decimal = Decimal("0"),
        clock: Callable[[], datetime] | None = None,
        fill_id_factory: Callable[[], str] | None = None,
    ) -> None:
        if fee_bps < 0:
            raise ValueError("fee_bps must be non-negative")
        if slippage_bps < 0:
            raise ValueError("slippage_bps must be non-negative")
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self._clock = clock or (lambda: datetime.now(UTC))
        self._fill_id_factory = fill_id_factory or (lambda: f"fill_{uuid4().hex}")

    def fill(self, order: Order, *, reference_price: Decimal) -> Fill:
        if reference_price <= 0:
            raise ValueError("reference_price must be positive")

        slippage_rate = self.slippage_bps / BPS_DENOMINATOR
        if order.side == "buy":
            price = reference_price * (Decimal("1") + slippage_rate)
        else:
            price = reference_price * (Decimal("1") - slippage_rate)

        gross_value = order.quantity * price
        fee = gross_value * (self.fee_bps / BPS_DENOMINATOR)
        slippage_cost = order.quantity * abs(price - reference_price)

        return Fill(
            fill_id=self._fill_id_factory(),
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
            gross_value=gross_value,
            fee=fee,
            slippage_cost=slippage_cost,
            filled_at=self._clock(),
        )
