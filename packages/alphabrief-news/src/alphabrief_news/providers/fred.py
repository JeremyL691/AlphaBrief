"""FRED macro-economic data provider (stub).

FRED requires a free API key. This module implements the ``MacroProvider``
protocol but refuses to fetch data, surfacing a structured error that tells
the caller an API key is required. No secret is read from the environment or
stored in code.
"""

from __future__ import annotations

from alphabrief_news.providers.base import (
    NewsProviderError,
    NewsProviderErrorCode,
)
from alphabrief_news.types import MacroFetchQuery, MacroIndicator


class FredMacroProvider:
    """Stub implementation of the FRED macro provider.

    A future round may add a real FRED adapter. The real adapter must:
      - read the API key from an environment variable at runtime
      - never store the key in code, logs, tests, or fixtures
      - still route through the shared retry helpers
    """

    def fetch_indicators(self, query: MacroFetchQuery) -> list[MacroIndicator]:
        """Raise a structured error because FRED needs an API key."""
        raise NewsProviderError(
            NewsProviderErrorCode.NO_API_KEY,
            (
                "FRED macro provider requires a FRED_API_KEY environment "
                "variable. Set it at runtime and retry. No key is stored in "
                "AlphaBrief code."
            ),
        )


__all__ = ["FredMacroProvider"]
