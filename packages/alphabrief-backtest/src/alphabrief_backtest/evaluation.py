"""Reproducible IS/OOS and walk-forward evaluation (M12-W04).

True in-sample / out-of-sample evaluation with rolling and anchored
walk-forward windows. Parameters are fitted only on declared in-sample
observations and frozen for the out-of-sample run; the out-of-sample
slice is structurally isolated (later observations, later revisions,
and undisclosed data versions are unreachable). Repeating a run with
the same strategy, data version, costs, seed, and window specification
yields the same run ID and the same normalized result (REQ-STRAT-003,
REQ-PLAT-009).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Literal

from alphabrief_core import Bar
from alphabrief_data import FeatureRow
from alphabrief_strategy import StrategyProtocol, StrategySpec
from pydantic import BaseModel, ConfigDict, Field, model_validator

from alphabrief_backtest.vectorized import (
    BacktestMetrics,
    BacktestReport,
    VectorizedBacktester,
)

WalkForwardMode = Literal["rolling", "anchored"]


class WalkForwardEvaluationError(ValueError):
    """Raised when a walk-forward evaluation cannot be configured."""


class WindowSpec(BaseModel):
    """One deterministic IS/OOS window specification.

    ``step_bars >= oos_bars`` is enforced so successive OOS slices never
    overlap: decision boundaries advance monotonically without overlap
    in both modes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: WalkForwardMode = "rolling"
    is_bars: int = Field(ge=1)
    oos_bars: int = Field(ge=1)
    step_bars: int = Field(ge=1)

    @model_validator(mode="after")
    def step_must_not_shrink_oos_windows(self) -> WindowSpec:
        if self.step_bars < self.oos_bars:
            raise ValueError(
                "step_bars must be >= oos_bars so OOS windows never overlap"
            )
        return self

    def window_bounds(
        self, window_index: int
    ) -> tuple[int, int, int, int]:
        """(is_start, is_end, oos_start, oos_end) bar indices."""
        if self.mode == "anchored":
            is_start = 0
        else:
            is_start = window_index * self.step_bars
        is_end = window_index * self.step_bars + self.is_bars
        oos_start = is_end
        oos_end = oos_start + self.oos_bars
        return is_start, is_end, oos_start, oos_end


class FittedParameters(BaseModel):
    """The deterministic parameter snapshot fitted on IS only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    family_id: str = Field(min_length=1)
    data_version: str = Field(min_length=1)
    is_start: datetime
    is_end: datetime
    parameters: dict[str, object]
    is_total_return: Decimal
    algorithm_version: str = Field(min_length=1)


class EvaluationWindow(BaseModel):
    """One window: fitted IS decision, frozen-parameter OOS result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    window_index: int = Field(ge=0)
    mode: WalkForwardMode
    is_start: datetime
    is_end: datetime
    oos_start: datetime
    oos_end: datetime
    fitted_parameters: FittedParameters
    is_metrics: BacktestMetrics
    oos_metrics: BacktestMetrics
    oos_benchmark_total_return: Decimal | None
    degradation: Decimal


class WalkForwardEvaluationResult(BaseModel):
    """The aggregate reproducible walk-forward outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    family_id: str = Field(min_length=1)
    data_version: str = Field(min_length=1)
    window_spec: WindowSpec
    initial_cash: Decimal
    seed: str | None
    windows: tuple[EvaluationWindow, ...]
    is_avg_total_return: Decimal
    oos_avg_total_return: Decimal
    avg_degradation: Decimal
    overfit_flag: bool
    benchmark_avg_total_return: Decimal | None

    def normalized_json(self) -> str:
        """Canonical serialization: identical inputs -> identical bytes."""
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )


def _fingerprint(bars: list[Bar], features: list[FeatureRow]) -> str:
    """Deterministic content fingerprint of bars and features."""
    bar_rows = [
        (
            bar.timestamp.isoformat(),
            str(bar.close),
            str(bar.volume),
        )
        for bar in bars
    ]
    feature_rows = [
        tuple(
            (key, None if value is None else str(value))
            for key, value in sorted(feature.values.items())
        )
        for feature in features
    ]
    payload = json.dumps(
        [bar_rows, feature_rows],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_evaluation_run_id(
    *,
    spec: StrategySpec,
    family_id: str,
    data_version: str,
    window_spec: WindowSpec,
    parameter_grid: tuple[dict[str, object], ...],
    initial_cash: Decimal,
    seed: str | None,
    bars: list[Bar],
    features: list[FeatureRow],
) -> str:
    """The deterministic run ID binding every result-relevant input."""
    payload = {
        "strategy_id": spec.strategy_id,
        "strategy_version": spec.version,
        "family_id": family_id,
        "data_version": data_version,
        "window_spec": window_spec.model_dump(mode="json"),
        "parameter_grid": [
            {key: str(value) for key, value in params.items()}
            for params in parameter_grid
        ],
        "initial_cash": str(initial_cash),
        "seed": seed,
        "fee_bps": str(spec.costs.fee_bps),
        "slippage_bps": str(spec.costs.slippage_bps),
        "bars_fingerprint": _fingerprint(bars, features),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_data_version(bars: list[Bar], data_version: str) -> None:
    """Every bar must carry the declared immutable data version."""
    for bar in bars:
        if bar.data_version != data_version:
            raise WalkForwardEvaluationError(
                f"bar {bar.timestamp.isoformat()} uses data version "
                f"{bar.data_version!r}, not the declared {data_version!r}"
            )


def _fit_parameters(
    backtester: VectorizedBacktester,
    strategy_factory: Callable[[dict[str, object]], StrategyProtocol],
    *,
    spec: StrategySpec,
    family_id: str,
    data_version: str,
    is_bars: list[Bar],
    is_features: list[FeatureRow],
    parameter_grid: tuple[dict[str, object], ...],
) -> tuple[FittedParameters, BacktestReport]:
    """Fit parameters on the declared IS slice only.

    The best candidate maximizes IS total return; ties resolve to the
    first candidate in grid order. The fitter never receives OOS bars.
    """
    best_params: dict[str, object] = parameter_grid[0]
    best_score = Decimal("-Infinity")
    best_report: BacktestReport | None = None
    for candidate in parameter_grid:
        strategy = strategy_factory(candidate)
        report = backtester.run(
            strategy,
            spec=spec,
            bars=is_bars,
            features=is_features,
        )
        score = report.metrics.total_return
        if score > best_score:
            best_score = score
            best_params = candidate
            best_report = report
    assert best_report is not None
    fitted = FittedParameters(
        strategy_id=spec.strategy_id,
        strategy_version=spec.version,
        family_id=family_id,
        data_version=data_version,
        is_start=is_bars[0].timestamp,
        is_end=is_bars[-1].timestamp,
        parameters=dict(best_params),
        is_total_return=best_score,
        algorithm_version="walk-forward-fit-1",
    )
    return fitted, best_report


def run_walk_forward_evaluation(
    strategy_factory: Callable[[dict[str, object]], StrategyProtocol],
    *,
    spec: StrategySpec,
    bars: list[Bar],
    features: list[FeatureRow],
    data_version: str,
    window_spec: WindowSpec,
    parameter_grid: tuple[dict[str, object], ...],
    initial_cash: Decimal = Decimal("10000"),
    seed: str | None = None,
) -> WalkForwardEvaluationResult:
    """Run reproducible rolling or anchored walk-forward evaluation.

    ``strategy_factory`` builds a strategy instance from one candidate
    parameter dict; the fitted parameters are frozen for every OOS run.
    ``seed`` is accepted for interface symmetry and bound into the run
    ID; the evaluation itself is fully deterministic and uses no RNG.
    """
    if not parameter_grid:
        raise WalkForwardEvaluationError("parameter_grid must not be empty")
    if len(bars) < window_spec.is_bars + window_spec.oos_bars:
        raise WalkForwardEvaluationError(
            f"need at least is_bars + oos_bars = "
            f"{window_spec.is_bars + window_spec.oos_bars} bars, "
            f"have {len(bars)}"
        )
    if len(features) != len(bars):
        raise WalkForwardEvaluationError(
            "features length must match bars length (got "
            f"{len(features)} features, {len(bars)} bars)"
        )
    _validate_data_version(bars, data_version)

    backtester = VectorizedBacktester(initial_cash=initial_cash)
    windows: list[EvaluationWindow] = []
    window_index = 0
    while True:
        is_start, is_end, oos_start, oos_end = window_spec.window_bounds(
            window_index
        )
        if oos_end > len(bars):
            break
        is_slice = bars[is_start:is_end]
        oos_slice = bars[oos_start:oos_end]
        is_features = features[is_start:is_end]
        oos_features = features[oos_start:oos_end]

        fitted, is_report = _fit_parameters(
            backtester,
            strategy_factory,
            spec=spec,
            family_id=_family_id(strategy_factory, parameter_grid[0]),
            data_version=data_version,
            is_bars=is_slice,
            is_features=is_features,
            parameter_grid=parameter_grid,
        )
        frozen_strategy = strategy_factory(fitted.parameters)
        oos_report = backtester.run(
            frozen_strategy,
            spec=spec,
            bars=oos_slice,
            features=oos_features,
        )
        degradation = (
            is_report.metrics.total_return - oos_report.metrics.total_return
        )
        windows.append(
            EvaluationWindow(
                window_index=window_index,
                mode=window_spec.mode,
                is_start=is_slice[0].timestamp,
                is_end=is_slice[-1].timestamp,
                oos_start=oos_slice[0].timestamp,
                oos_end=oos_slice[-1].timestamp,
                fitted_parameters=fitted,
                is_metrics=is_report.metrics,
                oos_metrics=oos_report.metrics,
                oos_benchmark_total_return=(
                    oos_report.metrics.benchmark_total_return
                ),
                degradation=degradation,
            )
        )
        window_index += 1

    run_id = compute_evaluation_run_id(
        spec=spec,
        family_id=_family_id(strategy_factory, parameter_grid[0]),
        data_version=data_version,
        window_spec=window_spec,
        parameter_grid=parameter_grid,
        initial_cash=initial_cash,
        seed=seed,
        bars=bars,
        features=features,
    )
    return _summarize_evaluation(
        run_id=run_id,
        spec=spec,
        family_id=_family_id(strategy_factory, parameter_grid[0]),
        data_version=data_version,
        window_spec=window_spec,
        initial_cash=initial_cash,
        seed=seed,
        windows=windows,
    )


def _family_id(
    strategy_factory: Callable[[dict[str, object]], object],
    sample_params: dict[str, object],
) -> str:
    """The fitted family id, or 'custom' for non-family strategies."""
    instance = strategy_factory(sample_params)
    return str(getattr(instance, "family_id", "custom"))


def _summarize_evaluation(
    *,
    run_id: str,
    spec: StrategySpec,
    family_id: str,
    data_version: str,
    window_spec: WindowSpec,
    initial_cash: Decimal,
    seed: str | None,
    windows: list[EvaluationWindow],
) -> WalkForwardEvaluationResult:
    count = Decimal(len(windows))
    is_avg = (
        sum((w.is_metrics.total_return for w in windows), Decimal("0")) / count
    )
    oos_avg = (
        sum((w.oos_metrics.total_return for w in windows), Decimal("0")) / count
    )
    avg_degradation = sum((w.degradation for w in windows), Decimal("0")) / count
    if is_avg > 0:
        overfit = avg_degradation > is_avg * Decimal("0.5")
    else:
        overfit = avg_degradation > 0
    benchmarks = [
        w.oos_benchmark_total_return
        for w in windows
        if w.oos_benchmark_total_return is not None
    ]
    benchmark_avg = (
        sum(benchmarks, Decimal("0")) / Decimal(len(benchmarks))
        if benchmarks
        else None
    )
    return WalkForwardEvaluationResult(
        run_id=run_id,
        strategy_id=spec.strategy_id,
        strategy_version=spec.version,
        family_id=family_id,
        data_version=data_version,
        window_spec=window_spec,
        initial_cash=initial_cash,
        seed=seed,
        windows=tuple(windows),
        is_avg_total_return=is_avg,
        oos_avg_total_return=oos_avg,
        avg_degradation=avg_degradation,
        overfit_flag=overfit,
        benchmark_avg_total_return=benchmark_avg,
    )


__all__ = [
    "EvaluationWindow",
    "FittedParameters",
    "WalkForwardEvaluationError",
    "WalkForwardEvaluationResult",
    "WalkForwardMode",
    "WindowSpec",
    "compute_evaluation_run_id",
    "run_walk_forward_evaluation",
]
