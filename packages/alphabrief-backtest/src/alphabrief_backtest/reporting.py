"""Research-grade reproducible portfolio reports (M12-W05).

``build_portfolio_report`` is a pure function of declared inputs —
snapshots, fills, trades, financing events, rejections, and a benchmark
— so identical inputs always produce an identical report. Every report
carries the full REQ-STRAT-005 metric set plus instrument and category
attribution, cost attribution (spread, slippage, financing, fees),
rejection attribution, benchmark delta, and an explicit IS/OOS label.
Degenerate inputs serialize as ``None`` (or ``0`` where a zero is the
truth) — never NaN or misleading infinity.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Literal, cast

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_backtest.execution import OrderFill
from alphabrief_backtest.portfolio import (
    CategoryAttribution,
    FinancingEvent,
    PortfolioSnapshot,
    PortfolioTrade,
)

ReportLabel = Literal["IS", "OOS", "FULL"]

_ANNUALIZATION = Decimal("252") ** Decimal("0.5")


class ReportMetrics(BaseModel):
    """The full REQ-STRAT-005 metric set.

    Statistical metrics are ``None`` for degenerate inputs (zero
    variance, no trades, too few periods); ``total_return``,
    ``max_drawdown``, ``turnover`` and ``exposure_pct`` are always
    computable and serialize as their true value (``0`` included).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_return: Decimal
    volatility: Decimal | None
    sharpe: Decimal | None
    sortino: Decimal | None
    calmar: Decimal | None
    max_drawdown: Decimal
    turnover: Decimal
    exposure_pct: Decimal
    hit_rate: Decimal | None
    profit_factor: Decimal | None
    tail_loss: Decimal | None


class CostAttribution(BaseModel):
    """Deterministic cost breakdown in home currency."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    spread_cost: Decimal
    slippage_cost: Decimal
    fee_cost: Decimal
    financing_cost: Decimal
    total_cost: Decimal


class RejectionAttribution(BaseModel):
    """One explicit rejection class and its cost."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reason: str = Field(min_length=1)
    count: int = Field(ge=0)
    rejected_notional: Decimal


class AttributionRow(BaseModel):
    """Instrument or category contribution in home currency."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: Literal["instrument", "category"]
    key: str = Field(min_length=1)
    gross_exposure: Decimal
    net_exposure: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal
    contribution: Decimal


class PortfolioReport(BaseModel):
    """One reproducible research-grade portfolio report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    data_version: str = Field(min_length=1)
    label: ReportLabel
    home_currency: str = Field(min_length=1)
    initial_cash: Decimal
    final_nav: Decimal
    metrics: ReportMetrics
    benchmark_total_return: Decimal | None
    benchmark_delta: Decimal | None
    instrument_attribution: tuple[AttributionRow, ...]
    category_attribution: tuple[AttributionRow, ...]
    cost_attribution: CostAttribution
    rejection_attribution: tuple[RejectionAttribution, ...]

    def normalized_json(self) -> str:
        """Canonical serialization: identical inputs -> identical bytes."""
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )


def _nav_series(snapshots: tuple[PortfolioSnapshot, ...]) -> list[Decimal]:
    return [snapshot.nav for snapshot in snapshots]


def _period_returns(navs: list[Decimal]) -> np.ndarray | None:
    """Per-period simple returns as a numpy array, or None when degenerate."""
    if len(navs) < 2:
        return None
    values = np.array([float(nav) for nav in navs], dtype=float)
    if values[0] <= 0:
        return None
    return cast(np.ndarray, values[1:] / values[:-1] - 1.0)


def _annualized_volatility(navs: list[Decimal]) -> Decimal | None:
    returns = _period_returns(navs)
    if returns is None or returns.size < 2:
        return None
    std = float(returns.std(ddof=1))
    if std <= 0 or std != std:
        return None
    return Decimal(str(std * float(_ANNUALIZATION)))


def _sharpe(navs: list[Decimal]) -> Decimal | None:
    returns = _period_returns(navs)
    if returns is None or returns.size < 2:
        return None
    std = float(returns.std(ddof=1))
    mean = float(returns.mean())
    if std <= 0 or std != std:
        return None
    return Decimal(str(mean / std * float(_ANNUALIZATION)))


def _sortino(navs: list[Decimal]) -> Decimal | None:
    returns = _period_returns(navs)
    if returns is None:
        return None
    negative = returns[returns < 0]
    if negative.size == 0:
        return None
    downside = float((negative**2).mean()) ** 0.5
    mean = float(returns.mean())
    if downside <= 0 or downside != downside:
        return None
    return Decimal(str(mean / downside * float(_ANNUALIZATION)))


def _max_drawdown(navs: list[Decimal]) -> Decimal:
    peak = navs[0]
    max_drawdown = Decimal("0")
    for nav in navs:
        if nav > peak:
            peak = nav
        if peak > 0:
            drawdown = (peak - nav) / peak
            if drawdown > max_drawdown:
                max_drawdown = drawdown
    return max_drawdown


def _cagr(
    snapshots: tuple[PortfolioSnapshot, ...], initial_cash: Decimal
) -> Decimal | None:
    if len(snapshots) < 2 or initial_cash <= 0:
        return None
    start = snapshots[0].timestamp
    end = snapshots[-1].timestamp
    span_seconds = (end - start).total_seconds()
    years = span_seconds / (252 * 24 * 3600)
    if years < (1.0 / 252.0) or span_seconds <= 0:
        return None
    final = snapshots[-1].nav
    if final <= 0:
        return None
    growth = float(final / initial_cash)
    if growth <= 0:
        return None
    return Decimal(str(growth ** (1.0 / years))) - Decimal("1")


def _calmar(
    snapshots: tuple[PortfolioSnapshot, ...],
    initial_cash: Decimal,
    max_drawdown: Decimal,
) -> Decimal | None:
    cagr = _cagr(snapshots, initial_cash)
    if cagr is None or max_drawdown == 0:
        return None
    return cagr / max_drawdown


def _turnover(trades: tuple[PortfolioTrade, ...], initial_cash: Decimal) -> Decimal:
    if initial_cash <= 0:
        return Decimal("0")
    traded = sum(
        (abs(trade.units) * trade.entry_price for trade in trades),
        Decimal("0"),
    )
    return traded / initial_cash


def _exposure_pct(snapshots: tuple[PortfolioSnapshot, ...]) -> Decimal:
    if not snapshots:
        return Decimal("0")
    in_market = sum(1 for s in snapshots if s.gross_exposure > 0)
    return Decimal(in_market) / Decimal(len(snapshots))


def _hit_rate(trades: tuple[PortfolioTrade, ...]) -> Decimal | None:
    if not trades:
        return None
    winners = sum(1 for trade in trades if trade.realized_pnl > 0)
    return Decimal(winners) / Decimal(len(trades))


def _profit_factor(trades: tuple[PortfolioTrade, ...]) -> Decimal | None:
    """Gross profit over gross loss; None when undefined (never infinity)."""
    if not trades:
        return None
    gross_profit = sum(
        (trade.realized_pnl for trade in trades if trade.realized_pnl > 0),
        Decimal("0"),
    )
    gross_loss = sum(
        (-trade.realized_pnl for trade in trades if trade.realized_pnl < 0),
        Decimal("0"),
    )
    if gross_loss == 0:
        return None
    return gross_profit / gross_loss


def _tail_loss(navs: list[Decimal]) -> Decimal | None:
    """Mean of the worst 5% of period returns; None when degenerate.

    Returns ``None`` with fewer than 20 periods or when the return
    series has zero variance (consistent with the other statistical
    metrics).
    """
    returns = _period_returns(navs)
    if returns is None:
        return None
    if returns.size < 20:
        return None
    std = float(returns.std(ddof=1))
    if std <= 0 or std != std:
        return None
    worst_count = max(1, int(np.ceil(0.05 * returns.size)))
    worst = np.sort(returns)[:worst_count]
    return Decimal(str(float(worst.mean())))


def _metrics(
    *,
    snapshots: tuple[PortfolioSnapshot, ...],
    trades: tuple[PortfolioTrade, ...],
    initial_cash: Decimal,
) -> ReportMetrics:
    navs = _nav_series(snapshots)
    total_return = (navs[-1] - initial_cash) / initial_cash
    max_drawdown = _max_drawdown(navs)
    return ReportMetrics(
        total_return=total_return,
        volatility=_annualized_volatility(navs),
        sharpe=_sharpe(navs),
        sortino=_sortino(navs),
        calmar=_calmar(snapshots, initial_cash, max_drawdown),
        max_drawdown=max_drawdown,
        turnover=_turnover(trades, initial_cash),
        exposure_pct=_exposure_pct(snapshots),
        hit_rate=_hit_rate(trades),
        profit_factor=_profit_factor(trades),
        tail_loss=_tail_loss(navs),
    )


def _instrument_attribution(
    snapshots: tuple[PortfolioSnapshot, ...],
    trades: tuple[PortfolioTrade, ...],
    initial_cash: Decimal,
) -> tuple[AttributionRow, ...]:
    realized_by_symbol: dict[str, Decimal] = {}
    for trade in trades:
        realized_by_symbol[trade.symbol] = (
            realized_by_symbol.get(trade.symbol, Decimal("0"))
            + trade.realized_pnl
        )
    latest = snapshots[-1]
    open_symbols = {position.symbol for position in latest.positions}
    rows: list[AttributionRow] = []
    for position in latest.positions:
        symbol = position.symbol
        gross = abs(position.units * position.avg_entry_price)
        rows.append(
            AttributionRow(
                scope="instrument",
                key=symbol,
                gross_exposure=gross,
                net_exposure=position.units * position.avg_entry_price,
                realized_pnl=realized_by_symbol.get(symbol, Decimal("0")),
                unrealized_pnl=position.unrealized_pnl,
                total_pnl=(
                    realized_by_symbol.get(symbol, Decimal("0"))
                    + position.unrealized_pnl
                ),
                contribution=(
                    realized_by_symbol.get(symbol, Decimal("0"))
                    + position.unrealized_pnl
                )
                / initial_cash,
            )
        )
    # Symbols fully closed still contribute realized PnL.
    for symbol in sorted(realized_by_symbol):
        if symbol not in open_symbols:
            rows.append(
                AttributionRow(
                    scope="instrument",
                    key=symbol,
                    gross_exposure=Decimal("0"),
                    net_exposure=Decimal("0"),
                    realized_pnl=realized_by_symbol[symbol],
                    unrealized_pnl=Decimal("0"),
                    total_pnl=realized_by_symbol[symbol],
                    contribution=realized_by_symbol[symbol] / initial_cash,
                )
            )
    return tuple(sorted(rows, key=lambda row: row.key))


def _category_attribution(
    categories: tuple[CategoryAttribution, ...],
    initial_cash: Decimal,
) -> tuple[AttributionRow, ...]:
    rows = tuple(
        AttributionRow(
            scope="category",
            key=category.category,
            gross_exposure=category.gross_exposure,
            net_exposure=category.net_exposure,
            realized_pnl=category.realized_pnl,
            unrealized_pnl=category.unrealized_pnl,
            total_pnl=category.realized_pnl + category.unrealized_pnl,
            contribution=(category.realized_pnl + category.unrealized_pnl)
            / initial_cash,
        )
        for category in categories
    )
    return tuple(sorted(rows, key=lambda row: row.key))


def _cost_attribution(
    fills: tuple[OrderFill, ...],
    financing_events: tuple[FinancingEvent, ...],
) -> CostAttribution:
    spread = sum((fill.spread_cost or Decimal("0") for fill in fills), Decimal("0"))
    slippage = sum(
        (fill.slippage_cost or Decimal("0") for fill in fills), Decimal("0")
    )
    fees = sum((fill.fee or Decimal("0") for fill in fills), Decimal("0"))
    financing = sum((event.amount for event in financing_events), Decimal("0"))
    return CostAttribution(
        spread_cost=spread,
        slippage_cost=slippage,
        fee_cost=fees,
        financing_cost=financing,
        total_cost=spread + slippage + fees + financing,
    )


def _rejection_attribution(
    rejections: tuple[OrderFill, ...],
) -> tuple[RejectionAttribution, ...]:
    by_reason: dict[str, tuple[int, Decimal]] = {}
    for rejection in rejections:
        reason = rejection.reject_reason or "unknown"
        count, notional = by_reason.get(reason, (0, Decimal("0")))
        by_reason[reason] = (
            count + 1,
            notional + abs(rejection.units * rejection.reference_mid),
        )
    return tuple(
        RejectionAttribution(
            reason=reason,
            count=count,
            rejected_notional=notional,
        )
        for reason, (count, notional) in sorted(by_reason.items())
    )


def build_portfolio_report(
    *,
    run_id: str,
    strategy_id: str,
    strategy_version: str,
    data_version: str,
    label: ReportLabel,
    initial_cash: Decimal,
    snapshots: tuple[PortfolioSnapshot, ...],
    fills: tuple[OrderFill, ...],
    trades: tuple[PortfolioTrade, ...],
    financing_events: tuple[FinancingEvent, ...],
    rejections: tuple[OrderFill, ...],
    benchmark_total_return: Decimal | None,
) -> PortfolioReport:
    """Build one reproducible report from declared portfolio evidence."""
    if not snapshots:
        raise ValueError("at least one portfolio snapshot is required")
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive")

    final_nav = snapshots[-1].nav
    metrics = _metrics(
        snapshots=snapshots,
        trades=trades,
        initial_cash=initial_cash,
    )
    benchmark_delta = (
        metrics.total_return - benchmark_total_return
        if benchmark_total_return is not None
        else None
    )
    return PortfolioReport(
        run_id=run_id,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        data_version=data_version,
        label=label,
        home_currency=snapshots[-1].home_currency,
        initial_cash=initial_cash,
        final_nav=final_nav,
        metrics=metrics,
        benchmark_total_return=benchmark_total_return,
        benchmark_delta=benchmark_delta,
        instrument_attribution=_instrument_attribution(
            snapshots, trades, initial_cash
        ),
        category_attribution=_category_attribution(
            snapshots[-1].category_attribution, initial_cash
        ),
        cost_attribution=_cost_attribution(fills, financing_events),
        rejection_attribution=_rejection_attribution(rejections),
    )


__all__ = [
    "AttributionRow",
    "CostAttribution",
    "PortfolioReport",
    "RejectionAttribution",
    "ReportLabel",
    "ReportMetrics",
    "build_portfolio_report",
]
