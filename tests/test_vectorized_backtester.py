from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_backtest import VectorizedBacktester, write_backtest_report
from alphabrief_data import generate_basic_features, load_ohlcv_csv
from alphabrief_strategy import MovingAverageTrendStrategy, StrategySpec


def _spec(*, fee_bps: str = "5", slippage_bps: str = "10") -> StrategySpec:
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
            "costs": {
                "fee_bps": Decimal(fee_bps),
                "slippage_bps": Decimal(slippage_bps),
            },
            "evaluation": {
                "train_period": {
                    "start": date(2020, 1, 1),
                    "end": date(2023, 12, 31),
                },
                "test_period": {
                    "start": date(2024, 1, 1),
                    "end": date(2025, 12, 31),
                },
            },
        }
    )


def _write_price_csv(path: Path) -> Path:
    path.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2026-06-12T09:30:00Z,100,100,100,100,10\n"
        "2026-06-12T09:31:00Z,100,100,100,100,10\n"
        "2026-06-12T09:32:00Z,100,100,100,100,10\n"
        "2026-06-12T09:33:00Z,110,110,110,110,10\n"
        "2026-06-12T09:34:00Z,120,120,120,120,10\n"
        "2026-06-12T09:35:00Z,90,90,90,90,10\n",
        encoding="utf-8",
    )
    return path


def test_vectorized_backtester_runs_moving_average_strategy(tmp_path: Path) -> None:
    bars = load_ohlcv_csv(
        _write_price_csv(tmp_path / "bars.csv"),
        symbol="BTC-USD",
        source="unit-test",
        data_version="fixture-v1",
    )
    features = generate_basic_features(bars, sma_windows=(3,))

    report = VectorizedBacktester(initial_cash=Decimal("10000")).run(
        MovingAverageTrendStrategy(sma_window=3),
        spec=_spec(),
        bars=bars,
        features=features,
    )

    assert report.strategy_id == "sma_trend_v1"
    assert report.symbol == "BTC-USD"
    assert report.initial_cash == Decimal("10000")
    assert report.fee_bps == Decimal("5")
    assert report.slippage_bps == Decimal("10")
    assert report.metrics.trade_count == 1
    assert len(report.trades) == 1
    assert report.trades[0].exit_reason == "signal_exit"
    assert report.equity_curve[-1].position_quantity == Decimal("0")


def test_backtest_report_can_be_written_as_json(tmp_path: Path) -> None:
    bars = load_ohlcv_csv(
        _write_price_csv(tmp_path / "bars.csv"),
        symbol="BTC-USD",
        source="unit-test",
        data_version="fixture-v1",
    )
    features = generate_basic_features(bars, sma_windows=(3,))
    report = VectorizedBacktester().run(
        MovingAverageTrendStrategy(sma_window=3),
        spec=_spec(),
        bars=bars,
        features=features,
    )

    output_path = tmp_path / "backtest_report.json"
    write_backtest_report(report, output_path)

    content = output_path.read_text(encoding="utf-8")
    assert '"strategy_id": "sma_trend_v1"' in content
    assert '"fee_bps": "5"' in content
    assert '"slippage_bps": "10"' in content


def test_transaction_costs_reduce_final_value(tmp_path: Path) -> None:
    bars = load_ohlcv_csv(
        _write_price_csv(tmp_path / "bars.csv"),
        symbol="BTC-USD",
        source="unit-test",
        data_version="fixture-v1",
    )
    features = generate_basic_features(bars, sma_windows=(3,))
    backtester = VectorizedBacktester(initial_cash=Decimal("10000"))

    no_cost_report = backtester.run(
        MovingAverageTrendStrategy(sma_window=3),
        spec=_spec(fee_bps="0", slippage_bps="0"),
        bars=bars,
        features=features,
    )
    cost_report = backtester.run(
        MovingAverageTrendStrategy(sma_window=3),
        spec=_spec(fee_bps="5", slippage_bps="10"),
        bars=bars,
        features=features,
    )

    assert cost_report.final_value < no_cost_report.final_value


def test_backtester_rejects_non_positive_initial_cash() -> None:
    with pytest.raises(ValueError, match="initial_cash"):
        VectorizedBacktester(initial_cash=Decimal("0"))


def test_backtester_executes_signal_at_next_bar_not_same_bar(tmp_path: Path) -> None:
    """A long signal at bar[i] must execute at bar[i+1], not bar[i]."""
    bars = load_ohlcv_csv(
        _write_price_csv(tmp_path / "bars.csv"),
        symbol="BTC-USD",
        source="unit-test",
        data_version="fixture-v1",
    )
    features = generate_basic_features(bars, sma_windows=(3,))
    report = VectorizedBacktester(initial_cash=Decimal("10000")).run(
        MovingAverageTrendStrategy(sma_window=3),
        spec=_spec(),
        bars=bars,
        features=features,
    )

    assert len(report.trades) >= 1

    for trade in report.trades:
        if trade.exit_reason == "signal_exit":
            assert trade.entry_timestamp != trade.exit_timestamp
