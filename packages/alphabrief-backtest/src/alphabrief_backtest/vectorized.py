"""Vectorized-style long/flat backtester for AlphaBrief Phase 1."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from alphabrief_core import Bar, Signal
from alphabrief_data import FeatureRow
from alphabrief_strategy import (
    StrategyInput,
    StrategyProtocol,
    StrategySpec,
    run_strategy,
)
from pydantic import BaseModel, ConfigDict, Field

BPS_DENOMINATOR = Decimal("10000")


class EquityPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: datetime
    portfolio_value: Decimal
    cash: Decimal
    position_quantity: Decimal
    close_price: Decimal


class BacktestTrade(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    entry_timestamp: datetime
    exit_timestamp: datetime
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    gross_pnl: Decimal
    fees: Decimal
    slippage_cost: Decimal
    net_pnl: Decimal
    exit_reason: str = Field(min_length=1)


class BacktestMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_return: Decimal
    max_drawdown: Decimal
    trade_count: int = Field(ge=0)
    win_rate: Decimal | None


class BacktestReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    data_version: str = Field(min_length=1)
    initial_cash: Decimal
    final_value: Decimal
    fee_bps: Decimal
    slippage_bps: Decimal
    metrics: BacktestMetrics
    equity_curve: list[EquityPoint]
    trades: list[BacktestTrade]


class VectorizedBacktester:
    """Run a simple long/flat backtest from strategy signals."""

    def __init__(self, *, initial_cash: Decimal = Decimal("10000")) -> None:
        if initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        self.initial_cash = initial_cash

    def run(
        self,
        strategy: StrategyProtocol,
        *,
        spec: StrategySpec,
        bars: list[Bar],
        features: list[FeatureRow],
    ) -> BacktestReport:
        strategy_input = StrategyInput(spec=spec, bars=bars, features=features)
        strategy_output = run_strategy(strategy, strategy_input)
        signals_by_timestamp = {
            signal.timestamp: signal for signal in strategy_output.signals
        }

        cash = self.initial_cash
        position_quantity = Decimal("0")
        entry_timestamp: datetime | None = None
        entry_price = Decimal("0")
        entry_fee = Decimal("0")
        entry_slippage = Decimal("0")
        trades: list[BacktestTrade] = []
        equity_curve: list[EquityPoint] = []

        for bar in bars:
            signal = signals_by_timestamp.get(bar.timestamp)
            if signal is not None:
                (
                    cash,
                    position_quantity,
                    entry_timestamp,
                    entry_price,
                    entry_fee,
                    entry_slippage,
                    maybe_trade,
                ) = self._apply_signal(
                    signal,
                    bar,
                    spec,
                    cash,
                    position_quantity,
                    entry_timestamp,
                    entry_price,
                    entry_fee,
                    entry_slippage,
                )
                if maybe_trade is not None:
                    trades.append(maybe_trade)

            equity_curve.append(
                _equity_point(
                    bar=bar,
                    cash=cash,
                    position_quantity=position_quantity,
                )
            )

        if position_quantity > 0:
            (
                cash,
                position_quantity,
                close_trade,
            ) = self._close_position(
                bar=bars[-1],
                spec=spec,
                cash=cash,
                position_quantity=position_quantity,
                entry_timestamp=entry_timestamp,
                entry_price=entry_price,
                entry_fee=entry_fee,
                entry_slippage=entry_slippage,
                exit_reason="end_of_backtest",
            )
            trades.append(close_trade)
            equity_curve[-1] = _equity_point(
                bar=bars[-1],
                cash=cash,
                position_quantity=position_quantity,
            )

        final_value = equity_curve[-1].portfolio_value
        return BacktestReport(
            strategy_id=spec.strategy_id,
            strategy_version=spec.version,
            symbol=bars[0].symbol,
            data_version=bars[0].data_version,
            initial_cash=self.initial_cash,
            final_value=final_value,
            fee_bps=spec.costs.fee_bps,
            slippage_bps=spec.costs.slippage_bps,
            metrics=_metrics(
                initial_cash=self.initial_cash,
                equity_curve=equity_curve,
                trades=trades,
            ),
            equity_curve=equity_curve,
            trades=trades,
        )

    def _apply_signal(
        self,
        signal: Signal,
        bar: Bar,
        spec: StrategySpec,
        cash: Decimal,
        position_quantity: Decimal,
        entry_timestamp: datetime | None,
        entry_price: Decimal,
        entry_fee: Decimal,
        entry_slippage: Decimal,
    ) -> tuple[
        Decimal,
        Decimal,
        datetime | None,
        Decimal,
        Decimal,
        Decimal,
        BacktestTrade | None,
    ]:
        if signal.direction == "long" and position_quantity == 0:
            return (*self._open_position(bar, spec, cash), None)

        if signal.direction in {"flat", "short"} and position_quantity > 0:
            new_cash, new_position, trade = self._close_position(
                bar=bar,
                spec=spec,
                cash=cash,
                position_quantity=position_quantity,
                entry_timestamp=entry_timestamp,
                entry_price=entry_price,
                entry_fee=entry_fee,
                entry_slippage=entry_slippage,
                exit_reason="signal_exit",
            )
            return (
                new_cash,
                new_position,
                None,
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                trade,
            )

        return (
            cash,
            position_quantity,
            entry_timestamp,
            entry_price,
            entry_fee,
            entry_slippage,
            None,
        )

    def _open_position(
        self,
        bar: Bar,
        spec: StrategySpec,
        cash: Decimal,
    ) -> tuple[Decimal, Decimal, datetime, Decimal, Decimal, Decimal]:
        fee_rate = spec.costs.fee_bps / BPS_DENOMINATOR
        slippage_rate = spec.costs.slippage_bps / BPS_DENOMINATOR
        execution_price = bar.close * (Decimal("1") + slippage_rate)
        target_notional = cash * spec.risk.max_position_pct
        quantity = target_notional / (execution_price * (Decimal("1") + fee_rate))
        notional = quantity * execution_price
        fee = notional * fee_rate
        slippage_cost = quantity * (execution_price - bar.close)

        return (
            cash - notional - fee,
            quantity,
            bar.timestamp,
            execution_price,
            fee,
            slippage_cost,
        )

    def _close_position(
        self,
        *,
        bar: Bar,
        spec: StrategySpec,
        cash: Decimal,
        position_quantity: Decimal,
        entry_timestamp: datetime | None,
        entry_price: Decimal,
        entry_fee: Decimal,
        entry_slippage: Decimal,
        exit_reason: str,
    ) -> tuple[Decimal, Decimal, BacktestTrade]:
        if entry_timestamp is None:
            raise ValueError("entry_timestamp is required to close a position")

        fee_rate = spec.costs.fee_bps / BPS_DENOMINATOR
        slippage_rate = spec.costs.slippage_bps / BPS_DENOMINATOR
        execution_price = bar.close * (Decimal("1") - slippage_rate)
        notional = position_quantity * execution_price
        exit_fee = notional * fee_rate
        exit_slippage = position_quantity * (bar.close - execution_price)
        gross_pnl = (execution_price - entry_price) * position_quantity
        total_fees = entry_fee + exit_fee
        total_slippage = entry_slippage + exit_slippage
        net_pnl = gross_pnl - total_fees

        return (
            cash + notional - exit_fee,
            Decimal("0"),
            BacktestTrade(
                symbol=bar.symbol,
                entry_timestamp=entry_timestamp,
                exit_timestamp=bar.timestamp,
                entry_price=entry_price,
                exit_price=execution_price,
                quantity=position_quantity,
                gross_pnl=gross_pnl,
                fees=total_fees,
                slippage_cost=total_slippage,
                net_pnl=net_pnl,
                exit_reason=exit_reason,
            ),
        )


def write_backtest_report(report: BacktestReport, path: str | Path) -> None:
    Path(path).write_text(report.model_dump_json(indent=2), encoding="utf-8")


def _equity_point(
    *,
    bar: Bar,
    cash: Decimal,
    position_quantity: Decimal,
) -> EquityPoint:
    return EquityPoint(
        timestamp=bar.timestamp,
        portfolio_value=cash + (position_quantity * bar.close),
        cash=cash,
        position_quantity=position_quantity,
        close_price=bar.close,
    )


def _metrics(
    *,
    initial_cash: Decimal,
    equity_curve: list[EquityPoint],
    trades: list[BacktestTrade],
) -> BacktestMetrics:
    final_value = equity_curve[-1].portfolio_value
    total_return = (final_value - initial_cash) / initial_cash
    max_drawdown = _max_drawdown(equity_curve)
    winning_trades = [trade for trade in trades if trade.net_pnl > 0]
    win_rate = (
        None if not trades else Decimal(len(winning_trades)) / Decimal(len(trades))
    )
    return BacktestMetrics(
        total_return=total_return,
        max_drawdown=max_drawdown,
        trade_count=len(trades),
        win_rate=win_rate,
    )


def _max_drawdown(equity_curve: list[EquityPoint]) -> Decimal:
    peak = equity_curve[0].portfolio_value
    max_drawdown = Decimal("0")

    for point in equity_curve:
        if point.portfolio_value > peak:
            peak = point.portfolio_value
        if peak > 0:
            drawdown = (peak - point.portfolio_value) / peak
            if drawdown > max_drawdown:
                max_drawdown = drawdown

    return max_drawdown
