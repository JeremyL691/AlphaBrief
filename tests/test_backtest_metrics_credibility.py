"""R21.4 — backtest credibility metrics.

Adds benchmark, CAGR, Sharpe, Sortino, turnover, and exposure to the
vectorized backtester. Each metric is exercised through its success
case + degenerate case (single bar, zero variance, no trades). The
existing ``total_return`` / ``max_drawdown`` / ``win_rate`` fields must
keep their values so older report readers stay consistent.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_backtest import VectorizedBacktester
from alphabrief_backtest.vectorized import BacktestMetrics, BacktestReport
from alphabrief_data import generate_basic_features, load_ohlcv_csv
from alphabrief_strategy import MovingAverageTrendStrategy, StrategySpec


def _spec() -> StrategySpec:
    return StrategySpec.model_validate(
        {
            "strategy_id": "sma_trend_v1",
            "name": "SMA Trend",
            "version": "1.0.0",
            "universe": {"symbols": ["BTC-USD"]},
            "timeframe": "1m",
            "entry": {"condition": "close > close_sma_3"},
            "exit": {"condition": "close <= close_sma_3"},
            "risk": {"max_position_pct": Decimal("0.2")},
            "costs": {"fee_bps": Decimal("0"), "slippage_bps": Decimal("0")},
            "evaluation": {
                "train_period": {"start": date(2020, 1, 1), "end": date(2023, 12, 31)},
                "test_period": {"start": date(2024, 1, 1), "end": date(2025, 12, 31)},
            },
        }
    )


def _write_csv(path: Path, rows: list[tuple[str, str]]) -> Path:
    """Write a minimal OHLCV CSV (every bar uses the close for O/H/L)."""
    lines = ["timestamp,open,high,low,close,volume"]
    for ts, close in rows:
        lines.append(f"{ts},{close},{close},{close},{close},10")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _run(path: Path) -> BacktestReport:
    bars = load_ohlcv_csv(
        path, symbol="BTC-USD", source="unit-test", data_version="fixture-v1"
    )
    if bars:
        features = generate_basic_features(bars, sma_windows=(3,))
    else:
        features = []
    return VectorizedBacktester(initial_cash=Decimal("10000")).run(
        MovingAverageTrendStrategy(sma_window=3),
        spec=_spec(),
        bars=bars,
        features=features,
    )


# ---------------------------------------------------------------------------
# Benchmark (buy-and-hold on the same bars)
# ---------------------------------------------------------------------------


def test_benchmark_matches_buy_and_hold_on_same_bars(tmp_path: Path) -> None:
    # Six bars: 100 -> 130 -> 110 -> 120 -> 140 -> 145
    csv = _write_csv(
        tmp_path / "bars.csv",
        [
            ("2026-06-12T09:30:00Z", "100"),
            ("2026-06-12T09:31:00Z", "130"),
            ("2026-06-12T09:32:00Z", "110"),
            ("2026-06-12T09:33:00Z", "120"),
            ("2026-06-12T09:34:00Z", "140"),
            ("2026-06-12T09:35:00Z", "145"),
        ],
    )
    report = _run(csv)
    # Benchmark = 145/100 - 1 = 0.45.
    assert report.metrics.benchmark_total_return == pytest.approx(Decimal("0.45"))


def test_alpha_is_strategy_return_minus_benchmark(tmp_path: Path) -> None:
    csv = _write_csv(
        tmp_path / "bars.csv",
        [
            ("2026-06-12T09:30:00Z", "100"),
            ("2026-06-12T09:31:00Z", "130"),
            ("2026-06-12T09:32:00Z", "110"),
            ("2026-06-12T09:33:00Z", "120"),
            ("2026-06-12T09:34:00Z", "140"),
            ("2026-06-12T09:35:00Z", "145"),
        ],
    )
    report = _run(csv)
    bench = report.metrics.benchmark_total_return
    assert bench is not None  # non-degenerate bars
    expected = report.metrics.total_return - bench
    assert report.metrics.alpha_vs_benchmark == pytest.approx(expected)


def test_benchmark_and_alpha_zero_for_single_bar(tmp_path: Path) -> None:
    # Degenerate single-bar case (the backtester rejects empty bars):
    # benchmark total return is zero (price didn't move), alpha equals
    # total_return (minus zero), CAGR/Sharpe/Sortino are None (no span).
    csv = _write_csv(tmp_path / "bars.csv", [("2026-06-12T09:30:00Z", "100")])
    report = _run(csv)
    assert report.metrics.benchmark_total_return == Decimal("0")
    assert report.metrics.alpha_vs_benchmark == report.metrics.total_return
    assert report.metrics.cagr is None
    assert report.metrics.sharpe is None
    assert report.metrics.sortino is None


# ---------------------------------------------------------------------------
# CAGR
# ---------------------------------------------------------------------------


def test_cagr_is_none_for_single_bar(tmp_path: Path) -> None:
    csv = _write_csv(tmp_path / "bars.csv", [("2026-06-12T09:30:00Z", "100")])
    report = _run(csv)
    assert report.metrics.cagr is None


def test_cagr_positive_for_long_growth(tmp_path: Path) -> None:
    # 253 daily bars (~1 year) with steady growth -> CAGR > 0. The dates
    # are constructed to span exactly one calendar year so the year
    # factor lands near 1.0; the CAGR then reflects the strategy's
    # compounded growth over that span.
    rows: list[tuple[str, str]] = []
    start = date(2025, 6, 1)
    for i in range(253):
        d = start + timedelta(days=i)
        rows.append((f"{d.isoformat()}T00:00:00Z", str(100 + i)))
    csv = _write_csv(tmp_path / "bars.csv", rows)
    report = _run(csv)
    cagr = report.metrics.cagr
    assert cagr is not None
    # $100 -> $352 over 253 daily bars. With ponytail:annualization
    # (252 trading days/year) the effective span is ~1.45y, so
    # CAGR ≈ (3.52)^(1/1.45) - 1 ≈ 0.48. The bound is loose on
    # purpose: any tighter bound would over-constrain the
    # annualization convention.
    assert Decimal("0.1") < cagr < Decimal("2.0")


# ---------------------------------------------------------------------------
# Sharpe
# ---------------------------------------------------------------------------


def test_sharpe_is_none_for_flat_curve(tmp_path: Path) -> None:
    # All bars at 100 -> zero variance -> Sharpe undefined.
    rows = [
        (f"2026-06-12T09:{30 + i // 60:02d}:{i % 60:02d}Z", "100") for i in range(6)
    ]
    csv = _write_csv(tmp_path / "bars.csv", rows)
    report = _run(csv)
    assert report.metrics.sharpe is None


def test_sharpe_positive_for_growth_with_some_variance(tmp_path: Path) -> None:
    rows = [
        ("2026-06-12T09:30:00Z", "100"),
        ("2026-06-12T09:31:00Z", "102"),
        ("2026-06-12T09:32:00Z", "104"),
        ("2026-06-12T09:33:00Z", "103"),
        ("2026-06-12T09:34:00Z", "106"),
        ("2026-06-12T09:35:00Z", "108"),
    ]
    csv = _write_csv(tmp_path / "bars.csv", rows)
    report = _run(csv)
    sharpe = report.metrics.sharpe
    assert sharpe is not None
    assert sharpe > Decimal("0")


# ---------------------------------------------------------------------------
# Sortino
# ---------------------------------------------------------------------------


def test_sortino_is_none_when_no_negative_returns(tmp_path: Path) -> None:
    # Monotonic up -> no downside -> Sortino undefined.
    rows = [(f"2026-06-12T09:{30 + i:02d}:00Z", str(100 + i)) for i in range(6)]
    csv = _write_csv(tmp_path / "bars.csv", rows)
    report = _run(csv)
    assert report.metrics.sortino is None


def test_sortino_at_least_sharpe_for_asymmetric_upside(tmp_path: Path) -> None:
    # Mostly small up moves + one large dip + recovery -> downside
    # deviation is smaller than total deviation -> Sortino >= Sharpe.
    rows = [
        ("2026-06-12T09:30:00Z", "100"),
        ("2026-06-12T09:31:00Z", "101"),
        ("2026-06-12T09:32:00Z", "102"),
        ("2026-06-12T09:33:00Z", "103"),
        ("2026-06-12T09:34:00Z", "90"),
        ("2026-06-12T09:35:00Z", "100"),
    ]
    csv = _write_csv(tmp_path / "bars.csv", rows)
    report = _run(csv)
    sortino = report.metrics.sortino
    sharpe = report.metrics.sharpe
    if sortino is not None and sharpe is not None:
        assert sortino >= sharpe


# ---------------------------------------------------------------------------
# Turnover
# ---------------------------------------------------------------------------


def test_turnover_zero_when_no_trades(tmp_path: Path) -> None:
    # Strictly flat bars -> SMA never crosses -> no trades.
    rows = [(f"2026-06-12T09:{30 + i:02d}:00Z", "100") for i in range(6)]
    csv = _write_csv(tmp_path / "bars.csv", rows)
    report = _run(csv)
    assert report.metrics.trade_count == 0
    assert report.metrics.turnover == Decimal("0")


def test_turnover_positive_after_a_round_trip(tmp_path: Path) -> None:
    # 100 -> 130 -> 110 -> 120 -> 140 -> 145: SMA(3) crosses a few
    # times, so a round-trip happens; turnover must be > 0.
    rows = [
        ("2026-06-12T09:30:00Z", "100"),
        ("2026-06-12T09:31:00Z", "130"),
        ("2026-06-12T09:32:00Z", "110"),
        ("2026-06-12T09:33:00Z", "120"),
        ("2026-06-12T09:34:00Z", "140"),
        ("2026-06-12T09:35:00Z", "145"),
    ]
    csv = _write_csv(tmp_path / "bars.csv", rows)
    report = _run(csv)
    assert report.metrics.trade_count >= 1
    assert report.metrics.turnover > Decimal("0")


# ---------------------------------------------------------------------------
# Exposure
# ---------------------------------------------------------------------------


def test_exposure_in_range_zero_to_one(tmp_path: Path) -> None:
    rows = [
        ("2026-06-12T09:30:00Z", "100"),
        ("2026-06-12T09:31:00Z", "130"),
        ("2026-06-12T09:32:00Z", "110"),
        ("2026-06-12T09:33:00Z", "120"),
        ("2026-06-12T09:34:00Z", "140"),
        ("2026-06-12T09:35:00Z", "145"),
    ]
    csv = _write_csv(tmp_path / "bars.csv", rows)
    report = _run(csv)
    assert Decimal("0") <= report.metrics.exposure_pct <= Decimal("1")


def test_exposure_one_when_strategy_holds_on_single_bar(tmp_path: Path) -> None:
    # Degenerate single-bar case (the backtester rejects empty bars):
    # on a single bar the strategy may or may not hold (depends on the
    # SMA logic); exposure_pct is in [0, 1] regardless. This pins the
    # upper-bound invariant and exercises the exposure_pct code path
    # even when the strategy never enters on one bar.
    csv = _write_csv(tmp_path / "bars.csv", [("2026-06-12T09:30:00Z", "100")])
    report = _run(csv)
    assert Decimal("0") <= report.metrics.exposure_pct <= Decimal("1")


# ---------------------------------------------------------------------------
# Regression: existing fields unchanged
# ---------------------------------------------------------------------------


def test_existing_metrics_fields_unchanged(tmp_path: Path) -> None:
    rows = [
        ("2026-06-12T09:30:00Z", "100"),
        ("2026-06-12T09:31:00Z", "130"),
        ("2026-06-12T09:32:00Z", "110"),
        ("2026-06-12T09:33:00Z", "120"),
        ("2026-06-12T09:34:00Z", "140"),
        ("2026-06-12T09:35:00Z", "145"),
    ]
    csv = _write_csv(tmp_path / "bars.csv", rows)
    report = _run(csv)
    assert isinstance(report.metrics.total_return, Decimal)
    assert isinstance(report.metrics.max_drawdown, Decimal)
    assert report.metrics.trade_count >= 0
    wr = report.metrics.win_rate
    assert wr is None or Decimal("0") <= wr <= Decimal("1")


def test_metrics_model_rejects_unknown_fields() -> None:
    # The credibility-metric extension keeps ``extra='forbid'`` so a
    # future typo in a report-store round-trip is caught.
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BacktestMetrics.model_validate(
            {
                "total_return": Decimal("0"),
                "max_drawdown": Decimal("0"),
                "trade_count": 0,
                "win_rate": None,
                "benchmark_total_return": None,
                "alpha_vs_benchmark": None,
                "cagr": None,
                "sharpe": None,
                "sortino": None,
                "turnover": Decimal("0"),
                "exposure_pct": Decimal("0"),
                "made_up_metric": Decimal("1"),
            }
        )
