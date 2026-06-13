"""Research brief schemas for AlphaBrief.

These schemas are pure Pydantic validation boundaries. They do not call
providers, do not read environment variables, do not store secret values, and
do not produce any side effects. They are designed to be the target model for
``parse_structured_output`` and future research layer generators.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MarketRegime = Literal["bullish", "bearish", "neutral", "uncertain"]
SymbolDirection = Literal["bullish", "bearish", "neutral"]
BriefHorizon = Literal["intraday", "1d", "1w", "1m"]


class AlphaBriefModel(BaseModel):
    """Shared strict schema configuration for research brief models."""

    model_config = ConfigDict(extra="forbid")


class MarketBrief(AlphaBriefModel):
    """A market-level research brief for a single trading day."""

    brief_id: str = Field(min_length=1)
    generated_at: datetime
    trading_day: date
    regime: MarketRegime
    summary: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    key_factors: list[str]

    @field_validator("brief_id", "summary")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("string fields must not be blank")
        return value

    @field_validator("generated_at")
    @classmethod
    def _generated_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        return value

    @field_validator("key_factors")
    @classmethod
    def _key_factors_must_not_contain_blank(cls, value: list[str]) -> list[str]:
        if any(factor.strip() == "" for factor in value):
            raise ValueError("key_factors must not contain blank entries")
        return value


class SymbolVerdict(AlphaBriefModel):
    """A per-symbol verdict nested inside a SymbolBrief."""

    direction: SymbolDirection
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1)

    @field_validator("rationale")
    @classmethod
    def _rationale_must_not_be_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("rationale must not be blank")
        return value


class SymbolBrief(AlphaBriefModel):
    """A symbol-level research brief for a defined horizon."""

    brief_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    generated_at: datetime
    horizon: BriefHorizon
    verdict: SymbolVerdict
    catalysts: list[str]
    risks: list[str]

    @field_validator("brief_id", "symbol")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("string fields must not be blank")
        return value

    @field_validator("generated_at")
    @classmethod
    def _generated_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        return value

    @field_validator("catalysts", "risks")
    @classmethod
    def _factors_must_not_contain_blank(cls, value: list[str]) -> list[str]:
        if any(item.strip() == "" for item in value):
            raise ValueError("catalysts and risks must not contain blank entries")
        return value
