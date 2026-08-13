"""Multi-instrument portfolio accounting in account home currency (M12-W03).

A :class:`PortfolioSimulator` applies accepted fills and financing
charges deterministically and marks positions to market, producing
cash, NAV, gross/net exposure, margin used, realized and unrealized
PnL, and per-category attribution — all in the account home currency
(prices are home-currency quotes; the assumption is explicit).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from alphabrief_strategy import StrategyInstrumentCategory
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_backtest.execution import OrderFill, financing_charge
from alphabrief_backtest.metadata import (
    SEMANTICS_VERSION,
    BacktestMetadataSet,
)


class PositionState(BaseModel):
    """One instrument's live position truth."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    units: Decimal
    avg_entry_price: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal = Decimal("0")


class PortfolioTrade(BaseModel):
    """One closed (or partially closed) trade's realized result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    units: Decimal
    entry_price: Decimal
    exit_price: Decimal
    realized_pnl: Decimal
    closed_at: datetime


class CategoryAttribution(BaseModel):
    """Per-category exposure and PnL in home currency."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    category: StrategyInstrumentCategory
    gross_exposure: Decimal
    net_exposure: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal


class FinancingEvent(BaseModel):
    """One deterministic financing charge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    nights: int = Field(ge=0)
    amount: Decimal
    timestamp: datetime


class PortfolioSnapshot(BaseModel):
    """Full portfolio state at one timestamp."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: datetime
    cash: Decimal
    nav: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal
    margin_used: Decimal
    positions: tuple[PositionState, ...]
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    category_attribution: tuple[CategoryAttribution, ...]
    home_currency: str = Field(min_length=1)
    metadata_version: str = Field(min_length=1)
    semantics_version: str = Field(min_length=1)


class PortfolioSimulator:
    """Deterministic multi-instrument portfolio accounting."""

    def __init__(
        self,
        *,
        initial_cash: Decimal,
        metadata_set: BacktestMetadataSet,
        home_currency: str = "USD",
    ) -> None:
        if initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        self._initial_cash = initial_cash
        self._metadata_set = metadata_set
        self._home_currency = home_currency
        self._cash = initial_cash
        self._positions: dict[str, PositionState] = {}
        self._financing: list[FinancingEvent] = []
        self._trade_log: list[PortfolioTrade] = []
        self._realized_pnl = Decimal("0")
        self._realized_by_category: dict[StrategyInstrumentCategory, Decimal] = {}

    # ------------------------------------------------------------------
    # Mutations (deterministic, applied in call order)
    # ------------------------------------------------------------------

    def apply_fill(self, fill: OrderFill) -> None:
        """Apply one accepted fill; rejected fills never mutate state."""
        if not fill.accepted or fill.execution_price is None:
            return
        metadata = self._metadata_set.require(fill.symbol)
        current = self._positions.get(fill.symbol)
        current_units = current.units if current is not None else Decimal("0")
        delta = fill.units if fill.side == "buy" else -fill.units
        units_after = current_units + delta

        notional = abs(fill.execution_price * fill.units)
        fee = fill.fee or Decimal("0")
        if fill.side == "buy":
            self._cash = self._cash - notional - fee
        else:
            self._cash = self._cash + notional - fee

        realized = Decimal("0")
        closed_units = Decimal("0")
        new_avg = fill.execution_price
        if current is not None and current_units != 0:
            sign = Decimal("1") if current_units > 0 else Decimal("-1")
            if units_after == 0 or (current_units > 0) != (units_after > 0):
                # Full close or reversal: realize the closed portion.
                closed_units = (
                    abs(current_units)
                    if units_after == 0
                    else min(abs(current_units), abs(delta))
                )
                realized = (
                    sign
                    * closed_units
                    * (fill.execution_price - current.avg_entry_price)
                )
                if abs(delta) > abs(current_units):
                    new_avg = fill.execution_price
            else:
                closed_units = abs(current_units) - abs(units_after)
                if closed_units > 0:
                    # Partial close: realize the reduced portion; the
                    # remaining units keep the original entry average.
                    realized = (
                        sign
                        * closed_units
                        * (fill.execution_price - current.avg_entry_price)
                    )
                    new_avg = current.avg_entry_price
                else:
                    # Adding: blend the average entry price.
                    blended_units = abs(units_after)
                    new_avg = (
                        abs(current_units) * current.avg_entry_price
                        + abs(delta) * fill.execution_price
                    ) / blended_units

        if closed_units > 0:
            assert current is not None
            self._trade_log.append(
                PortfolioTrade(
                    symbol=fill.symbol,
                    units=closed_units if current_units >= 0 else -closed_units,
                    entry_price=current.avg_entry_price,
                    exit_price=fill.execution_price,
                    realized_pnl=realized,
                    closed_at=fill.timestamp,
                )
            )

        if realized != 0:
            self._realized_pnl += realized
            self._realized_by_category[metadata.category] = (
                self._realized_by_category.get(metadata.category, Decimal("0"))
                + realized
            )

        if units_after == 0:
            self._positions.pop(fill.symbol, None)
            return

        self._positions[fill.symbol] = PositionState(
            symbol=fill.symbol,
            units=units_after,
            avg_entry_price=new_avg,
            realized_pnl=(
                current.realized_pnl + realized
                if current is not None
                else realized
            ),
        )

    def accrue_financing(self, *, timestamp: datetime, nights: int) -> None:
        """Charge overnight financing for every open position."""
        for symbol, position in self._positions.items():
            metadata = self._metadata_set.require(symbol)
            charge = financing_charge(
                position.units,
                metadata,
                nights=nights,
            )
            if charge != 0:
                self._cash = self._cash - charge
                self._financing.append(
                    FinancingEvent(
                        symbol=symbol,
                        nights=nights,
                        amount=charge,
                        timestamp=timestamp,
                    )
                )

    # ------------------------------------------------------------------
    # Valuation
    # ------------------------------------------------------------------

    def mark_to_market(
        self,
        *,
        timestamp: datetime,
        mid_prices: dict[str, Decimal],
    ) -> PortfolioSnapshot:
        """Deterministic valuation over the given home-currency mids."""
        gross = Decimal("0")
        net = Decimal("0")
        margin = Decimal("0")
        unrealized = Decimal("0")
        position_value = Decimal("0")
        realized_total = Decimal("0")
        attribution: dict[StrategyInstrumentCategory, list[Decimal]] = {}

        for symbol, position in self._positions.items():
            metadata = self._metadata_set.require(symbol)
            mid = mid_prices[symbol]
            notional = abs(position.units * mid)
            signed_notional = position.units * mid
            gross += notional
            net += signed_notional
            margin += notional * metadata.margin_rate
            unrealized += (mid - position.avg_entry_price) * position.units
            position_value += signed_notional
            entry = attribution.setdefault(metadata.category, [Decimal("0")] * 4)
            entry[0] += notional
            entry[1] += signed_notional
            entry[2] = self._realized_by_category.get(metadata.category, Decimal("0"))
            entry[3] += (mid - position.avg_entry_price) * position.units

        realized_total = self._realized_pnl

        # Categories with realized PnL but no open positions still
        # appear in attribution (closed-out categories are never lost).
        for category, realized in self._realized_by_category.items():
            entry = attribution.setdefault(category, [Decimal("0")] * 4)
            entry[2] = realized

        positions = tuple(
            sorted(
                (
                    PositionState(
                        symbol=position.symbol,
                        units=position.units,
                        avg_entry_price=position.avg_entry_price,
                        realized_pnl=position.realized_pnl,
                        unrealized_pnl=(
                            mid_prices[position.symbol]
                            - position.avg_entry_price
                        )
                        * position.units,
                    )
                    for position in self._positions.values()
                ),
                key=lambda p: p.symbol,
            )
        )
        nav = self._cash + position_value
        attribution_rows = tuple(
            CategoryAttribution(
                category=category,
                gross_exposure=values[0],
                net_exposure=values[1],
                realized_pnl=values[2],
                unrealized_pnl=values[3],
            )
            for category, values in sorted(attribution.items())
        )
        return PortfolioSnapshot(
            timestamp=timestamp,
            cash=self._cash,
            nav=nav,
            gross_exposure=gross,
            net_exposure=net,
            margin_used=margin,
            positions=positions,
            realized_pnl=realized_total,
            unrealized_pnl=unrealized,
            category_attribution=attribution_rows,
            home_currency=self._home_currency,
            metadata_version=self._metadata_set.version,
            semantics_version=SEMANTICS_VERSION,
        )

    # ------------------------------------------------------------------
    # Read-only accessors
    # ------------------------------------------------------------------

    @property
    def cash(self) -> Decimal:
        return self._cash

    @property
    def financing_events(self) -> tuple[FinancingEvent, ...]:
        return tuple(self._financing)

    @property
    def trade_log(self) -> tuple[PortfolioTrade, ...]:
        """Every closed (or partially closed) trade in fill order."""
        return tuple(self._trade_log)


__all__ = [
    "CategoryAttribution",
    "FinancingEvent",
    "PortfolioSimulator",
    "PortfolioSnapshot",
    "PortfolioTrade",
    "PositionState",
]
