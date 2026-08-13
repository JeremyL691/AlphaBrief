"""M12-W04: run ID and normalized-result reproducibility.

Covers AC-M12-W04-03: repeating a run with the same strategy, data
version, costs, seed, and window specification yields the same run ID
and normalized result; every result-relevant input is bound into the
run ID (REQ-PLAT-009).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from alphabrief_backtest import (
    WalkForwardEvaluationResult,
    WindowSpec,
    compute_evaluation_run_id,
    run_walk_forward_evaluation,
)
from alphabrief_core import Bar
from alphabrief_data import FeatureRow
from alphabrief_strategy import StrategySpec, TrendFamily

DATA_VERSION = "fixture-data-v1"


def _spec(
    *,
    strategy_id: str = "trend_fit_v1",
    fee_bps: str = "2",
    slippage_bps: str = "0",
) -> StrategySpec:
    return StrategySpec.model_validate(
        {
            "strategy_id": strategy_id,
            "name": "Trend Fit",
            "version": "1.0.0",
            "universe": {"symbols": ["SPY"]},
            "timeframe": "1d",
            "entry": {"condition": "close > close_sma_20"},
            "exit": {"condition": "close < close_sma_20"},
            "risk": {"max_position_pct": Decimal("0.5")},
            "costs": {
                "fee_bps": Decimal(fee_bps),
                "slippage_bps": Decimal(slippage_bps),
            },
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
        rows.append(
            FeatureRow(
                symbol=bar.symbol,
                timestamp=bar.timestamp,
                source=bar.source,
                data_version=bar.data_version,
                values={
                    "close_sma_3": Decimal("100"),
                    "close_sma_5": Decimal("100"),
                },
            )
        )
    return rows


def _trend_factory(params: dict[str, object]) -> TrendFamily:
    return TrendFamily(sma_window=int(cast(Any, params["sma_window"])))


def _run(
    *,
    spec: StrategySpec | None = None,
    bars: list[Bar] | None = None,
    features: list[FeatureRow] | None = None,
    data_version: str = DATA_VERSION,
    window_spec: WindowSpec | None = None,
    grid: tuple[dict[str, object], ...] = (
        {"sma_window": 3},
        {"sma_window": 5},
    ),
    seed: str | None = "seed-1",
    fee_bps: str | None = None,
) -> WalkForwardEvaluationResult:
    bars = bars or _bars([str(100 + (index % 7)) for index in range(120)])
    features = features or _features(bars)
    spec = spec or _spec(fee_bps=fee_bps or "2")
    return run_walk_forward_evaluation(
        _trend_factory,
        spec=spec,
        bars=bars,
        features=features,
        data_version=data_version,
        window_spec=window_spec
        or WindowSpec(mode="rolling", is_bars=30, oos_bars=10, step_bars=10),
        parameter_grid=grid,
        seed=seed,
    )


class TestRunReproducibility:
    def test_identical_inputs_yield_identical_run_id(self) -> None:
        first = _run()
        second = _run()
        assert first.run_id == second.run_id
        assert len(first.run_id) == 64  # sha256 hex

    def test_identical_inputs_yield_identical_normalized_result(self) -> None:
        first = _run()
        second = _run()
        assert first.normalized_json() == second.normalized_json()
        assert first.model_dump() == second.model_dump()

    def test_seed_is_bound_into_the_run_id(self) -> None:
        assert _run(seed="seed-1").run_id != _run(seed="seed-2").run_id

    def test_window_spec_is_bound_into_the_run_id(self) -> None:
        rolling = _run(
            window_spec=WindowSpec(
                mode="rolling", is_bars=30, oos_bars=10, step_bars=10
            )
        )
        anchored = _run(
            window_spec=WindowSpec(
                mode="anchored", is_bars=30, oos_bars=10, step_bars=10
            )
        )
        assert rolling.run_id != anchored.run_id

    def test_data_version_is_bound_into_the_run_id(self) -> None:
        bars = _bars([str(100 + (index % 7)) for index in range(120)])
        other = [bar.model_copy(update={"data_version": "v2"}) for bar in bars]
        assert _run().run_id != _run(bars=other, data_version="v2").run_id

    def test_costs_are_bound_into_the_run_id(self) -> None:
        assert _run().run_id != _run(spec=_spec(fee_bps="5")).run_id

    def test_parameter_grid_is_bound_into_the_run_id(self) -> None:
        single = _run(grid=({"sma_window": 3},))
        double = _run(grid=({"sma_window": 3}, {"sma_window": 5}))
        assert single.run_id != double.run_id

    def test_strategy_identity_is_bound_into_the_run_id(self) -> None:
        assert _run(spec=_spec(strategy_id="other_v1")).run_id != _run().run_id

    def test_bar_content_is_bound_into_the_run_id(self) -> None:
        bars = _bars([str(100 + (index % 7)) for index in range(120)])
        changed = [
            bar.model_copy(
                update={"close": bar.close + 1, "high": bar.close + 1}
            )
            for bar in bars
        ]
        assert _run(bars=changed).run_id != _run().run_id

    def test_deterministic_fit_picks_the_same_parameters(self) -> None:
        first = _run()
        second = _run()
        for window_a, window_b in zip(
            first.windows, second.windows, strict=True
        ):
            assert window_a.fitted_parameters.parameters == (
                window_b.fitted_parameters.parameters
            )
            assert window_a.oos_metrics == window_b.oos_metrics


class TestRunIdContract:
    def test_run_id_changes_when_declared_version_differs(self) -> None:
        bars = _bars([str(100)] * 120, version="declared-v1")
        features = _features(bars)
        first = compute_evaluation_run_id(
            spec=_spec(),
            family_id="trend",
            data_version="declared-v1",
            window_spec=WindowSpec(
                mode="rolling", is_bars=30, oos_bars=10, step_bars=10
            ),
            parameter_grid=({"sma_window": 3},),
            initial_cash=Decimal("10000"),
            seed="s",
            bars=bars,
            features=features,
        )
        second = compute_evaluation_run_id(
            spec=_spec(),
            family_id="trend",
            data_version="declared-v2",
            window_spec=WindowSpec(
                mode="rolling", is_bars=30, oos_bars=10, step_bars=10
            ),
            parameter_grid=({"sma_window": 3},),
            initial_cash=Decimal("10000"),
            seed="s",
            bars=bars,
            features=features,
        )
        assert first != second
        # Same inputs hash to the same id deterministically.
        third = compute_evaluation_run_id(
            spec=_spec(),
            family_id="trend",
            data_version="declared-v1",
            window_spec=WindowSpec(
                mode="rolling", is_bars=30, oos_bars=10, step_bars=10
            ),
            parameter_grid=({"sma_window": 3},),
            initial_cash=Decimal("10000"),
            seed="s",
            bars=bars,
            features=features,
        )
        assert third == first
