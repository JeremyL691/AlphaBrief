"""News & macro data layer for AlphaBrief.

This package provides structured schemas, provider protocols, mock
implementations, and lightweight free-tier readers for news headlines and
macro-economic indicators. It does not call provider SDKs directly, does not
store API keys, and does not produce research conclusions or trading signals.
"""

from __future__ import annotations

from alphabrief_news.quality import (
    HeadlineQualityReport,
    IndicatorQualityReport,
    check_indicator_quality,
)
from alphabrief_news.types import (
    MacroFetchQuery,
    MacroIndicator,
    NewsCategory,
    NewsFetchQuery,
    NewsHeadline,
    SentimentLabel,
)

__all__ = [
    "HeadlineQualityReport",
    "IndicatorQualityReport",
    "MacroFetchQuery",
    "MacroIndicator",
    "NewsCategory",
    "NewsFetchQuery",
    "NewsHeadline",
    "SentimentLabel",
    "check_indicator_quality",
]
