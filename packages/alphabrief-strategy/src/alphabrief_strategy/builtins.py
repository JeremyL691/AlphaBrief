"""Built-in strategy implementations for AlphaBrief MVP workflows."""

import random
from dataclasses import dataclass
from typing import Protocol

from alphabrief_core import Signal, SignalDirection

from alphabrief_strategy.interface import StrategyInput, StrategyOutput


@dataclass(frozen=True)
class MovingAverageTrendStrategy:
    """Simple long/flat strategy driven by a trailing close SMA feature."""

    sma_window: int = 3
    confidence: float = 1.0
    horizon: str = "1bar"

    def generate(self, strategy_input: StrategyInput) -> StrategyOutput:
        feature_key = f"close_sma_{self.sma_window}"
        signals: list[Signal] = []

        for bar, feature_row in zip(
            strategy_input.bars, strategy_input.features, strict=True
        ):
            sma_value = feature_row.values.get(feature_key)
            direction: SignalDirection = "flat"
            rationale = f"{feature_key} unavailable"

            if sma_value is not None:
                if bar.close > sma_value:
                    direction = "long"
                    rationale = f"close is above {feature_key}"
                else:
                    direction = "flat"
                    rationale = f"close is not above {feature_key}"

            signals.append(
                Signal(
                    signal_id=(
                        f"{strategy_input.spec.strategy_id}:"
                        f"{bar.timestamp.isoformat()}"
                    ),
                    strategy_id=strategy_input.spec.strategy_id,
                    symbol=bar.symbol,
                    timestamp=bar.timestamp,
                    direction=direction,
                    confidence=self.confidence,
                    horizon=self.horizon,
                    rationale=rationale,
                )
            )

        return StrategyOutput(signals=signals)


@dataclass(frozen=True)
class MomentumStrategy:
    """Long when trailing window-bar return is positive, flat otherwise."""

    window: int = 20
    confidence: float = 1.0
    horizon: str = "24h"

    def generate(self, strategy_input: StrategyInput) -> StrategyOutput:
        signals: list[Signal] = []
        closes = [bar.close for bar in strategy_input.bars]
        for i, bar in enumerate(strategy_input.bars):
            if i < self.window:
                direction: SignalDirection = "flat"
                rationale = (
                    f"insufficient bars for momentum "
                    f"({i + 1} < {self.window + 1})"
                )
            else:
                prev_close = closes[i - self.window]
                if bar.close > prev_close:
                    direction = "long"
                    rationale = f"positive {self.window}-bar momentum"
                else:
                    direction = "flat"
                    rationale = f"non-positive {self.window}-bar momentum"

            signals.append(
                Signal(
                    signal_id=(
                        f"{strategy_input.spec.strategy_id}:"
                        f"{bar.timestamp.isoformat()}"
                    ),
                    strategy_id=strategy_input.spec.strategy_id,
                    symbol=bar.symbol,
                    timestamp=bar.timestamp,
                    direction=direction,
                    confidence=self.confidence,
                    horizon=self.horizon,
                    rationale=rationale,
                )
            )

        return StrategyOutput(signals=signals)


@dataclass(frozen=True)
class RandomStrategy:
    """Deterministic seeded random baseline strategy."""

    seed: int = 42
    confidence: float = 0.5
    horizon: str = "24h"

    def generate(self, strategy_input: StrategyInput) -> StrategyOutput:
        rng = random.Random(self.seed)
        signals: list[Signal] = []
        for bar in strategy_input.bars:
            direction: SignalDirection = rng.choice(["long", "flat"])
            signals.append(
                Signal(
                    signal_id=(
                        f"{strategy_input.spec.strategy_id}:"
                        f"{bar.timestamp.isoformat()}"
                    ),
                    strategy_id=strategy_input.spec.strategy_id,
                    symbol=bar.symbol,
                    timestamp=bar.timestamp,
                    direction=direction,
                    confidence=self.confidence,
                    horizon=self.horizon,
                    rationale="random baseline choice",
                )
            )

        return StrategyOutput(signals=signals)


class _RunnerLike(Protocol):
    def generate(self, strategy_input: StrategyInput) -> StrategyOutput: ...


def resolve_builtin_runner(strategy_id: str) -> _RunnerLike | None:
    """Map a registered strategy id to its deterministic builtin runner.

    v1 ships three builtin runners. ``momentum`` ids run
    :class:`MomentumStrategy`, ``random`` ids run :class:`RandomStrategy`,
    and every other registered id (including ``ma_trend``) runs the
    MovingAverageTrend runner under its own strategy id. Unknown empty ids
    return ``None`` so callers can skip optional evidence instead of
    guessing a runner.
    """
    normalized = (strategy_id or "").strip().lower()
    if not normalized:
        return None
    if "momentum" in normalized:
        return MomentumStrategy()
    if "random" in normalized:
        return RandomStrategy()
    return MovingAverageTrendStrategy()
