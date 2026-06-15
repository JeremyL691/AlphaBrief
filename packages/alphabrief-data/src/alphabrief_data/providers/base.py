"""Provider base types for AlphaBrief market data providers.

This module defines the abstract protocol that all external market data
providers must satisfy, the structured error class used to surface
network and parse failures, and the shared retry helper used by the
HTTP layer.

Providers in this package return :class:`alphabrief_core.Bar` lists and
never call third-party SDKs. The HTTP layer is intentionally a callable
so tests can inject deterministic responses without monkeypatching
``urllib``.

Retry semantics
----------------

:class:`RetryPolicy` captures the retry budget and exponential-backoff
parameters shared by every provider in this package. The default
``call_with_retry`` helper retries only on **recoverable** failures:

* HTTP 429 (rate limited)
* HTTP 418 (Binance rate limited)
* HTTP 5xx (server errors)
* :class:`urllib.error.URLError`, :class:`OSError`,
  :class:`TimeoutError`, :class:`ConnectionError`

Client errors (HTTP 4xx other than 429/418) are **not** retried because
they will not succeed without caller-side changes. After the retry
budget is exhausted, the original exception is re-raised so the
provider can convert it into a structured
:class:`MarketDataProviderError`.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from urllib.error import HTTPError, URLError

from alphabrief_core import Bar

if TYPE_CHECKING:
    from urllib.request import Request

# A function that performs a GET request and returns the raw response
# body as ``bytes``. The first argument is the framework ``Request``
# instance and ``timeout_seconds`` is the configured timeout.
# Implementations delegate the actual HTTP work to this callable so
# tests can substitute a fake.
_HttpGet = Callable[["Request", float], bytes]


class MarketDataProviderErrorCode:
    """Stable error codes emitted by market data providers."""

    INVALID_CONFIG = "invalid_config"
    INVALID_SYMBOL = "invalid_symbol"
    INVALID_INTERVAL = "invalid_interval"
    INVALID_DATE_RANGE = "invalid_date_range"
    NETWORK_ERROR = "network_error"
    HTTP_ERROR = "http_error"
    RATE_LIMITED = "rate_limited"
    PARSE_ERROR = "parse_error"
    EMPTY_RESPONSE = "empty_response"


class MarketDataProviderError(ValueError):
    """Raised when a market data provider cannot produce valid bars.

    The :attr:`code` attribute carries a stable error code that
    downstream CLI/API layers can switch on without parsing free-form
    messages. It defaults to ``"provider_error"`` for forward
    compatibility with callers that construct the error directly.
    """

    def __init__(self, message: str, *, code: str = "provider_error") -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Retry / backoff helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetryPolicy:
    """Configuration for provider HTTP retries.

    Attributes:
        max_retries: Number of retries **after** the initial attempt.
            ``max_retries=3`` means at most 4 attempts in total.
        initial_backoff_seconds: Delay before the first retry. Subsequent
            delays are multiplied by ``backoff_factor`` and capped at
            ``max_backoff_seconds``.
        backoff_factor: Multiplier applied to the delay between
            successive retries. ``2.0`` yields the 1s → 2s → 4s schedule.
        max_backoff_seconds: Hard cap on a single delay.
        jitter_factor: Fractional jitter applied uniformly around the
            computed delay. ``0.1`` perturbs the delay by up to ±10% of
            its value to avoid synchronized retry storms.
    """

    max_retries: int = 3
    initial_backoff_seconds: float = 1.0
    backoff_factor: float = 2.0
    max_backoff_seconds: float = 30.0
    jitter_factor: float = 0.1

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise MarketDataProviderError(
                "retry policy: max_retries must be >= 0",
                code=MarketDataProviderErrorCode.INVALID_CONFIG,
            )
        if self.initial_backoff_seconds < 0:
            raise MarketDataProviderError(
                "retry policy: initial_backoff_seconds must be >= 0",
                code=MarketDataProviderErrorCode.INVALID_CONFIG,
            )
        if self.backoff_factor < 1.0:
            raise MarketDataProviderError(
                "retry policy: backoff_factor must be >= 1.0",
                code=MarketDataProviderErrorCode.INVALID_CONFIG,
            )
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise MarketDataProviderError(
                "retry policy: max_backoff_seconds must be >= "
                "initial_backoff_seconds",
                code=MarketDataProviderErrorCode.INVALID_CONFIG,
            )
        if self.jitter_factor < 0 or self.jitter_factor >= 1.0:
            raise MarketDataProviderError(
                "retry policy: jitter_factor must be in [0, 1)",
                code=MarketDataProviderErrorCode.INVALID_CONFIG,
            )


def is_retryable_exception(exc: BaseException) -> bool:
    """Return ``True`` when *exc* should trigger a retry.

    Retryable failures are HTTP 429, HTTP 418 (Binance rate limit),
    HTTP 5xx server errors, and transient network / timeout
    exceptions. HTTP 4xx (other than 429/418) is **not** retried.
    """
    if isinstance(exc, HTTPError):
        code = int(exc.code)  # HTTPError.code is int-like
        return code == 429 or code == 418 or 500 <= code < 600
    if isinstance(exc, (URLError, TimeoutError, ConnectionError, OSError)):
        return True
    return False


def compute_backoff_delay(
    attempt: int,
    policy: RetryPolicy,
    *,
    random_fn: Callable[[], float] = random.random,
) -> float:
    """Compute the delay before retry attempt *attempt* (0-indexed).

    The base delay is ``initial_backoff_seconds * backoff_factor**attempt``
    capped at ``max_backoff_seconds``. A symmetric uniform jitter of
    ±``jitter_factor`` is applied to the final delay.
    """
    if attempt < 0:
        raise ValueError("attempt must be >= 0")
    base = policy.initial_backoff_seconds * (policy.backoff_factor ** attempt)
    capped = min(base, policy.max_backoff_seconds)
    jitter_amplitude = policy.jitter_factor * capped
    jitter = (random_fn() * 2.0 - 1.0) * jitter_amplitude
    return max(0.0, capped + jitter)


def call_with_retry(
    fn: Callable[[], Any],
    *,
    retry_policy: RetryPolicy,
    sleep: Callable[[float], None] = time.sleep,
    is_retryable: Callable[[BaseException], bool] = is_retryable_exception,
    on_retry: Callable[[int, float, BaseException], None] | None = None,
    random_fn: Callable[[], float] = random.random,
) -> Any:
    """Invoke *fn* with exponential-backoff retries on recoverable errors.

    The function is called once first; on a retryable exception, the
    helper sleeps for the computed backoff delay and retries up to
    ``retry_policy.max_retries`` additional times. Non-retryable
    exceptions are re-raised immediately. When the retry budget is
    exhausted, the **last** exception is re-raised so callers can
    surface it as a structured provider error.

    Parameters:
        fn: Zero-argument callable to execute.
        retry_policy: Retry configuration.
        sleep: Test seam for the actual sleep call. Defaults to
            :func:`time.sleep`.
        is_retryable: Predicate that decides whether an exception is
            recoverable. Defaults to :func:`is_retryable_exception`.
        on_retry: Optional observer called with
            ``(attempt, delay_seconds, exception)`` before each retry.
        random_fn: Test seam for the jitter source. Defaults to
            :func:`random.random`.
    """
    last_exc: BaseException | None = None
    total_attempts = retry_policy.max_retries + 1
    for attempt in range(total_attempts):
        try:
            return fn()
        except BaseException as exc:  # noqa: BLE001 - intentional broad catch
            last_exc = exc
            if attempt >= retry_policy.max_retries:
                raise
            if not is_retryable(exc):
                raise
            delay = compute_backoff_delay(
                attempt, retry_policy, random_fn=random_fn
            )
            if on_retry is not None:
                on_retry(attempt, delay, exc)
            sleep(delay)
    # Unreachable: the loop either returns or raises.
    assert last_exc is not None
    raise last_exc


@runtime_checkable
class MarketDataProvider(Protocol):
    """Protocol for external market data providers.

    Implementations must be safe to construct without any network call
    and must surface all failures as
    :class:`MarketDataProviderError` instances.
    """

    provider_name: str

    def fetch_ohlcv(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> list[Bar]:
        """Fetch OHLCV bars for *symbol* in the half-open range
        ``[start, end)`` at *interval*. The returned bars are sorted
        ascending by timestamp and tagged with the provider's
        ``provider_name`` and a stable ``data_version`` derived from
        the request inputs.

        Implementations should wrap their HTTP layer with
        :func:`call_with_retry` so transient failures (429, 5xx,
        network errors) are recovered automatically before raising a
        structured :class:`MarketDataProviderError`.
        """


__all__ = [
    "MarketDataProvider",
    "MarketDataProviderError",
    "MarketDataProviderErrorCode",
    "RetryPolicy",
    "call_with_retry",
    "compute_backoff_delay",
    "is_retryable_exception",
]