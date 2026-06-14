"""Schemas for the AlphaBrief Review Center."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ReviewPeriod = Literal["daily", "weekly"]


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("decimal fields must not be provided as float values")
    return value


def _validate_timezone_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime fields must be timezone-aware")
    return value


def _validate_non_blank_items(field_name: str, values: list[str]) -> list[str]:
    if any(value.strip() == "" for value in values):
        raise ValueError(f"{field_name} must not contain blank entries")
    return values


class ReviewSchema(BaseModel):
    """Shared strict schema configuration for review objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class StrategyListItem(ReviewSchema):
    strategy_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: str = Field(min_length=1)

    @field_validator("strategy_id", "name", "version", "status")
    @classmethod
    def _strings_must_not_be_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("string fields must not be blank")
        return value


class BacktestReportSummary(ReviewSchema):
    report_id: str = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    generated_at: datetime
    total_return: Decimal
    max_drawdown: Decimal
    trade_count: int = Field(ge=0)
    summary: str = Field(min_length=1)

    @field_validator("generated_at")
    @classmethod
    def _generated_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)

    @field_validator("total_return", "max_drawdown", mode="before")
    @classmethod
    def _decimal_fields_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)

    @field_validator("report_id", "strategy_id", "symbol", "summary")
    @classmethod
    def _strings_must_not_be_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("string fields must not be blank")
        return value


class DailyBriefSummary(ReviewSchema):
    brief_id: str = Field(min_length=1)
    trading_day: date
    generated_at: datetime
    headline: str = Field(min_length=1)
    executive_summary: str = Field(min_length=1)
    watchlist: list[str]
    risk_notes: list[str]

    @field_validator("generated_at")
    @classmethod
    def _generated_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)

    @field_validator("brief_id", "headline", "executive_summary")
    @classmethod
    def _strings_must_not_be_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("string fields must not be blank")
        return value

    @field_validator("watchlist", "risk_notes")
    @classmethod
    def _lists_must_not_contain_blank(cls, value: list[str]) -> list[str]:
        return _validate_non_blank_items("watchlist and risk_notes", value)


class ModelCallSummary(ReviewSchema):
    call_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    task_type: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    status: str = Field(min_length=1)
    created_at: datetime
    latency_ms: int = Field(ge=0)
    error_type: str | None = None

    @field_validator("created_at")
    @classmethod
    def _created_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)

    @field_validator(
        "call_id",
        "provider",
        "model",
        "task_type",
        "prompt_version",
        "status",
    )
    @classmethod
    def _strings_must_not_be_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("string fields must not be blank")
        return value


class PaperPortfolioSummary(ReviewSchema):
    cash: Decimal
    total_value: Decimal
    realized_pnl: Decimal
    open_positions: dict[str, Decimal]
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def _updated_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)

    @field_validator("cash", "total_value", "realized_pnl", mode="before")
    @classmethod
    def _decimal_fields_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)

    @field_validator("open_positions", mode="before")
    @classmethod
    def _positions_must_not_use_float(cls, value: Any) -> Any:
        if isinstance(value, dict) and any(
            isinstance(position, float) for position in value.values()
        ):
            raise ValueError("decimal fields must not be provided as float values")
        return value


class OrderAuditSummary(ReviewSchema):
    event_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    intent_id: str | None = None
    risk_decision_id: str | None = None
    order_id: str | None = None
    message: str = Field(min_length=1)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)

    @field_validator("event_id", "event_type", "message")
    @classmethod
    def _strings_must_not_be_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("string fields must not be blank")
        return value


class RiskDashboardSummary(ReviewSchema):
    total_decisions: int = Field(ge=0)
    approved_decisions: int = Field(ge=0)
    rejected_decisions: int = Field(ge=0)
    kill_switch_active: bool
    latest_risk_tags: list[str]
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def _updated_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)

    @field_validator("latest_risk_tags")
    @classmethod
    def _tags_must_not_contain_blank(cls, value: list[str]) -> list[str]:
        return _validate_non_blank_items("latest_risk_tags", value)


class ReviewJournalEntry(ReviewSchema):
    entry_id: str = Field(min_length=1)
    period: ReviewPeriod
    period_start: date
    period_end: date
    generated_at: datetime
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    highlights: list[str]
    action_items: list[str]

    @field_validator("generated_at")
    @classmethod
    def _generated_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)

    @field_validator("entry_id", "title", "summary")
    @classmethod
    def _strings_must_not_be_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("string fields must not be blank")
        return value

    @field_validator("highlights", "action_items")
    @classmethod
    def _lists_must_not_contain_blank(cls, value: list[str]) -> list[str]:
        return _validate_non_blank_items("highlights and action_items", value)


class ReviewCenterSnapshot(ReviewSchema):
    snapshot_id: str = Field(min_length=1)
    generated_at: datetime
    strategies: list[StrategyListItem]
    backtests: list[BacktestReportSummary]
    daily_briefs: list[DailyBriefSummary]
    model_calls: list[ModelCallSummary]
    paper_portfolio: PaperPortfolioSummary
    order_audit_log: list[OrderAuditSummary]
    risk_dashboard: RiskDashboardSummary
    review_journal: list[ReviewJournalEntry]

    @field_validator("snapshot_id")
    @classmethod
    def _snapshot_id_must_not_be_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("snapshot_id must not be blank")
        return value

    @field_validator("generated_at")
    @classmethod
    def _generated_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return _validate_timezone_aware(value)
