from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from alphabrief_core import Bar, Signal
from alphabrief_data import FeatureRow, generate_basic_features
from alphabrief_strategy import (
    StrategyExecutionError,
    StrategyInput,
    StrategyOutput,
    StrategySpec,
    run_strategy,
)
from pydantic import ValidationError

BASE_TIME = datetime(2026, 6, 12, 9, 30, tzinfo=UTC)


def _bar(*, minutes: int, symbol: str = "BTC-USD") -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=BASE_TIME + timedelta(minutes=minutes),
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("95"),
        close=Decimal("105"),
        volume=Decimal("1"),
        source="unit-test",
        data_version="fixture-v1",
    )


def _spec(symbols: list[str] | None = None) -> StrategySpec:
    return StrategySpec.model_validate(
        {
            "strategy_id": "strategy_1",
            "name": "Test Strategy",
            "version": "1.0.0",
            "universe": {"symbols": symbols or ["BTC-USD"]},
            "timeframe": "1m",
            "entry": {"condition": "close > close_sma_3"},
            "exit": {"condition": "close < close_sma_3"},
            "risk": {"max_position_pct": Decimal("0.2")},
            "costs": {"fee_bps": Decimal("1"), "slippage_bps": Decimal("2")},
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


def _strategy_input(
    *,
    bars: list[Bar] | None = None,
    spec: StrategySpec | None = None,
    features: list[FeatureRow] | None = None,
) -> StrategyInput:
    resolved_bars = bars if bars is not None else [_bar(minutes=0), _bar(minutes=1)]
    resolved_features = (
        features if features is not None else generate_basic_features(resolved_bars)
    )
    return StrategyInput(
        spec=spec or _spec(),
        bars=resolved_bars,
        features=resolved_features,
    )


def _signal(
    *,
    strategy_id: str = "strategy_1",
    symbol: str = "BTC-USD",
    timestamp: datetime = BASE_TIME,
) -> Signal:
    return Signal(
        signal_id="signal_1",
        strategy_id=strategy_id,
        symbol=symbol,
        timestamp=timestamp,
        direction="long",
        confidence=0.8,
        horizon="1m",
        rationale="fake strategy signal",
    )


class FakeStrategy:
    def __init__(self, output: StrategyOutput | None = None) -> None:
        self.output = output or StrategyOutput(signals=[_signal()])

    def generate(self, strategy_input: StrategyInput) -> StrategyOutput:
        return self.output


class ExplodingStrategy:
    def generate(self, strategy_input: StrategyInput) -> StrategyOutput:
        raise RuntimeError("boom")


def test_run_strategy_returns_valid_signal_output() -> None:
    strategy_input = _strategy_input()

    output = run_strategy(FakeStrategy(), strategy_input)

    assert output.signals == [_signal()]


def test_strategy_input_rejects_empty_bars() -> None:
    with pytest.raises(ValidationError):
        StrategyInput(spec=_spec(), bars=[], features=[])


def test_run_strategy_rejects_feature_length_mismatch() -> None:
    strategy_input = _strategy_input(features=[])

    with pytest.raises(StrategyExecutionError, match="features length"):
        run_strategy(FakeStrategy(), strategy_input)


def test_run_strategy_rejects_failed_bar_quality() -> None:
    bars = [_bar(minutes=1), _bar(minutes=0)]
    features = [
        FeatureRow(
            symbol=bar.symbol,
            timestamp=bar.timestamp,
            source=bar.source,
            data_version=bar.data_version,
            values={},
        )
        for bar in bars
    ]
    strategy_input = _strategy_input(bars=bars, features=features)

    with pytest.raises(StrategyExecutionError, match="non_increasing_timestamp"):
        run_strategy(FakeStrategy(), strategy_input)


def test_run_strategy_rejects_signal_strategy_id_mismatch() -> None:
    output = StrategyOutput(signals=[_signal(strategy_id="other_strategy")])

    with pytest.raises(StrategyExecutionError, match="strategy_id"):
        run_strategy(FakeStrategy(output), _strategy_input())


def test_run_strategy_rejects_signal_symbol_outside_universe() -> None:
    output = StrategyOutput(signals=[_signal(symbol="ETH-USD")])

    with pytest.raises(StrategyExecutionError, match="universe"):
        run_strategy(FakeStrategy(output), _strategy_input())


def test_run_strategy_rejects_signal_timestamp_outside_input_bars() -> None:
    output = StrategyOutput(signals=[_signal(timestamp=BASE_TIME + timedelta(days=1))])

    with pytest.raises(StrategyExecutionError, match="timestamp"):
        run_strategy(FakeStrategy(output), _strategy_input())


def test_run_strategy_wraps_strategy_exceptions() -> None:
    with pytest.raises(StrategyExecutionError, match="boom"):
        run_strategy(ExplodingStrategy(), _strategy_input())


def test_strategy_output_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StrategyOutput.model_validate({"signals": [], "unexpected": True})


def test_run_strategy_wraps_invalid_output_shape() -> None:
    class InvalidOutputStrategy:
        def generate(self, strategy_input: StrategyInput) -> Any:
            return {"signals": [_signal()], "unexpected": True}

    with pytest.raises(StrategyExecutionError, match="strategy output"):
        run_strategy(InvalidOutputStrategy(), _strategy_input())
