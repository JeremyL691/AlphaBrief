"""News & macro provider implementations for AlphaBrief.

All network-backed providers in this package use ``urllib`` only, expose an
injectable ``http_get`` callable for tests, and reuse the retry helpers from
``alphabrief_data.providers``.
"""

from __future__ import annotations

from alphabrief_news.providers.base import (
    MacroProvider,
    NewsProvider,
    NewsProviderError,
    NewsProviderErrorCode,
)
from alphabrief_news.providers.fred import FredMacroProvider
from alphabrief_news.providers.mock import (
    MockMacroProvider,
    MockNewsProvider,
    build_default_mock_macro,
    build_default_mock_news,
)
from alphabrief_news.providers.rss import RssNewsProvider

__all__ = [
    "FredMacroProvider",
    "MacroProvider",
    "MockMacroProvider",
    "MockNewsProvider",
    "NewsProvider",
    "NewsProviderError",
    "NewsProviderErrorCode",
    "RssNewsProvider",
    "build_default_mock_macro",
    "build_default_mock_news",
]
