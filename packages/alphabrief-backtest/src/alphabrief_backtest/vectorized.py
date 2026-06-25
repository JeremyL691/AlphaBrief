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
    # R21.4 backtest credibility metrics. Each ``Optional`` is None for
    # degenerate cases (zero trades / single bar / zero variance) so a
    # missing metric is a real signal, not a divide-by-zero artifact.
    benchmark_total_return: Decimal | None  # buy-and-hold on the same bars
    alpha_vs_benchmark: Decimal | None  # strategy total_return - bench
    cagr: Decimal | None  # annualized from equity_curve time span
    sharpe: Decimal | None  # annualized, risk-free 0; per-bar returns
    sortino: Decimal | None  # downside-deviation variant
    turnover: Decimal  # sum(|delta_qty| * price) / initial_cash
    exposure_pct: Decimal  # fraction of bars in-market (position > 0)


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
        pending_signal: Signal | None = None

        for bar in bars:
            if pending_signal is not None:
                (
                    cash,
                    position_quantity,
                    entry_timestamp,
                    entry_price,
                    entry_fee,
                    entry_slippage,
                    maybe_trade,
                ) = self._apply_signal(
                    pending_signal,
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
                pending_signal = None

            equity_curve.append(
                _equity_point(
                    bar=bar,
                    cash=cash,
                    position_quantity=position_quantity,
                )
            )

            pending_signal = signals_by_timestamp.get(bar.timestamp)

        if pending_signal is not None:
            (
                cash,
                position_quantity,
                entry_timestamp,
                entry_price,
                entry_fee,
                entry_slippage,
                maybe_trade,
            ) = self._apply_signal(
                pending_signal,
                bars[-1],
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
            equity_curve[-1] = _equity_point(
                bar=bars[-1],
                cash=cash,
                position_quantity=position_quantity,
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
                bars=bars,
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
    bars: list[Bar],
) -> BacktestMetrics:
    final_value = equity_curve[-1].portfolio_value
    total_return = (final_value - initial_cash) / initial_cash
    max_drawdown = _max_drawdown(equity_curve)
    winning_trades = [trade for trade in trades if trade.net_pnl > 0]
    win_rate = (
        None if not trades else Decimal(len(winning_trades)) / Decimal(len(trades))
    )
    # R21.4 credibility metrics. See ``_buy_and_hold_benchmark`` and the
    # per-field ``ponytail:annualization`` note on the gating rules.
    benchmark_total_return = _buy_and_hold_benchmark(
        initial_cash=initial_cash, bars=bars
    )
    alpha_vs_benchmark = (
        total_return - benchmark_total_return
        if benchmark_total_return is not None
        else None
    )
    cagr = _cagr(equity_curve=equity_curve, initial_cash=initial_cash)
    sharpe = _sharpe(equity_curve=equity_curve)
    sortino = _sortino(equity_curve=equity_curve)
    turnover = _turnover(trades=trades, initial_cash=initial_cash)
    exposure_pct = _exposure_pct(equity_curve=equity_curve)
    return BacktestMetrics(
        total_return=total_return,
        max_drawdown=max_drawdown,
        trade_count=len(trades),
        win_rate=win_rate,
        benchmark_total_return=benchmark_total_return,
        alpha_vs_benchmark=alpha_vs_benchmark,
        cagr=cagr,
        sharpe=sharpe,
        sortino=sortino,
        turnover=turnover,
        exposure_pct=exposure_pct,
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


def _buy_and_hold_benchmark(
    *,
    initial_cash: Decimal,
    bars: list[Bar],
) -> Decimal | None:
    """Compute buy-and-hold benchmark return on the same bars.

    Buys at the first bar's close with all ``initial_cash``, holds to the
    last bar. Returns the benchmark total return, or ``None`` when
    ``bars`` is empty / entry price is non-positive. The benchmark lives
    here in the backtest package rather than pulling from
    ``alphabrief_gym.policies.evaluate_buy_and_hold`` so the dependency
    arrow stays one-way (backtest does not import gym).
    """
    if not bars:
        return None
    entry_price = bars[0].close
    exit_price = bars[-1].close
    if entry_price <= 0:
        return None
    quantity = initial_cash / entry_price
    bench_final = quantity * exit_price
    return (bench_final - initial_cash) / initial_cash


def _cagr(
    *,
    equity_curve: list[EquityPoint],
    initial_cash: Decimal,
) -> Decimal | None:
    """Annualized growth rate from first to last equity point.

    ponytail:annualization: assumes 252 daily bars per year and a
    risk-free rate of 0. Intraday/multi-asset bars would mis-annualize;
    the upgrade path is a configurable ``periods_per_year`` + ``rf``.
    Returns ``None`` when the span is shorter than one trading day
    (avoids an unbounded exponent that overflows float).
    """
    if len(equity_curve) < 2 or initial_cash <= 0:
        return None
    start = equity_curve[0].timestamp
    end = equity_curve[-1].timestamp
    span_seconds = (end - start).total_seconds()
    if span_seconds <= 0:
        return None
    # 252 trading days/year * 24*3600 sec/day; use float for the ratio
    # (annualization factor) then convert the final growth back to Decimal.
    years = span_seconds / (252 * 24 * 3600)
    # Avoid raising to an unbounded exponent when the span is sub-trading-day.
    if years < (1.0 / 252.0):
        return None
    final_value = equity_curve[-1].portfolio_value
    if final_value <= 0:
        return None
    growth = float(final_value / initial_cash)
    if growth <= 0:
        return None
    annualized = growth ** (1.0 / years)
    return Decimal(str(annualized)) - Decimal("1")


def _sharpe(equity_curve: list[EquityPoint]) -> Decimal | None:
    """Annualized Sharpe from per-bar returns, risk-free 0.

    Returns ``None`` when there are fewer than 2 bars, when per-bar
    variance is zero, or when the std-of-returns is non-finite (defends
    against degenerate runs without a hard division by zero).
    """
    if len(equity_curve) < 2:
        return None
    returns = _per_bar_returns(equity_curve)
    if returns is None:
        return None
    import numpy as np

    arr = np.asarray(returns)
    # 0 variance -> a constant (positive or negative) return series;
    # Sharpe is undefined, return None rather than 0/0 = NaN.
    std = float(arr.std(ddof=1))
    mean = float(arr.mean())
    if std <= 0 or std != std:  # std != std catches NaN
        return None
    sharpe = mean / std * (252**0.5)
    return Decimal(str(sharpe))


def _sortino(equity_curve: list[EquityPoint]) -> Decimal | None:
    """Annualized Sortino (downside deviation only).

    Returns ``None`` when there are fewer than 2 bars, when no negative
    returns exist, or when the downside deviation is non-finite.
    """
    if len(equity_curve) < 2:
        return None
    returns = _per_bar_returns(equity_curve)
    if returns is None:
        return None
    import numpy as np

    arr = np.asarray(returns)
    neg = arr[arr < 0]
    if neg.size == 0:
        return None
    downside = float((neg**2).mean()) ** 0.5
    mean = float(arr.mean())
    if downside <= 0 or downside != downside:  # catches NaN
        return None
    sortino = mean / downside * (252**0.5)
    return Decimal(str(sortino))


def _per_bar_returns(equity_curve: list[EquityPoint]) -> object | None:
    """Convert per-bar equity points to a numpy array of simple returns.

    Imports numpy lazily so callers that only use Decimal metrics
    (e.g. tests that pin the existing metric surface) don't pay the
    import cost. Returns ``None`` on degenerate inputs. The return
    type is left as ``object`` so this module's static type surface
    does not depend on the numpy import.
    """
    if len(equity_curve) < 2:
        return None
    import numpy as np

    values = np.array(
        [float(point.portfolio_value) for point in equity_curve], dtype=float
    )
    if values[0] <= 0:
        return None
    return values[1:] / values[:-1] - 1.0  # type: ignore[no-any-return]


def _turnover(*, trades: list[BacktestTrade], initial_cash: Decimal) -> Decimal:
    """Sum of ``|delta_qty| * price`` across trades, scaled by initial cash.

    Each trade contributes ``quantity * entry_price`` (round-trip notional
    approximation; fees excluded). Always 0 when ``initial_cash <= 0``,
    but the caller guarantees ``initial_cash > 0``.
    """
    if initial_cash <= 0:
        return Decimal("0")
    traded = sum(
        (trade.quantity * trade.entry_price for trade in trades),
        Decimal("0"),
    )
    return traded / initial_cash


def _exposure_pct(equity_curve: list[EquityPoint]) -> Decimal:
    """Fraction of bars where the strategy held any position."""
    if not equity_curve:
        return Decimal("0")
    in_market = sum(1 for p in equity_curve if p.position_quantity > 0)
    return Decimal(in_market) / Decimal(len(equity_curve))
