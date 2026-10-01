"""News & macro provider implementations for AlphaBrief.

All network-backed providers in this package use ``urllib`` only, expose an
injectable ``http_get`` callable for tests, and reuse the retry helpers from
``alphabrief_data.providers``.

Deterministic in-memory providers used by tests live in
``tests/news_mock_provider.py`` so runtime code can never import a mock.
"""

from __future__ import annotations

from alphabrief_news.providers.base import (
    MacroProvider,
    NewsProvider,
    NewsProviderError,
    NewsProviderErrorCode,
)
from alphabrief_news.providers.fred import FredMacroProvider
from alphabrief_news.providers.rss import RssNewsProvider

__all__ = [
    "FredMacroProvider",
    "MacroProvider",
    "NewsProvider",
    "NewsProviderError",
    "NewsProviderErrorCode",
    "RssNewsProvider",
]
