"""M12-W02: category-aware deterministic strategy families.

Covers AC-M12-W02-01/03: every required family (trend, mean reversion,
breakout, volatility regime, no-trade) emits deterministic long, short,
flat, and insufficient-data outcomes from declared inputs only;
no-trade is a first-class benchmark strategy; all outputs are advisory
:class:`Signal` evidence and never executable orders.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import get_args

import pytest
from alphabrief_core import Bar
from alphabrief_data import FeatureRow
from alphabrief_execution.broker.oanda.taxonomy import (
    InstrumentCategory as OandaInstrumentCategory,
)
from alphabrief_strategy import (
    FAMILY_APPLICABILITY,
    BreakoutFamily,
    MeanReversionFamily,
    NoTradeFamily,
    StrategyFamily,
    StrategyInput,
    StrategyInstrumentCategory,
    StrategyOutput,
    StrategySpec,
    TrendFamily,
    VolatilityRegimeFamily,
    run_strategy,
)

_FAMILIES: tuple[StrategyFamily, ...] = (
    TrendFamily(),
    MeanReversionFamily(),
    BreakoutFamily(),
    VolatilityRegimeFamily(),
    NoTradeFamily(),
)


def _spec() -> StrategySpec:
    return StrategySpec.model_validate(
        {
            "strategy_id": "family_test_v1",
            "name": "Family Test",
            "version": "1.0.0",
            "universe": {"symbols": ["SPY"]},
            "timeframe": "1d",
            "entry": {"condition": "close > close_sma_20"},
            "exit": {"condition": "close < close_sma_20"},
            "risk": {"max_position_pct": Decimal("0.2")},
            "costs": {"fee_bps": Decimal("5"), "slippage_bps": Decimal("10")},
            "evaluation": {
                "train_period": {"start": "2024-01-01", "end": "2024-12-31"},
                "test_period": {"start": "2025-01-01", "end": "2025-12-31"},
            },
        }
    )


def _bars(closes: Sequence[str]) -> list[Bar]:
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
                data_version="fixture-v1",
            )
        )
    return bars


def _strategy_input(
    closes: Sequence[str],
    feature_values: Sequence[Mapping[str, Decimal | None]],
) -> StrategyInput:
    bars = _bars(closes)
    features = [
        FeatureRow(
            symbol=bar.symbol,
            timestamp=bar.timestamp,
            source=bar.source,
            data_version=bar.data_version,
            values=dict(values),
        )
        for bar, values in zip(bars, feature_values, strict=True)
    ]
    return StrategyInput(spec=_spec(), bars=bars, features=features)


def _outcomes(strategy: StrategyFamily) -> tuple[StrategyOutput, StrategyOutput]:
    """Generate twice on identical input; returns (first, second)."""
    strategy_input = _strategy_input(
        ["100", "101"],
        [
            {"close_sma_20": Decimal("100"), "rsi_14": Decimal("25")},
            {"close_sma_20": Decimal("101"), "rsi_14": Decimal("25")},
        ],
    )
    return strategy.generate(strategy_input), strategy.generate(strategy_input)


class TestTrendFamily:
    def test_long_short_flat_and_insufficient_data(self) -> None:
        strategy = TrendFamily(sma_window=3)
        output = strategy.generate(
            _strategy_input(
                ["100", "101", "100", "99"],
                [
                    {"close_sma_3": Decimal("99")},
                    {"close_sma_3": Decimal("102")},
                    {"close_sma_3": Decimal("100")},
                    {"close_sma_3": None},
                ],
            )
        )
        assert [s.direction for s in output.signals] == [
            "long",
            "short",
            "flat",
            "flat",
        ]
        assert output.signals[0].rationale == "close is above close_sma_3"
        assert output.signals[2].rationale == "close equals close_sma_3"
        assert output.signals[3].rationale == (
            "insufficient data: close_sma_3 unavailable"
        )

    def test_declared_requirements(self) -> None:
        strategy = TrendFamily(sma_window=5)
        assert strategy.required_features() == frozenset({"close_sma_5"})
        assert strategy.family_id == "trend"
        assert "OTHER_CFD" not in strategy.applicable_categories

    def test_identical_inputs_produce_identical_signals(self) -> None:
        first, second = _outcomes(TrendFamily())
        assert first == second


class TestMeanReversionFamily:
    def test_oversold_overbought_inside_and_insufficient_data(self) -> None:
        strategy = MeanReversionFamily(rsi_period=14)
        output = strategy.generate(
            _strategy_input(
                ["100", "101", "102", "103"],
                [
                    {"rsi_14": Decimal("20")},
                    {"rsi_14": Decimal("80")},
                    {"rsi_14": Decimal("50")},
                    {"rsi_14": None},
                ],
            )
        )
        assert [s.direction for s in output.signals] == [
            "long",
            "short",
            "flat",
            "flat",
        ]
        assert output.signals[0].rationale == (
            "rsi_14 20 is oversold (<= 30)"
        )
        assert output.signals[2].rationale == (
            "rsi_14 50 is inside the mean-reversion band"
        )
        assert output.signals[3].rationale == (
            "insufficient data: rsi_14 unavailable"
        )

    def test_declared_requirements(self) -> None:
        strategy = MeanReversionFamily(rsi_period=9)
        assert strategy.required_features() == frozenset({"rsi_9"})
        assert strategy.family_id == "mean_reversion"

    def test_identical_inputs_produce_identical_signals(self) -> None:
        first, second = _outcomes(MeanReversionFamily())
        assert first == second


class TestBreakoutFamily:
    def test_above_upper_below_lower_inside_and_insufficient_data(self) -> None:
        strategy = BreakoutFamily(bb_period=20)
        output = strategy.generate(
            _strategy_input(
                ["105", "95", "100", "100"],
                [
                    {
                        "bb_upper_20": Decimal("102"),
                        "bb_lower_20": Decimal("98"),
                    },
                    {
                        "bb_upper_20": Decimal("102"),
                        "bb_lower_20": Decimal("98"),
                    },
                    {
                        "bb_upper_20": Decimal("102"),
                        "bb_lower_20": Decimal("98"),
                    },
                    {
                        "bb_upper_20": Decimal("102"),
                        "bb_lower_20": None,
                    },
                ],
            )
        )
        assert [s.direction for s in output.signals] == [
            "long",
            "short",
            "flat",
            "flat",
        ]
        assert output.signals[0].rationale == "close is above bb_upper_20"
        assert output.signals[2].rationale == (
            "close is inside the breakout bands"
        )
        assert "insufficient data" in output.signals[3].rationale

    def test_declared_requirements(self) -> None:
        strategy = BreakoutFamily(bb_period=10)
        assert strategy.required_features() == frozenset(
            {"bb_upper_10", "bb_lower_10"}
        )
        assert strategy.family_id == "breakout"

    def test_identical_inputs_produce_identical_signals(self) -> None:
        first, second = _outcomes(BreakoutFamily())
        assert first == second


class TestVolatilityRegimeFamily:
    def test_high_volatility_flat_normal_long_short_and_insufficient(self) -> None:
        strategy = VolatilityRegimeFamily(
            sma_window=20, atr_period=14, high_vol_atr_pct=Decimal("0.02")
        )
        output = strategy.generate(
            _strategy_input(
                ["100", "101", "99", "100"],
                [
                    {"close_sma_20": Decimal("99"), "atr_14": Decimal("3.0")},
                    {"close_sma_20": Decimal("99"), "atr_14": Decimal("1.0")},
                    {"close_sma_20": Decimal("100"), "atr_14": Decimal("1.0")},
                    {"close_sma_20": None, "atr_14": Decimal("1.0")},
                ],
            )
        )
        assert [s.direction for s in output.signals] == [
            "flat",
            "long",
            "short",
            "flat",
        ]
        assert "high volatility regime" in output.signals[0].rationale
        assert output.signals[1].rationale == (
            "normal regime, close is above close_sma_20"
        )
        assert output.signals[2].rationale == (
            "normal regime, close is below close_sma_20"
        )
        assert "insufficient data" in output.signals[3].rationale

    def test_declared_requirements(self) -> None:
        strategy = VolatilityRegimeFamily(sma_window=5, atr_period=7)
        assert strategy.required_features() == frozenset(
            {"close_sma_5", "atr_7"}
        )
        assert strategy.family_id == "volatility_regime"

    def test_identical_inputs_produce_identical_signals(self) -> None:
        first, second = _outcomes(VolatilityRegimeFamily())
        assert first == second


class TestNoTradeFamily:
    def test_always_flat_even_with_direction_like_features(self) -> None:
        strategy = NoTradeFamily()
        output = strategy.generate(
            _strategy_input(
                ["100", "200"],
                [
                    {"close_sma_20": Decimal("50"), "rsi_14": Decimal("10")},
                    {"close_sma_20": Decimal("250"), "rsi_14": Decimal("90")},
                ],
            )
        )
        assert [s.direction for s in output.signals] == ["flat", "flat"]
        assert all(
            s.rationale == "no-trade benchmark: no position"
            for s in output.signals
        )

    def test_never_reads_declared_inputs(self) -> None:
        strategy = NoTradeFamily()
        assert strategy.required_features() == frozenset()
        assert strategy.family_id == "no_trade"
        assert strategy.applicable_categories == frozenset(
            get_args(StrategyInstrumentCategory)
        )

    def test_first_class_benchmark_metadata(self) -> None:
        strategy = NoTradeFamily()
        assert strategy.confidence == 1.0
        assert strategy.family_id in FAMILY_APPLICABILITY


class TestFamilyContract:
    @pytest.mark.parametrize("strategy", _FAMILIES)
    def test_every_family_passes_the_validated_runner(
        self, strategy: StrategyFamily
    ) -> None:
        strategy_input = _strategy_input(
            ["100", "101"],
            [
                {"close_sma_20": Decimal("100")},
                {"close_sma_20": Decimal("101")},
            ],
        )
        output = run_strategy(strategy, strategy_input)
        assert isinstance(output, StrategyOutput)

    @pytest.mark.parametrize("strategy", _FAMILIES)
    def test_outputs_are_advisory_signal_evidence_only(
        self, strategy: StrategyFamily
    ) -> None:
        strategy_input = _strategy_input(
            ["100", "101"],
            [
                {"close_sma_20": Decimal("100")},
                {"close_sma_20": Decimal("101")},
            ],
        )
        output = strategy.generate(strategy_input)
        assert isinstance(output, StrategyOutput)
        for signal in output.signals:
            assert signal.direction in ("long", "short", "flat")
            assert signal.strategy_id == strategy_input.spec.strategy_id
            assert signal.symbol in strategy_input.spec.universe.symbols
            assert signal.timestamp in {
                bar.timestamp for bar in strategy_input.bars
            }
            assert signal.rationale

    @pytest.mark.parametrize("strategy", _FAMILIES)
    def test_every_family_declares_its_family_id(
        self, strategy: StrategyFamily
    ) -> None:
        assert strategy.family_id in FAMILY_APPLICABILITY
        assert FAMILY_APPLICABILITY[strategy.family_id] == (
            strategy.applicable_categories
        )

    def test_category_mirror_matches_oanda_taxonomy(self) -> None:
        assert set(get_args(StrategyInstrumentCategory)) == set(
            get_args(OandaInstrumentCategory)
        )

    def test_families_never_return_orders(self) -> None:
        # The output boundary is StrategyOutput(Signal evidence). No
        # family exposes any order-like attribute.
        assert "orders" not in StrategyOutput.model_fields
        for strategy in _FAMILIES:
            assert "submit" not in dir(strategy)
