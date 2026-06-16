"""Deterministic, in-memory news and macro providers for tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from alphabrief_news.providers.base import NewsProviderError, NewsProviderErrorCode
from alphabrief_news.types import (
    MacroFetchQuery,
    MacroIndicator,
    NewsFetchQuery,
    NewsHeadline,
)


class MockNewsProvider:
    """Deterministic news provider that returns canned headlines.

    The provider does not perform network calls. It filters by query symbols
    and the requested time window, then returns up to ``query.limit`` rows.
    """

    def __init__(self, seed_headlines: list[NewsHeadline] | None = None) -> None:
        self._headlines: list[NewsHeadline] = seed_headlines or []

    def fetch_headlines(self, query: NewsFetchQuery) -> list[NewsHeadline]:
        """Return matching headlines from the in-memory seed list."""
        if not query.symbols:
            raise NewsProviderError(
                NewsProviderErrorCode.INVALID_SYMBOL,
                "at least one symbol is required",
            )

        symbol_set = set(query.symbols)
        results = [
            headline
            for headline in self._headlines
            if symbol_set.intersection(headline.symbols)
            and query.start <= headline.published_at < query.end
        ]
        return results[: query.limit]


class MockMacroProvider:
    """Deterministic macro provider that returns canned indicators."""

    def __init__(self, seed_indicators: list[MacroIndicator] | None = None) -> None:
        self._indicators: list[MacroIndicator] = seed_indicators or []

    def fetch_indicators(self, query: MacroFetchQuery) -> list[MacroIndicator]:
        """Return matching indicators from the in-memory seed list."""
        if not query.indicators:
            raise NewsProviderError(
                NewsProviderErrorCode.INVALID_CONFIG,
                "at least one indicator is required",
            )

        indicator_set = set(query.indicators)
        results = [
            indicator
            for indicator in self._indicators
            if indicator.indicator_id in indicator_set
            and query.start <= indicator.released_at < query.end
        ]
        return results


def build_default_mock_news(symbols: list[str]) -> list[NewsHeadline]:
    """Return a small deterministic headline set for smoke tests."""
    base = datetime(2024, 6, 1, 9, 30, tzinfo=UTC)
    return [
        NewsHeadline(
            headline_id=f"news-{symbol}-001",
            published_at=base.replace(hour=9 + idx),
            symbols=[symbol],
            category="earnings",
            source="mock-news",
            title=f"{symbol} earnings preview",
            summary=f"Analysts preview {symbol} earnings.",
            url=f"https://example.com/{symbol.lower()}-001",
            sentiment="neutral",
            data_version="news-v1",
        )
        for idx, symbol in enumerate(symbols)
    ]


def build_default_mock_macro(indicators: list[str]) -> list[MacroIndicator]:
    """Return a small deterministic indicator set for smoke tests."""
    base = datetime(2024, 6, 1, 8, 30, tzinfo=UTC)
    values: dict[str, Decimal] = {
        "CPIAUCSL": Decimal("307.123"),
        "UNRATE": Decimal("3.7"),
        "GDP": Decimal("28782.5"),
    }
    return [
        MacroIndicator(
            indicator_id=indicator_id,
            name=indicator_id,
            country="US",
            released_at=base.replace(day=1 + idx),
            period="2024-05",
            value=values.get(indicator_id, Decimal("0.0")),
            unit="index",
            source="mock-macro",
            data_version="macro-v1",
        )
        for idx, indicator_id in enumerate(indicators)
    ]


__all__ = [
    "MockMacroProvider",
    "MockNewsProvider",
    "build_default_mock_macro",
    "build_default_mock_news",
]
