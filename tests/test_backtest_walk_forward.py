"""M12-W04: reproducible IS/OOS walk-forward evaluation.

Covers AC-M12-W04-01/02: rolling and anchored fixtures create
non-overlapping decision boundaries with parameters fitted only on
declared in-sample observations; out-of-sample execution uses frozen
parameters and cannot access later observations, later revisions, or
undisclosed data versions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from alphabrief_backtest import (
    FittedParameters,
    VectorizedBacktester,
    WalkForwardEvaluationError,
    WindowSpec,
    run_walk_forward_evaluation,
)
from alphabrief_core import Bar
from alphabrief_data import FeatureRow
from alphabrief_strategy import StrategySpec, TrendFamily

DATA_VERSION = "fixture-data-v1"


def _spec() -> StrategySpec:
    return StrategySpec.model_validate(
        {
            "strategy_id": "trend_fit_v1",
            "name": "Trend Fit",
            "version": "1.0.0",
            "universe": {"symbols": ["SPY"]},
            "timeframe": "1d",
            "entry": {"condition": "close > close_sma_20"},
            "exit": {"condition": "close < close_sma_20"},
            "risk": {"max_position_pct": Decimal("0.5")},
            "costs": {"fee_bps": Decimal("2"), "slippage_bps": Decimal("0")},
            "evaluation": {
                "train_period": {"start": "2024-01-01", "end": "2024-12-31"},
                "test_period": {"start": "2025-01-01", "end": "2025-12-31"},
            },
        }
    )


def _bars(closes: list[str], *, version: str = DATA_VERSION) -> list[Bar]:
    bars: list[Bar] = []
    for index, close in enumerate(closes):
        bars.append(
            Bar(
                symbol="SPY",
                timestamp=datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
                + timedelta(seconds=index),
                open=Decimal(close),
                high=Decimal(close),
                low=Decimal(close),
                close=Decimal(close),
                volume=Decimal("10"),
                source="unit-test",
                data_version=version,
            )
        )
    return bars


def _features(bars: list[Bar]) -> list[FeatureRow]:
    rows: list[FeatureRow] = []
    for bar in bars:
        values: dict[str, Decimal | None] = {}
        for window in (3, 5, 10):
            values[f"close_sma_{window}"] = Decimal("100")
        rows.append(
            FeatureRow(
                symbol=bar.symbol,
                timestamp=bar.timestamp,
                source=bar.source,
                data_version=bar.data_version,
                values=values,
            )
        )
    return rows


def _trend_factory(params: dict[str, object]) -> TrendFamily:
    return TrendFamily(sma_window=int(cast(Any, params["sma_window"])))


def _input(closes: list[str]) -> tuple[list[Bar], list[FeatureRow]]:
    bars = _bars(closes)
    return bars, _features(bars)


def _fit_is_only(
    bars: list[Bar],
    features: list[FeatureRow],
    spec: StrategySpec,
) -> FittedParameters:
    """Independent IS-only fit: prove the runner fit on IS exclusively."""
    backtester = VectorizedBacktester(initial_cash=Decimal("10000"))
    best_params: dict[str, object] = {"sma_window": 3}
    best_score = Decimal("-Infinity")
    for window in (3, 5, 10):
        report = backtester.run(
            _trend_factory({"sma_window": window}),
            spec=spec,
            bars=bars,
            features=features,
        )
        if report.metrics.total_return > best_score:
            best_score = report.metrics.total_return
            best_params = {"sma_window": window}
    return FittedParameters(
        strategy_id=spec.strategy_id,
        strategy_version=spec.version,
        family_id="trend",
        data_version=DATA_VERSION,
        is_start=bars[0].timestamp,
        is_end=bars[-1].timestamp,
        parameters=best_params,
        is_total_return=best_score,
        algorithm_version="walk-forward-fit-1",
    )


class TestRollingWindows:
    def test_decision_boundaries_are_non_overlapping(self) -> None:
        closes = [str(100 + (index % 7)) for index in range(120)]
        bars, features = _input(closes)
        result = run_walk_forward_evaluation(
            _trend_factory,
            spec=_spec(),
            bars=bars,
            features=features,
            data_version=DATA_VERSION,
            window_spec=WindowSpec(
                mode="rolling", is_bars=30, oos_bars=10, step_bars=10
            ),
            parameter_grid=(
                {"sma_window": 3},
                {"sma_window": 5},
                {"sma_window": 10},
            ),
        )
        assert len(result.windows) >= 2
        previous_oos_end: datetime | None = None
        for window in result.windows:
            # The decision boundary separates IS from OOS: OOS starts
            # immediately after IS ends (never before it).
            assert window.oos_start > window.is_end
            assert window.oos_end > window.oos_start
            if previous_oos_end is not None:
                # Successive OOS slices never overlap.
                assert window.oos_start >= previous_oos_end
            previous_oos_end = window.oos_end

    def test_parameters_fitted_only_on_declared_is_observations(self) -> None:
        closes = [str(100 + (index % 7)) for index in range(120)]
        bars, features = _input(closes)
        spec = _spec()
        result = run_walk_forward_evaluation(
            _trend_factory,
            spec=spec,
            bars=bars,
            features=features,
            data_version=DATA_VERSION,
            window_spec=WindowSpec(
                mode="rolling", is_bars=30, oos_bars=10, step_bars=10
            ),
            parameter_grid=(
                {"sma_window": 3},
                {"sma_window": 5},
                {"sma_window": 10},
            ),
        )
        first = result.windows[0]
        is_slice = bars[:30]
        is_features = features[:30]
        expected = _fit_is_only(is_slice, is_features, spec)
        assert first.fitted_parameters.parameters == expected.parameters
        assert first.fitted_parameters.is_total_return == (
            expected.is_total_return
        )
        assert first.fitted_parameters.is_start == is_slice[0].timestamp
        assert first.fitted_parameters.is_end == is_slice[-1].timestamp
        assert first.fitted_parameters.data_version == DATA_VERSION

    def test_oos_metrics_equal_standalone_run_on_the_slice(self) -> None:
        closes = [str(100 + (index % 7)) for index in range(120)]
        bars, features = _input(closes)
        spec = _spec()
        result = run_walk_forward_evaluation(
            _trend_factory,
            spec=spec,
            bars=bars,
            features=features,
            data_version=DATA_VERSION,
            window_spec=WindowSpec(
                mode="rolling", is_bars=30, oos_bars=10, step_bars=10
            ),
            parameter_grid=({"sma_window": 3}, {"sma_window": 5}),
        )
        window = result.windows[0]
        oos_bars = bars[30:40]
        oos_features = features[30:40]
        standalone = VectorizedBacktester(initial_cash=Decimal("10000")).run(
            _trend_factory(window.fitted_parameters.parameters),
            spec=spec,
            bars=oos_bars,
            features=oos_features,
        )
        # The frozen-parameter OOS run only ever saw its own slice.
        assert window.oos_metrics == standalone.metrics
        assert window.oos_metrics.trade_count == standalone.metrics.trade_count


class TestAnchoredWindows:
    def test_anchored_is_starts_at_the_first_bar_and_grows(self) -> None:
        closes = [str(100 + (index % 7)) for index in range(120)]
        bars, features = _input(closes)
        result = run_walk_forward_evaluation(
            _trend_factory,
            spec=_spec(),
            bars=bars,
            features=features,
            data_version=DATA_VERSION,
            window_spec=WindowSpec(
                mode="anchored", is_bars=30, oos_bars=10, step_bars=10
            ),
            parameter_grid=({"sma_window": 3}, {"sma_window": 5}),
        )
        assert len(result.windows) >= 2
        for window in result.windows:
            assert window.is_start == bars[0].timestamp
            assert window.oos_start > window.is_end
        # IS grows and OOS slices are adjacent and non-overlapping.
        assert result.windows[1].is_end > result.windows[0].is_end
        assert result.windows[1].oos_start >= result.windows[0].oos_end

    def test_anchored_mode_is_recorded_on_every_window(self) -> None:
        closes = [str(100 + (index % 7)) for index in range(120)]
        bars, features = _input(closes)
        result = run_walk_forward_evaluation(
            _trend_factory,
            spec=_spec(),
            bars=bars,
            features=features,
            data_version=DATA_VERSION,
            window_spec=WindowSpec(
                mode="anchored", is_bars=30, oos_bars=10, step_bars=10
            ),
            parameter_grid=({"sma_window": 3},),
        )
        assert all(w.mode == "anchored" for w in result.windows)


class TestWindowSpecValidation:
    def test_step_smaller_than_oos_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="never overlap"):
            WindowSpec(mode="rolling", is_bars=30, oos_bars=10, step_bars=5)

    def test_non_positive_windows_are_rejected(self) -> None:
        with pytest.raises(ValueError):
            WindowSpec(mode="rolling", is_bars=0, oos_bars=10, step_bars=10)

    def test_empty_parameter_grid_is_rejected(self) -> None:
        bars, features = _input([str(100)] * 60)
        with pytest.raises(WalkForwardEvaluationError, match="empty"):
            run_walk_forward_evaluation(
                _trend_factory,
                spec=_spec(),
                bars=bars,
                features=features,
                data_version=DATA_VERSION,
                window_spec=WindowSpec(
                    mode="rolling", is_bars=30, oos_bars=10, step_bars=10
                ),
                parameter_grid=(),
            )

    def test_insufficient_bars_are_rejected(self) -> None:
        bars, features = _input([str(100)] * 30)
        with pytest.raises(WalkForwardEvaluationError, match="need at least"):
            run_walk_forward_evaluation(
                _trend_factory,
                spec=_spec(),
                bars=bars,
                features=features,
                data_version=DATA_VERSION,
                window_spec=WindowSpec(
                    mode="rolling", is_bars=30, oos_bars=10, step_bars=10
                ),
                parameter_grid=({"sma_window": 3},),
            )


class TestDataVersionIsolation:
    def test_undisclosed_data_version_is_rejected(self) -> None:
        bars, _ = _input([str(100)] * 60)
        # One bar silently carries a different (later) data version.
        bars[40] = bars[40].model_copy(
            update={"data_version": "fixture-data-v2"}
        )
        features = _features(bars)
        with pytest.raises(WalkForwardEvaluationError, match="data version"):
            run_walk_forward_evaluation(
                _trend_factory,
                spec=_spec(),
                bars=bars,
                features=features,
                data_version=DATA_VERSION,
                window_spec=WindowSpec(
                    mode="rolling", is_bars=30, oos_bars=10, step_bars=10
                ),
                parameter_grid=({"sma_window": 3},),
            )

    def test_every_window_records_the_declared_data_version(self) -> None:
        closes = [str(100 + (index % 7)) for index in range(120)]
        bars, features = _input(closes)
        result = run_walk_forward_evaluation(
            _trend_factory,
            spec=_spec(),
            bars=bars,
            features=features,
            data_version=DATA_VERSION,
            window_spec=WindowSpec(
                mode="rolling", is_bars=30, oos_bars=10, step_bars=10
            ),
            parameter_grid=({"sma_window": 3}, {"sma_window": 5}),
        )
        assert result.data_version == DATA_VERSION
        assert all(
            w.fitted_parameters.data_version == DATA_VERSION
            for w in result.windows
        )

    def test_frozen_parameters_are_used_for_every_oos_run(self) -> None:
        closes = [str(100 + (index % 7)) for index in range(120)]
        bars, features = _input(closes)
        result = run_walk_forward_evaluation(
            _trend_factory,
            spec=_spec(),
            bars=bars,
            features=features,
            data_version=DATA_VERSION,
            window_spec=WindowSpec(
                mode="rolling", is_bars=30, oos_bars=10, step_bars=10
            ),
            parameter_grid=(
                {"sma_window": 3},
                {"sma_window": 5},
                {"sma_window": 10},
            ),
        )
        for window in result.windows:
            chosen = window.fitted_parameters.parameters
            assert chosen["sma_window"] in (3, 5, 10)
            # The frozen instance on that window's OOS slice reproduces
            # the recorded oos_metrics.
            oos_bars = [
                bar
                for bar in bars
                if window.oos_start <= bar.timestamp <= window.oos_end
            ]
            oos_features = [
                feature
                for feature in features
                if window.oos_start
                <= feature.timestamp
                <= window.oos_end
            ]
            standalone = VectorizedBacktester(initial_cash=Decimal("10000")).run(
                _trend_factory(chosen),
                spec=_spec(),
                bars=oos_bars,
                features=oos_features,
            )
            assert window.oos_metrics == standalone.metrics
