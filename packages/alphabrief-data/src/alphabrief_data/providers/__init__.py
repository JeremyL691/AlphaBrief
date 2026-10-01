"""Market data provider interface for AlphaBrief.

This subpackage defines the protocol that external market data providers
must implement to plug into AlphaBrief's Data Layer. Market data in v1
comes from OANDA (see ``alphabrief_execution.broker.oanda``); the protocol
stays here so alternative read-only sources can be added without touching
callers.

All providers in this subpackage:

1. Return timezone-aware :class:`alphabrief_core.Bar` objects only.
2. Expose an injectable ``http_get`` callable for deterministic tests.
3. Surface network and parse failures as
   :class:`MarketDataProviderError` — never as raw ``urllib`` errors.
4. Reject any config or symbol value that would require an API key.
5. Never log, store, or transmit secrets.
"""

from alphabrief_data.providers.base import (
    MarketDataProvider,
    MarketDataProviderError,
    MarketDataProviderErrorCode,
    RetryPolicy,
    call_with_retry,
    compute_backoff_delay,
    is_retryable_exception,
)

__all__ = [
    "MarketDataProvider",
    "MarketDataProviderError",
    "MarketDataProviderErrorCode",
    "RetryPolicy",
    "call_with_retry",
    "compute_backoff_delay",
    "is_retryable_exception",
]
