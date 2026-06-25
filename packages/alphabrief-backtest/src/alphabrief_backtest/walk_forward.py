"""R21.5 — walk-forward validation and overfitting audit.

Reuses :class:`VectorizedBacktester` to run the strategy on rolling
in-sample (IS) / out-of-sample (OOS) windows, then reports the
per-window IS and OOS metrics plus an aggregate degradation ratio and
an overfitting flag.

A walk-forward run is **out of scope** for the single-bar degenerate
case (no rolling windows can be formed from one bar) and for runs that
have fewer bars than ``is_bars + oos_bars + step_bars`` (the runner
fails closed with a :class:`WalkForwardError`).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from alphabrief_core import Bar
from alphabrief_data import FeatureRow
from alphabrief_strategy import (
    StrategyProtocol,
    StrategySpec,
)

from alphabrief_backtest.vectorized import (
    BacktestReport,
    VectorizedBacktester,
)


@dataclass(frozen=True)
class WalkForwardWindow:
    """A single IS/OOS walk-forward window."""

    window_index: int
    is_bars: list[Bar]
    oos_bars: list[Bar]
    is_report: BacktestReport
    oos_report: BacktestReport
    # Per-window degradation: IS total_return - OOS total_return.
    # Positive -> OOS underperformed IS (warning sign).
    degradation: Decimal


@dataclass(frozen=True)
class WalkForwardResult:
    """The aggregate walk-forward outcome across all windows."""

    windows: tuple[WalkForwardWindow, ...]
    is_avg_total_return: Decimal
    oos_avg_total_return: Decimal
    # Average degradation across windows: IS - OOS. Positive -> OOS
    # on average underperformed IS (the headline overfitting signal).
    avg_degradation: Decimal
    # True when the OOS run materially underperforms the IS run. A
    # threshold of 50% of the IS return keeps the flag tight without
    # being so sensitive that any noise trip it.
    overfit_flag: bool
    # ponytail:walk_forward: the runner uses a fixed IS/OOS split and a
    # fixed step between windows. The upgrade path is configurable IS
    # ratios, an anchored-vs-rolling choice, and a combinatorial-purged
    # cross-validation variant (CPCV) for harder overfitting detection.


class WalkForwardError(ValueError):
    """Raised when the walk-forward runner cannot be configured."""


def run_walk_forward(
    strategy: StrategyProtocol,
    *,
    spec: StrategySpec,
    bars: list[Bar],
    features: list[FeatureRow],
    initial_cash: Decimal = Decimal("10000"),
    is_bars: int = 60,
    oos_bars: int = 20,
    step_bars: int = 20,
) -> WalkForwardResult:
    """Run :class:`VectorizedBacktester` on rolling IS/OOS windows.

    The window sequence starts at bar 0, takes ``is_bars`` bars as IS,
    then ``oos_bars`` bars as OOS, then steps forward by ``step_bars``.
    Windows are emitted until there is not enough data for the next
    OOS slice; a trailing window with only IS data is not run.

    ``features`` must be the same length as ``bars`` (the standard
    contract from :func:`generate_basic_features`); each window uses
    the matching slice.
    """
    if is_bars <= 0 or oos_bars <= 0 or step_bars <= 0:
        raise WalkForwardError("is_bars, oos_bars, and step_bars must be positive")
    if len(bars) < is_bars + oos_bars:
        raise WalkForwardError(
            f"need at least is_bars + oos_bars = {is_bars + oos_bars} bars, "
            f"have {len(bars)}"
        )
    if len(features) != len(bars):
        raise WalkForwardError(
            "features length must match bars length (got "
            f"{len(features)} features, {len(bars)} bars)"
        )
    backtester = VectorizedBacktester(initial_cash=initial_cash)
    windows: list[WalkForwardWindow] = []
    cursor = 0
    window_index = 0
    while cursor + is_bars + oos_bars <= len(bars):
        is_slice = bars[cursor : cursor + is_bars]
        oos_slice = bars[cursor + is_bars : cursor + is_bars + oos_bars]
        is_features = features[cursor : cursor + is_bars]
        oos_features = features[cursor + is_bars : cursor + is_bars + oos_bars]
        is_report = _run_window(backtester, strategy, spec, is_slice, is_features)
        oos_report = _run_window(backtester, strategy, spec, oos_slice, oos_features)
        degradation = is_report.metrics.total_return - oos_report.metrics.total_return
        windows.append(
            WalkForwardWindow(
                window_index=window_index,
                is_bars=is_slice,
                oos_bars=oos_slice,
                is_report=is_report,
                oos_report=oos_report,
                degradation=degradation,
            )
        )
        cursor += step_bars
        window_index += 1
    return _summarize(windows)


def _run_window(
    backtester: VectorizedBacktester,
    strategy: StrategyProtocol,
    spec: StrategySpec,
    bars: list[Bar],
    features: list[FeatureRow],
) -> BacktestReport:
    """Run a single window through the existing vectorized backtester."""
    return backtester.run(strategy, spec=spec, bars=bars, features=features)


def _summarize(windows: list[WalkForwardWindow]) -> WalkForwardResult:
    n = Decimal(len(windows))
    is_avg = sum((w.is_report.metrics.total_return for w in windows), Decimal("0")) / n
    oos_avg = (
        sum((w.oos_report.metrics.total_return for w in windows), Decimal("0")) / n
    )
    avg_deg = sum((w.degradation for w in windows), Decimal("0")) / n
    # Overfit when OOS underperforms IS by more than half of the IS
    # return. For a positive IS run (e.g. +20% IS), an OOS that returns
    # less than +10% (degradation > 50% of IS) trips the flag. For a
    # non-positive IS run, treat any positive degradation as the flag.
    if is_avg > 0:
        threshold = is_avg * Decimal("0.5")
        overfit = avg_deg > threshold
    else:
        overfit = avg_deg > 0
    return WalkForwardResult(
        windows=tuple(windows),
        is_avg_total_return=is_avg,
        oos_avg_total_return=oos_avg,
        avg_degradation=avg_deg,
        overfit_flag=overfit,
    )


__all__ = [
    "WalkForwardError",
    "WalkForwardResult",
    "WalkForwardWindow",
    "run_walk_forward",
]
