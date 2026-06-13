"""StrategySpec schemas for AlphaBrief.

These schemas describe strategy intent and evaluation boundaries only. They do
not parse conditions, generate signals, run backtests, or place orders.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _reject_float_decimal(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("decimal fields must not be provided as float values")
    return value


class AlphaBriefStrategyModel(BaseModel):
    """Shared model configuration for strict strategy schemas."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class StrategyUniverse(AlphaBriefStrategyModel):
    symbols: list[str] = Field(min_length=1)

    @field_validator("symbols")
    @classmethod
    def symbols_must_be_non_empty_and_stable_unique(
        cls,
        value: list[str],
    ) -> list[str]:
        unique_symbols: list[str] = []
        seen: set[str] = set()

        for symbol in value:
            normalized = symbol.strip()
            if normalized == "":
                raise ValueError("universe symbols must not contain empty strings")
            if normalized not in seen:
                unique_symbols.append(normalized)
                seen.add(normalized)

        if not unique_symbols:
            raise ValueError("universe must contain at least one symbol")
        return unique_symbols


class StrategyRule(AlphaBriefStrategyModel):
    condition: str = Field(min_length=1)

    @field_validator("condition")
    @classmethod
    def condition_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "":
            raise ValueError("strategy rule condition must not be blank")
        return normalized


class StrategyRisk(AlphaBriefStrategyModel):
    max_position_pct: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    stop_loss: str | None = None

    @field_validator("max_position_pct", mode="before")
    @classmethod
    def max_position_pct_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float_decimal(value)

    @field_validator("stop_loss")
    @classmethod
    def stop_loss_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if normalized == "":
            raise ValueError("stop_loss must not be blank when provided")
        return normalized


class StrategyCosts(AlphaBriefStrategyModel):
    fee_bps: Decimal = Field(ge=Decimal("0"))
    slippage_bps: Decimal = Field(ge=Decimal("0"))

    @field_validator("fee_bps", "slippage_bps", mode="before")
    @classmethod
    def decimal_fields_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float_decimal(value)


class EvaluationPeriod(AlphaBriefStrategyModel):
    start: date
    end: date

    @model_validator(mode="after")
    def start_must_not_be_after_end(self) -> "EvaluationPeriod":
        if self.start > self.end:
            raise ValueError("evaluation period start must be on or before end")
        return self


class StrategyEvaluation(AlphaBriefStrategyModel):
    train_period: EvaluationPeriod
    test_period: EvaluationPeriod

    @model_validator(mode="after")
    def test_period_must_follow_train_period(self) -> "StrategyEvaluation":
        if self.test_period.start <= self.train_period.end:
            raise ValueError("test period must start after train period ends")
        return self


class StrategySpec(AlphaBriefStrategyModel):
    strategy_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    universe: StrategyUniverse
    timeframe: str = Field(min_length=1)
    entry: StrategyRule
    exit: StrategyRule
    risk: StrategyRisk
    costs: StrategyCosts
    evaluation: StrategyEvaluation

    @field_validator("strategy_id", "name", "version", "timeframe")
    @classmethod
    def key_strings_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "":
            raise ValueError("strategy spec strings must not be blank")
        return normalized
