"""Market data provider interface for AlphaBrief.

This subpackage defines the protocol that external market data providers
must implement to plug into AlphaBrief's Data Layer. Two free, key-less
HTTP providers ship with the package: ``YahooFinanceProvider`` and
``BinanceProvider``. Both use the Python standard library's
``urllib.request`` only and never call any third-party SDK.

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
from alphabrief_data.providers.binance import BinanceProvider
from alphabrief_data.providers.yahoo import YahooFinanceProvider

__all__ = [
    "BinanceProvider",
    "MarketDataProvider",
    "MarketDataProviderError",
    "MarketDataProviderErrorCode",
    "RetryPolicy",
    "YahooFinanceProvider",
    "call_with_retry",
    "compute_backoff_delay",
    "is_retryable_exception",
]
