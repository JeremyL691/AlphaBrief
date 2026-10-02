"""Credential-free broker observations for model and execution input checks."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BrokerInputFacts(BaseModel):
    """Missing observations remain None; errors contain classes, never messages."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    symbol: str = Field(min_length=1)
    bid: Decimal | None = None
    ask: Decimal | None = None
    spread: Decimal | None = None
    quote_to_home: Decimal | None = None
    quote_position_to_home: Decimal | None = None
    quote_captured_at: datetime | None = None
    nav: Decimal | None = None
    margin_available: Decimal | None = None
    margin_used: Decimal | None = None
    account_captured_at: datetime | None = None
    position_units: Decimal | None = None
    position_unrealized_pnl: Decimal | None = None
    positions_captured_at: datetime | None = None
    reconciliation_captured_at: datetime | None = None
    daily_open_count: int | None = Field(default=None, ge=0)
    errors: dict[str, str] = Field(default_factory=dict)

    @field_validator(
        "quote_captured_at",
        "account_captured_at",
        "positions_captured_at",
        "reconciliation_captured_at",
    )
    @classmethod
    def _time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("broker observation must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator(
        "bid",
        "ask",
        "spread",
        "quote_to_home",
        "quote_position_to_home",
        "nav",
        "margin_available",
        "margin_used",
        "position_units",
        "position_unrealized_pnl",
        mode="before",
    )
    @classmethod
    def _decimal(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("broker amounts must not use float")
        return value
