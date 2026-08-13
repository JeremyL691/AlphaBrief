"""M12-W06: parameter stability and overfitting audits.

Covers AC-M12-W06-02: parameter perturbation, subperiod, walk-forward,
and multiple-testing fixtures emit stability metrics and explicit
overfitting warnings.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from alphabrief_backtest import (
    OverfittingAudit,
    WindowSpec,
    best_margin,
    multiple_testing_warning,
    perturbation_stability,
    run_overfitting_audit,
    run_walk_forward_evaluation,
    subperiod_stability,
    walk_forward_warning,
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


def _bars(closes: list[str]) -> list[Bar]:
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
                data_version=DATA_VERSION,
            )
        )
    return bars


def _features(bars: list[Bar]) -> list[FeatureRow]:
    rows: list[FeatureRow] = []
    for bar in bars:
        rows.append(
            FeatureRow(
                symbol=bar.symbol,
                timestamp=bar.timestamp,
                source=bar.source,
                data_version=bar.data_version,
                values={
                    "close_sma_3": Decimal("100"),
                    "close_sma_5": Decimal("100"),
                    "close_sma_10": Decimal("100"),
                },
            )
        )
    return rows


def _trend_factory(params: dict[str, object]) -> TrendFamily:
    return TrendFamily(sma_window=int(cast(Any, params["sma_window"])))


class TestPerturbationStability:
    def test_spread_across_perturbation_grid(self) -> None:
        metric = perturbation_stability(
            {
                "w3": Decimal("0.10"),
                "w5": Decimal("0.04"),
                "w10": Decimal("-0.02"),
            }
        )
        assert metric.name == "perturbation_return_spread"
        assert metric.value == Decimal("0.12")

    def test_single_perturbation_is_undefined(self) -> None:
        metric = perturbation_stability({"w3": Decimal("0.10")})
        assert metric.value is None

    def test_best_margin_from_median(self) -> None:
        metric = best_margin(
            {
                "w3": Decimal("0.03"),
                "w5": Decimal("0.04"),
                "w10": Decimal("0.25"),
            }
        )
        # Sorted: 0.03, 0.04, 0.25 -> median 0.04, margin 0.21.
        assert metric.value == Decimal("0.21")

    def test_best_margin_needs_three_points(self) -> None:
        metric = best_margin({"w3": Decimal("0.10"), "w5": Decimal("0.11")})
        assert metric.value is None


class TestSubperiodStability:
    def test_coefficient_of_variation(self) -> None:
        metric = subperiod_stability(
            (Decimal("0.10"), Decimal("0.10"), Decimal("0.10"))
        )
        assert metric.value == 0

    def test_varying_subperiods_have_positive_cv(self) -> None:
        metric = subperiod_stability(
            (Decimal("0.10"), Decimal("-0.10"), Decimal("0.05"))
        )
        assert metric.value is not None
        assert metric.value > 0

    def test_zero_mean_is_undefined(self) -> None:
        metric = subperiod_stability(
            (Decimal("0.05"), Decimal("-0.05"))
        )
        assert metric.value is None

    def test_single_subperiod_is_undefined(self) -> None:
        metric = subperiod_stability((Decimal("0.05"),))
        assert metric.value is None


class TestMultipleTesting:
    def test_many_trials_warn(self) -> None:
        warning = multiple_testing_warning(50)
        assert warning is not None
        assert warning.code == "multiple_testing"
        assert "50 trials" in warning.message

    def test_few_trials_do_not_warn(self) -> None:
        assert multiple_testing_warning(5) is None
        assert multiple_testing_warning(20) is None


class TestWalkForwardWarning:
    def test_healthy_walk_forward_does_not_warn(self) -> None:
        warning = walk_forward_warning(
            is_avg_total_return=Decimal("0.20"),
            oos_avg_total_return=Decimal("0.15"),
            avg_degradation=Decimal("0.05"),
        )
        assert warning is None

    def test_degraded_walk_forward_warns(self) -> None:
        warning = walk_forward_warning(
            is_avg_total_return=Decimal("0.20"),
            oos_avg_total_return=Decimal("0.05"),
            avg_degradation=Decimal("0.15"),
        )
        assert warning is not None
        assert warning.code == "walk_forward_degradation"

    def test_non_positive_is_any_degradation_warns(self) -> None:
        warning = walk_forward_warning(
            is_avg_total_return=Decimal("-0.05"),
            oos_avg_total_return=Decimal("-0.06"),
            avg_degradation=Decimal("0.01"),
        )
        assert warning is not None

    def test_walk_forward_runner_output_feeds_the_warning(self) -> None:
        closes = [str(100 + (index % 7)) for index in range(120)]
        bars = _bars(closes)
        features = _features(bars)
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
            ),
        )
        warning = walk_forward_warning(
            is_avg_total_return=result.is_avg_total_return,
            oos_avg_total_return=result.oos_avg_total_return,
            avg_degradation=result.avg_degradation,
        )
        # Whatever the fixture produces, the audit mirrors the runner's
        # own overfit_flag semantics.
        assert (warning is not None) == result.overfit_flag


class TestOverfittingAudit:
    def _audit(
        self,
        *,
        returns_by_parameter: Mapping[str, Decimal] | None = None,
        subperiod_returns: tuple[Decimal, ...] | None = None,
        trial_count: int | None = None,
        is_avg_total_return: Decimal | None = None,
        oos_avg_total_return: Decimal | None = None,
        avg_degradation: Decimal | None = None,
    ) -> OverfittingAudit:
        return run_overfitting_audit(
            returns_by_parameter=returns_by_parameter
            or {
                "w3": Decimal("0.10"),
                "w5": Decimal("0.04"),
                "w10": Decimal("-0.02"),
            },
            subperiod_returns=subperiod_returns
            or (
                Decimal("0.10"),
                Decimal("0.04"),
                Decimal("-0.02"),
            ),
            trial_count=trial_count or 5,
            is_avg_total_return=is_avg_total_return or Decimal("0.20"),
            oos_avg_total_return=oos_avg_total_return or Decimal("0.18"),
            avg_degradation=avg_degradation or Decimal("0.02"),
        )

    def test_healthy_audit_passes_with_metrics(self) -> None:
        audit = self._audit()
        assert audit.passed
        assert len(audit.stability_metrics) == 3
        assert {m.name for m in audit.stability_metrics} == {
            "perturbation_return_spread",
            "best_margin",
            "subperiod_cv",
        }

    def test_multiple_testing_warns(self) -> None:
        audit = self._audit(trial_count=100)
        assert not audit.passed
        codes = {w.code for w in audit.warnings}
        assert "multiple_testing" in codes

    def test_walk_forward_degradation_warns(self) -> None:
        audit = self._audit(
            is_avg_total_return=Decimal("0.20"),
            oos_avg_total_return=Decimal("0.02"),
            avg_degradation=Decimal("0.18"),
        )
        assert not audit.passed
        codes = {w.code for w in audit.warnings}
        assert "walk_forward_degradation" in codes

    def test_identical_inputs_produce_identical_audits(self) -> None:
        first = self._audit()
        second = self._audit()
        assert first.model_dump() == second.model_dump()
