"""Paper portfolio state for AlphaBrief."""

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from alphabrief_execution.fills import Fill


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("decimal fields must not be provided as float values")
    return value


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    quantity: Decimal
    average_price: Decimal

    @field_validator("quantity", "average_price", mode="before")
    @classmethod
    def _decimal_fields_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)

    @model_validator(mode="after")
    def _validate_position(self) -> "Position":
        if self.quantity < 0:
            raise ValueError("position quantity must be non-negative")
        if self.average_price < 0:
            raise ValueError("average_price must be non-negative")
        return self


class PortfolioState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cash: Decimal
    positions: dict[str, Position] = Field(default_factory=dict)
    realized_pnl: Decimal = Decimal("0")

    @field_validator("cash", "realized_pnl", mode="before")
    @classmethod
    def _decimal_fields_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)

    def apply_fill(self, fill: Fill) -> "PortfolioState":
        if fill.side == "buy":
            return self._apply_buy(fill)
        return self._apply_sell(fill)

    def _apply_buy(self, fill: Fill) -> "PortfolioState":
        # fill.gross_value uses fill.price which already embeds slippage;
        # fill.slippage_cost is an informational breakdown, not an extra charge.
        total_cost = fill.gross_value + fill.fee
        if total_cost > self.cash:
            raise ValueError("insufficient cash for fill")

        current = self.positions.get(fill.symbol)
        if current is None:
            new_position = Position(
                symbol=fill.symbol,
                quantity=fill.quantity,
                average_price=fill.price,
            )
        else:
            new_quantity = current.quantity + fill.quantity
            weighted_cost = (
                current.quantity * current.average_price
            ) + fill.gross_value
            new_position = Position(
                symbol=fill.symbol,
                quantity=new_quantity,
                average_price=weighted_cost / new_quantity,
            )

        return self._with_position(
            fill.symbol,
            new_position,
            cash=self.cash - total_cost,
            realized_pnl=self.realized_pnl,
        )

    def _apply_sell(self, fill: Fill) -> "PortfolioState":
        current = self.positions.get(fill.symbol)
        if current is None or fill.quantity > current.quantity:
            raise ValueError("insufficient position for fill")

        proceeds = fill.gross_value - fill.fee
        realized = (
            (fill.price - current.average_price) * fill.quantity
            - fill.fee
        )
        remaining_quantity = current.quantity - fill.quantity
        new_position = (
            None
            if remaining_quantity == 0
            else Position(
                symbol=fill.symbol,
                quantity=remaining_quantity,
                average_price=current.average_price,
            )
        )

        return self._with_position(
            fill.symbol,
            new_position,
            cash=self.cash + proceeds,
            realized_pnl=self.realized_pnl + realized,
        )

    def _with_position(
        self,
        symbol: str,
        position: Position | None,
        *,
        cash: Decimal,
        realized_pnl: Decimal,
    ) -> "PortfolioState":
        positions = dict(self.positions)
        if position is None:
            positions.pop(symbol, None)
        else:
            positions[symbol] = position
        return PortfolioState(cash=cash, positions=positions, realized_pnl=realized_pnl)

    def position_quantity(self, symbol: str) -> Decimal:
        position = self.positions.get(symbol)
        if position is None:
            return Decimal("0")
        return position.quantity
