"""Built-in strategy implementations for AlphaBrief MVP workflows."""

from dataclasses import dataclass

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
