"""Strategy execution interface contracts for AlphaBrief."""

from typing import Protocol, runtime_checkable

from alphabrief_core import Bar, Signal
from alphabrief_data import FeatureRow, check_bar_quality
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from alphabrief_strategy.spec import StrategySpec


class StrategyExecutionError(RuntimeError):
    """Raised when a strategy cannot be run or returns invalid output."""


class StrategyInput(BaseModel):
    """Input passed to a strategy implementation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    spec: StrategySpec
    bars: list[Bar] = Field(min_length=1)
    features: list[FeatureRow]


class StrategyOutput(BaseModel):
    """Output returned by a strategy implementation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signals: list[Signal]


@runtime_checkable
class StrategyProtocol(Protocol):
    """Protocol implemented by AlphaBrief strategy classes."""

    def generate(self, strategy_input: StrategyInput) -> StrategyOutput:
        """Generate strategy output from validated input."""


def run_strategy(
    strategy: StrategyProtocol,
    strategy_input: StrategyInput,
) -> StrategyOutput:
    """Run a strategy and validate that it returns allowed signals only."""

    _validate_strategy_input(strategy_input)

    try:
        output = strategy.generate(strategy_input)
    except Exception as exc:
        raise StrategyExecutionError(f"strategy execution failed: {exc}") from exc

    try:
        validated_output = StrategyOutput.model_validate(output)
    except ValidationError as exc:
        raise StrategyExecutionError(f"strategy output is invalid: {exc}") from exc

    _validate_strategy_output(strategy_input, validated_output)
    return validated_output


def _validate_strategy_input(strategy_input: StrategyInput) -> None:
    if len(strategy_input.features) != len(strategy_input.bars):
        raise StrategyExecutionError("features length must match bars length")

    quality_report = check_bar_quality(strategy_input.bars)
    if not quality_report.passed:
        issue_codes = ", ".join(issue.code for issue in quality_report.issues)
        raise StrategyExecutionError(
            f"cannot run strategy with failed data quality report: {issue_codes}"
        )


def _validate_strategy_output(
    strategy_input: StrategyInput,
    output: StrategyOutput,
) -> None:
    allowed_symbols = set(strategy_input.spec.universe.symbols)
    bar_timestamps = {bar.timestamp for bar in strategy_input.bars}

    for signal in output.signals:
        if signal.strategy_id != strategy_input.spec.strategy_id:
            raise StrategyExecutionError(
                "signal strategy_id must match StrategySpec strategy_id"
            )
        if signal.symbol not in allowed_symbols:
            raise StrategyExecutionError(
                "signal symbol must be in StrategySpec universe"
            )
        if signal.timestamp not in bar_timestamps:
            raise StrategyExecutionError("signal timestamp must come from input bars")
