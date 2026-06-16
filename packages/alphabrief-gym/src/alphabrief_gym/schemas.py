"""Common schemas for the AlphaBrief trading environment (Phase 11+).

These Pydantic models describe the public observation / action / step
result / metrics / configuration surface used by the gymnasium-style
trading environment. They live in their own module so callers can
construct them without depending on the env implementation.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from alphabrief_core import Bar
from pydantic import BaseModel, ConfigDict, Field, field_validator

SingleAssetAction = Literal["hold", "buy", "sell"]
ContinuousAction = Literal["hold", "target_weight"]


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("decimal fields must not be provided as float values")
    return value


def _require_timezone_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


class AlphaBriefEnvModel(BaseModel):
    """Shared strict schema configuration for env objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class AssetObservation(AlphaBriefEnvModel):
    """Per-asset observation used in multi-asset environments."""

    symbol: str = Field(min_length=1)
    timestamp: datetime
    close: Decimal
    position_quantity: Decimal

    @field_validator("close", "position_quantity", mode="before")
    @classmethod
    def _decimal_fields_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)

    @field_validator("timestamp")
    @classmethod
    def _timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _require_timezone_aware(value)


class PortfolioSnapshot(AlphaBriefEnvModel):
    """Portfolio state at a single step."""

    cash: Decimal
    positions: dict[str, Decimal] = Field(default_factory=dict)
    portfolio_value: Decimal
    leverage: Decimal = Decimal("0")
    borrow_cost_accrued: Decimal = Decimal("0")

    @field_validator(
        "cash", "portfolio_value", "leverage", "borrow_cost_accrued", mode="before",
    )
    @classmethod
    def _decimal_fields_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class MultiAssetObservation(AlphaBriefEnvModel):
    """Multi-asset observation carrying per-asset and portfolio views."""

    step_index: int = Field(ge=0)
    timestamp: datetime
    assets: dict[str, AssetObservation]
    portfolio: PortfolioSnapshot

    @field_validator("timestamp")
    @classmethod
    def _timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _require_timezone_aware(value)


class ContinuousActionSpace(AlphaBriefEnvModel):
    """Continuous target-weight action space per asset.

    Each target weight is bounded by ``[-max_leverage, max_leverage]``;
    negative values represent a short position. The action is applied
    as a portfolio rebalance at the current bar's close.
    """

    assets: list[str] = Field(min_length=1)
    max_leverage: Decimal = Field(default=Decimal("1"))
    allow_short: bool = True

    @field_validator("assets")
    @classmethod
    def _assets_unique_non_blank(cls, value: list[str]) -> list[str]:
        if any(a.strip() == "" for a in value):
            raise ValueError("asset symbols must not be blank")
        if len(value) != len(set(value)):
            raise ValueError("asset symbols must be unique")
        return value

    @field_validator("max_leverage", mode="before")
    @classmethod
    def _max_leverage_positive(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("max_leverage must not be provided as float")
        if value is not None and Decimal(str(value)) <= 0:
            raise ValueError("max_leverage must be > 0")
        return value


class DiscreteActionSpace(AlphaBriefEnvModel):
    """Discrete action space (legacy single-asset)."""

    actions: tuple[SingleAssetAction, ...] = ("hold", "buy", "sell")


class EpisodeMetricsV2(AlphaBriefEnvModel):
    """Episode metrics for the multi-asset environment."""

    initial_value: Decimal
    final_value: Decimal
    total_return: Decimal
    max_drawdown: Decimal
    steps: int = Field(ge=0)
    trades: int = Field(ge=0)
    slippage_cost: Decimal = Decimal("0")
    market_impact_cost: Decimal = Decimal("0")
    borrow_cost: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")

    @field_validator(
        "initial_value", "final_value", "total_return", "max_drawdown",
        "slippage_cost", "market_impact_cost", "borrow_cost", "realized_pnl",
        mode="before",
    )
    @classmethod
    def _decimal_fields_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class EnvV2CostBreakdown(AlphaBriefEnvModel):
    """Cost breakdown for an EnvV2 episode report."""

    slippage_cost: Decimal = Decimal("0")
    market_impact_cost: Decimal = Decimal("0")
    borrow_cost: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")

    @field_validator(
        "slippage_cost", "market_impact_cost", "borrow_cost", "total_cost",
        mode="before",
    )
    @classmethod
    def _decimal_fields_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class EnvV2AssetMetrics(AlphaBriefEnvModel):
    """Per-asset metrics for an EnvV2 episode report."""

    symbol: str = Field(min_length=1)
    final_position: Decimal
    realized_pnl: Decimal
    trade_count: int = Field(ge=0)

    @field_validator("final_position", "realized_pnl", mode="before")
    @classmethod
    def _decimal_fields_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class EnvV2Report(AlphaBriefEnvModel):
    """Phase 12.6 episode report for the multi-asset environment."""

    report_id: str = Field(min_length=1)
    environment: str = Field(default="alphabrief_gym_v2", min_length=1)
    steps: int = Field(ge=0)
    initial_value: Decimal
    final_value: Decimal
    total_return: Decimal
    max_drawdown: Decimal
    trade_count: int = Field(ge=0)
    final_leverage: Decimal
    costs: EnvV2CostBreakdown
    assets: list[EnvV2AssetMetrics] = Field(default_factory=list)
    generated_at: datetime

    @field_validator(
        "initial_value", "final_value", "total_return", "max_drawdown",
        "final_leverage", mode="before",
    )
    @classmethod
    def _decimal_fields_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)

    @field_validator("generated_at")
    @classmethod
    def _timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _require_timezone_aware(value)


def bars_by_symbol(bars: list[Bar]) -> dict[str, list[Bar]]:
    """Group a flat bar list by symbol, preserving sort order."""
    grouped: dict[str, list[Bar]] = {}
    for bar in bars:
        grouped.setdefault(bar.symbol, []).append(bar)
    for symbol_bars in grouped.values():
        symbol_bars.sort(key=lambda bar: bar.timestamp)
    return grouped


__all__ = [
    "AlphaBriefEnvModel",
    "AssetObservation",
    "ContinuousAction",
    "ContinuousActionSpace",
    "DiscreteActionSpace",
    "EpisodeMetricsV2",
    "MultiAssetObservation",
    "PortfolioSnapshot",
    "SingleAssetAction",
    "bars_by_symbol",
]
