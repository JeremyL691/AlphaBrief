"""Strategy specification schemas for AlphaBrief."""

from alphabrief_strategy.builtins import MovingAverageTrendStrategy
from alphabrief_strategy.interface import (
    StrategyExecutionError,
    StrategyInput,
    StrategyOutput,
    StrategyProtocol,
    run_strategy,
)
from alphabrief_strategy.spec import (
    EvaluationPeriod,
    StrategyCosts,
    StrategyEvaluation,
    StrategyRisk,
    StrategyRule,
    StrategySpec,
    StrategyUniverse,
)

__all__ = [
    "EvaluationPeriod",
    "MovingAverageTrendStrategy",
    "StrategyExecutionError",
    "StrategyInput",
    "StrategyOutput",
    "StrategyProtocol",
    "StrategyCosts",
    "StrategyEvaluation",
    "StrategyRisk",
    "StrategyRule",
    "StrategySpec",
    "StrategyUniverse",
    "run_strategy",
]
