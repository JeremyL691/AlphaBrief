"""AlphaBrief core domain models.

These models define data boundaries only. They do not implement risk checks,
order routing, broker behavior, model calls, or trading decisions.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SignalDirection = Literal["long", "short", "flat"]
OrderIntentSource = Literal["strategy", "model", "manual"]
OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "limit"]


def _reject_float_decimal(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("decimal fields must not be provided as float values")
    return value


def _validate_timezone_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime fields must be timezone-aware")
    return value


class AlphaBriefModel(BaseModel):
    """Shared model configuration for strict AlphaBrief boundary objects."""

    model_config = ConfigDict(extra="forbid")


class Bar(AlphaBriefModel):
    symbol: str = Field(min_length=1)
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    source: str = Field(min_length=1)
    data_version: str = Field(min_length=1)

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)

    @field_validator("open", "high", "low", "close", "volume", mode="before")
    @classmethod
    def decimal_fields_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float_decimal(value)

    @model_validator(mode="after")
    def validate_ohlcv(self) -> "Bar":
        prices = [self.open, self.high, self.low, self.close]
        if any(price < 0 for price in prices):
            raise ValueError("bar prices must be non-negative")
        if self.volume < 0:
            raise ValueError("bar volume must be non-negative")
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("bar high must be at least open, low, and close")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("bar low must be at most open, high, and close")
        return self


class SignalEvidence(AlphaBriefModel):
    """Optional external-evidence metadata attached to a :class:`Signal`.

    Fields are all optional and default-empty so existing signal
    construction stays backward compatible. The metadata is **audit
    context only** — it must not be used to bypass risk rules or
    order routing. Sentiment scores use the convention of
    ``[-1.0, 1.0]`` (negative to positive); ``None`` means unknown.
    """

    news_headline_ids: list[str] = Field(default_factory=list)
    macro_indicator_ids: list[str] = Field(default_factory=list)
    sentiment_score: float | None = Field(default=None, ge=-1.0, le=1.0)
    source: str | None = None
    data_version: str | None = None
    external_context_version: str | None = None
    generated_at: datetime | None = None

    @field_validator("generated_at")
    @classmethod
    def generated_at_must_be_timezone_aware(
        cls, value: datetime | None,
    ) -> datetime | None:
        if value is None:
            return None
        return _validate_timezone_aware(value)

    @field_validator("news_headline_ids", "macro_indicator_ids")
    @classmethod
    def ids_must_not_contain_blanks(cls, value: list[str]) -> list[str]:
        for item in value:
            if not isinstance(item, str) or item.strip() == "":
                raise ValueError("evidence ids must be non-empty strings")
        return value

    @field_validator("source", "data_version", "external_context_version")
    @classmethod
    def optional_string_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.strip() == "":
            raise ValueError("evidence string fields must not be blank when provided")
        return value


class Signal(AlphaBriefModel):
    signal_id: str = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    timestamp: datetime
    direction: SignalDirection
    confidence: float = Field(ge=0, le=1)
    horizon: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    evidence: SignalEvidence | None = None

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)


class OrderIntent(AlphaBriefModel):
    intent_id: str = Field(min_length=1)
    source: OrderIntentSource
    symbol: str = Field(min_length=1)
    side: OrderSide
    order_type: OrderType
    quantity: Decimal | None = None
    target_position_pct: Decimal | None = None
    limit_price: Decimal | None = None
    rationale: str = Field(min_length=1)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def created_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)

    @field_validator("quantity", "target_position_pct", "limit_price", mode="before")
    @classmethod
    def decimal_fields_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float_decimal(value)

    @model_validator(mode="after")
    def validate_order_intent(self) -> "OrderIntent":
        has_quantity = self.quantity is not None
        has_target_position = self.target_position_pct is not None

        if has_quantity == has_target_position:
            raise ValueError("provide exactly one of quantity or target_position_pct")
        if self.quantity is not None and self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.target_position_pct is not None and not (
            Decimal("0") <= self.target_position_pct <= Decimal("1")
        ):
            raise ValueError("target_position_pct must be between 0 and 1")
        if self.order_type == "limit":
            if self.limit_price is None or self.limit_price <= 0:
                raise ValueError("limit orders require a positive limit_price")
        if self.order_type == "market" and self.limit_price is not None:
            raise ValueError("market orders must not include limit_price")
        return self


class RiskDecision(AlphaBriefModel):
    decision_id: str = Field(min_length=1)
    intent_id: str = Field(min_length=1)
    approved: bool
    reason: str = Field(min_length=1)
    max_quantity: Decimal | None = None
    risk_tags: list[str]
    requires_human_review: bool
    source_module: str = ""
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def created_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)

    @field_validator("max_quantity", mode="before")
    @classmethod
    def decimal_fields_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float_decimal(value)

    @field_validator("risk_tags")
    @classmethod
    def risk_tags_must_not_be_empty(cls, value: list[str]) -> list[str]:
        if any(tag == "" for tag in value):
            raise ValueError("risk_tags must not contain empty strings")
        return value

    @model_validator(mode="after")
    def validate_risk_decision(self) -> "RiskDecision":
        if self.max_quantity is not None and self.max_quantity < 0:
            raise ValueError("max_quantity must be non-negative")
        return self


class Order(AlphaBriefModel):
    order_id: str = Field(min_length=1)
    intent_id: str = Field(min_length=1)
    risk_decision_id: str = Field(min_length=1)
    broker: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    status: str = Field(min_length=1)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def created_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)

    @field_validator("quantity", mode="before")
    @classmethod
    def decimal_fields_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float_decimal(value)

    @model_validator(mode="after")
    def validate_order(self) -> "Order":
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        return self
