"""Base provider types for the AlphaBrief news & macro data layer.

The design intentionally mirrors ``alphabrief_data.providers.base`` so the
two data planes share the same retry, error-classification, and test-injection
conventions.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from alphabrief_data.providers import (
    RetryPolicy,
    call_with_retry,
    compute_backoff_delay,
    is_retryable_exception,
)

from alphabrief_news.types import (
    MacroFetchQuery,
    MacroIndicator,
    NewsFetchQuery,
    NewsHeadline,
)

if TYPE_CHECKING:
    from urllib.request import Request

# A function that performs a GET request and returns the raw response body as
# ``bytes``. Implementations delegate the actual HTTP work to this callable so
# tests can substitute a fake.
HttpGet = Callable[["Request", float], bytes]


class NewsProviderErrorCode:
    """Stable error codes emitted by news & macro providers."""

    INVALID_CONFIG = "invalid_config"
    INVALID_SYMBOL = "invalid_symbol"
    INVALID_INTERVAL = "invalid_interval"
    NETWORK_ERROR = "network_error"
    HTTP_ERROR = "http_error"
    RATE_LIMITED = "rate_limited"
    PARSE_ERROR = "parse_error"
    EMPTY_RESPONSE = "empty_response"
    NO_API_KEY = "no_api_key"
    UNSUPPORTED_OPERATION = "unsupported_operation"


class NewsProviderError(ValueError):
    """Raised when a news or macro provider cannot produce valid data.

    Carries a stable ``code`` attribute so callers can branch on the failure
    mode without parsing free-form error messages.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@runtime_checkable
class NewsProvider(Protocol):
    """Protocol for external news headline providers."""

    def fetch_headlines(self, query: NewsFetchQuery) -> list[NewsHeadline]:
        """Return headlines matching *query*.

        Raises:
            NewsProviderError: when the provider cannot return valid data.
        """


@runtime_checkable
class MacroProvider(Protocol):
    """Protocol for external macro-economic indicator providers."""

    def fetch_indicators(
        self, query: MacroFetchQuery,
    ) -> list[MacroIndicator]:
        """Return indicators matching *query*.

        Raises:
            NewsProviderError: when the provider cannot return valid data.
        """


__all__ = [
    "HttpGet",
    "MacroProvider",
    "NewsProvider",
    "NewsProviderError",
    "NewsProviderErrorCode",
    "RetryPolicy",
    "call_with_retry",
    "compute_backoff_delay",
    "is_retryable_exception",
]
