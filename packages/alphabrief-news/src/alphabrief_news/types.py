"""Schema definitions for the AlphaBrief news & macro data layer.

These models are pure Pydantic validation boundaries. They do not call
providers, read environment variables, store secrets, or produce trading
signals.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

NewsCategory = Literal[
    "earnings",
    "macro",
    "product",
    "regulation",
    "geopolitics",
    "other",
]

SentimentLabel = Literal["positive", "negative", "neutral"]


class AlphaBriefNewsModel(BaseModel):
    """Shared strict schema configuration for news & macro models."""

    model_config = ConfigDict(extra="forbid")


class NewsFetchQuery(AlphaBriefNewsModel):
    """Parameters for fetching a set of news headlines."""

    symbols: list[str] = Field(min_length=1)
    start: datetime
    end: datetime
    limit: int = Field(default=100, ge=1, le=1000)
    data_version: str = Field(default="news-v1", min_length=1)

    @field_validator("symbols")
    @classmethod
    def _symbols_non_empty(cls, value: list[str]) -> list[str]:
        if any(symbol.strip() == "" for symbol in value):
            raise ValueError("symbols must not contain blank entries")
        return value

    @field_validator("end")
    @classmethod
    def _end_after_start(cls, value: datetime, info: ValidationInfo) -> datetime:
        start = info.data.get("start")
        if start is not None and value <= start:
            raise ValueError("end must be after start")
        return value


class NewsHeadline(AlphaBriefNewsModel):
    """A single news headline relevant to one or more symbols."""

    headline_id: str = Field(min_length=1)
    published_at: datetime
    symbols: list[str] = Field(min_length=1)
    category: NewsCategory
    source: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(default="")
    url: str | None = Field(default=None)
    sentiment: SentimentLabel | None = Field(default=None)
    data_version: str = Field(default="news-v1", min_length=1)

    @field_validator("headline_id", "source", "title")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("string fields must not be blank")
        return value

    @field_validator("symbols")
    @classmethod
    def _symbols_non_empty(cls, value: list[str]) -> list[str]:
        if any(symbol.strip() == "" for symbol in value):
            raise ValueError("symbols must not contain blank entries")
        return value

    @field_validator("published_at")
    @classmethod
    def _published_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("published_at must be timezone-aware")
        return value


class MacroFetchQuery(AlphaBriefNewsModel):
    """Parameters for fetching macro-economic indicators."""

    indicators: list[str] = Field(min_length=1)
    start: datetime
    end: datetime
    data_version: str = Field(default="macro-v1", min_length=1)

    @field_validator("indicators")
    @classmethod
    def _indicators_non_empty(cls, value: list[str]) -> list[str]:
        if any(indicator.strip() == "" for indicator in value):
            raise ValueError("indicators must not contain blank entries")
        return value

    @field_validator("end")
    @classmethod
    def _end_after_start(cls, value: datetime, info: ValidationInfo) -> datetime:
        start = info.data.get("start")
        if start is not None and value <= start:
            raise ValueError("end must be after start")
        return value


class MacroIndicator(AlphaBriefNewsModel):
    """A single macro-economic indicator observation."""

    indicator_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    country: str = Field(default="US", min_length=1)
    released_at: datetime
    period: str | None = Field(default=None)
    value: Decimal
    unit: str | None = Field(default=None)
    source: str = Field(default="", min_length=1)
    data_version: str = Field(default="macro-v1", min_length=1)

    @field_validator("indicator_id", "name", "source")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("string fields must not be blank")
        return value

    @field_validator("released_at")
    @classmethod
    def _released_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("released_at must be timezone-aware")
        return value


__all__ = [
    "MacroFetchQuery",
    "MacroIndicator",
    "NewsCategory",
    "NewsFetchQuery",
    "NewsHeadline",
    "SentimentLabel",
]
