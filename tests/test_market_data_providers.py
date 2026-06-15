"""Tests for the free market data providers shipped with AlphaBrief.

These tests use injected HTTP callables (``http_get``) and never make
real network requests. They cover:

1. HTTP request construction (URL, query parameters).
2. JSON response parsing for both Yahoo and Binance payload shapes.
3. Error handling: invalid config, invalid symbol/interval/range,
   network errors, HTTP error codes, rate limiting, parse errors.
4. Output invariants: bars are sorted, timezone-aware, and tagged with
   the correct provider name and a stable ``data_version``.

The tests run as a single pytest module. The full provider coverage
exceeds the 10-test floor required by the Phase 9 plan.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.message import Message
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest
from alphabrief_core import Bar
from alphabrief_data import (
    BinanceProvider,
    MarketDataProvider,
    MarketDataProviderError,
    MarketDataProviderErrorCode,
    RetryPolicy,
    YahooFinanceProvider,
    call_with_retry,
    compute_backoff_delay,
    is_retryable_exception,
)

# ---------------------------------------------------------------------------
# Shared fixtures and helpers
# ---------------------------------------------------------------------------


def _yahoo_payload(
    timestamps: list[int],
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
) -> bytes:
    """Build a minimal valid Yahoo Finance chart payload."""
    return json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "meta": {"symbol": "AAPL"},
                        "timestamp": timestamps,
                        "indicators": {
                            "quote": [
                                {
                                    "open": opens,
                                    "high": highs,
                                    "low": lows,
                                    "close": closes,
                                    "volume": volumes,
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }
    ).encode("utf-8")


def _binance_payload(rows: list[list[Any]]) -> bytes:
    """Build a minimal valid Binance klines payload."""
    return json.dumps(rows).encode("utf-8")


def _http_capture(responses: list[bytes] | bytes) -> tuple[Any, list[dict[str, Any]]]:
    """Return a (callable, captures) pair.

    The callable yields the next response from *responses* on each
    invocation and records the call arguments into the captures list.
    """
    captures: list[dict[str, Any]] = []
    queue = (
        [responses]
        if isinstance(responses, bytes)
        else list(responses)
    )

    def http_get(request: Request, timeout_seconds: float) -> bytes:
        captures.append(
            {
                "url": request.full_url,
                "timeout": timeout_seconds,
                "headers": dict(request.header_items()),
            }
        )
        if not queue:
            raise AssertionError("http_get called with no queued response")
        return queue.pop(0)

    return http_get, captures


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


def test_yahoo_provider_satisfies_market_data_provider_protocol() -> None:
    provider = YahooFinanceProvider()
    assert isinstance(provider, MarketDataProvider)
    assert provider.provider_name == "yahoo"


def test_binance_provider_satisfies_market_data_provider_protocol() -> None:
    provider = BinanceProvider()
    assert isinstance(provider, MarketDataProvider)
    assert provider.provider_name == "binance"


# ---------------------------------------------------------------------------
# Yahoo provider — happy path
# ---------------------------------------------------------------------------


def test_yahoo_provider_parses_valid_payload() -> None:
    base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    ts = [int(base.timestamp()), int(base.timestamp()) + 86_400]
    payload = _yahoo_payload(
        timestamps=ts,
        opens=[100.0, 101.0],
        highs=[110.0, 111.0],
        lows=[95.0, 96.0],
        closes=[105.0, 106.0],
        volumes=[1234.0, 1500.0],
    )
    http_get, captures = _http_capture(payload)
    provider = YahooFinanceProvider(http_get=http_get)

    bars = provider.fetch_ohlcv(
        symbol="AAPL",
        start=base,
        end=base + timedelta(days=2),
        interval="1d",
    )

    assert len(bars) == 2
    assert all(isinstance(bar, Bar) for bar in bars)
    assert bars[0].symbol == "AAPL"
    assert bars[0].source == "yahoo"
    assert bars[0].data_version == "yahoo-1d-v1"
    assert bars[0].open == Decimal("100")
    assert bars[0].close == Decimal("105")
    assert bars[0].volume == Decimal("1234")
    assert bars[0].timestamp.tzinfo is not None
    assert bars[1].timestamp > bars[0].timestamp
    assert "query1.finance.yahoo.com" in str(captures[0]["url"])
    assert "interval=1d" in str(captures[0]["url"])
    assert "symbol=AAPL" not in str(captures[0]["url"])  # in path, not query


def test_yahoo_provider_returns_empty_list_for_empty_range() -> None:
    http_get, _ = _http_capture(b'{"chart":{"result":[],"error":null}}')
    provider = YahooFinanceProvider(http_get=http_get)

    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start
    bars = provider.fetch_ohlcv(
        symbol="AAPL", start=start, end=end, interval="1d"
    )
    assert bars == []


def test_yahoo_provider_returns_empty_list_for_empty_response_payload() -> None:
    http_get, _ = _http_capture(b'{"chart":{"result":[],"error":null}}')
    provider = YahooFinanceProvider(http_get=http_get)

    bars = provider.fetch_ohlcv(
        symbol="AAPL",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 3, tzinfo=UTC),
        interval="1d",
    )
    assert bars == []


def test_yahoo_provider_skips_null_rows() -> None:
    base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    ts = [int(base.timestamp()), int(base.timestamp()) + 86_400]
    payload = json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "meta": {"symbol": "AAPL"},
                        "timestamp": ts,
                        "indicators": {
                            "quote": [
                                {
                                    "open": [100.0, None],
                                    "high": [110.0, 111.0],
                                    "low": [95.0, 96.0],
                                    "close": [105.0, 106.0],
                                    "volume": [1234.0, 1500.0],
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }
    ).encode("utf-8")
    http_get, _ = _http_capture(payload)
    provider = YahooFinanceProvider(http_get=http_get)

    bars = provider.fetch_ohlcv(
        symbol="AAPL",
        start=base,
        end=base + timedelta(days=2),
        interval="1d",
    )
    assert len(bars) == 1


# ---------------------------------------------------------------------------
# Yahoo provider — error handling
# ---------------------------------------------------------------------------


def test_yahoo_provider_raises_on_invalid_config() -> None:
    with pytest.raises(MarketDataProviderError) as exc_info:
        YahooFinanceProvider(timeout_seconds=0)
    assert exc_info.value.code == MarketDataProviderErrorCode.INVALID_CONFIG


def test_yahoo_provider_raises_on_empty_symbol() -> None:
    http_get, _ = _http_capture(b"{}")
    provider = YahooFinanceProvider(http_get=http_get)
    with pytest.raises(MarketDataProviderError) as exc_info:
        provider.fetch_ohlcv(
            symbol="",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            interval="1d",
        )
    assert exc_info.value.code == MarketDataProviderErrorCode.INVALID_SYMBOL


def test_yahoo_provider_raises_on_unsupported_interval() -> None:
    http_get, _ = _http_capture(b"{}")
    provider = YahooFinanceProvider(http_get=http_get)
    with pytest.raises(MarketDataProviderError) as exc_info:
        provider.fetch_ohlcv(
            symbol="AAPL",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            interval="2h",
        )
    assert exc_info.value.code == MarketDataProviderErrorCode.INVALID_INTERVAL


def test_yahoo_provider_raises_on_naive_start() -> None:
    http_get, _ = _http_capture(b"{}")
    provider = YahooFinanceProvider(http_get=http_get)
    with pytest.raises(MarketDataProviderError) as exc_info:
        provider.fetch_ohlcv(
            symbol="AAPL",
            start=datetime(2024, 1, 1),  # naive
            end=datetime(2024, 1, 2, tzinfo=UTC),
            interval="1d",
        )
    assert exc_info.value.code == MarketDataProviderErrorCode.INVALID_DATE_RANGE


def test_yahoo_provider_raises_on_http_error() -> None:
    def http_get(_request: Request, _timeout: float) -> bytes:
        raise HTTPError(
            "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
            500,
            "Internal Server Error",
            Message(),
            None,
        )

    provider = YahooFinanceProvider(http_get=http_get)
    with pytest.raises(MarketDataProviderError) as exc_info:
        provider.fetch_ohlcv(
            symbol="AAPL",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            interval="1d",
        )
    assert exc_info.value.code == MarketDataProviderErrorCode.HTTP_ERROR


def test_yahoo_provider_raises_on_rate_limit() -> None:
    def http_get(_request: Request, _timeout: float) -> bytes:
        raise HTTPError(
            "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
            429,
            "Too Many Requests",
            Message(),
            None,
        )

    provider = YahooFinanceProvider(http_get=http_get)
    with pytest.raises(MarketDataProviderError) as exc_info:
        provider.fetch_ohlcv(
            symbol="AAPL",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            interval="1d",
        )
    assert exc_info.value.code == MarketDataProviderErrorCode.RATE_LIMITED


def test_yahoo_provider_raises_on_network_error() -> None:
    def http_get(_request: Request, _timeout: float) -> bytes:
        raise URLError("connection refused")

    provider = YahooFinanceProvider(http_get=http_get)
    with pytest.raises(MarketDataProviderError) as exc_info:
        provider.fetch_ohlcv(
            symbol="AAPL",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            interval="1d",
        )
    assert exc_info.value.code == MarketDataProviderErrorCode.NETWORK_ERROR


def test_yahoo_provider_raises_on_invalid_json() -> None:
    http_get, _ = _http_capture(b"not json")
    provider = YahooFinanceProvider(http_get=http_get)
    with pytest.raises(MarketDataProviderError) as exc_info:
        provider.fetch_ohlcv(
            symbol="AAPL",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            interval="1d",
        )
    assert exc_info.value.code == MarketDataProviderErrorCode.PARSE_ERROR


def test_yahoo_provider_raises_on_api_error_payload() -> None:
    payload = json.dumps(
        {"chart": {"result": [], "error": "Invalid symbol"}}
    ).encode("utf-8")
    http_get, _ = _http_capture(payload)
    provider = YahooFinanceProvider(http_get=http_get)
    with pytest.raises(MarketDataProviderError) as exc_info:
        provider.fetch_ohlcv(
            symbol="NOPE",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            interval="1d",
        )
    assert exc_info.value.code == MarketDataProviderErrorCode.HTTP_ERROR


# ---------------------------------------------------------------------------
# Binance provider — happy path
# ---------------------------------------------------------------------------


def test_binance_provider_parses_valid_payload() -> None:
    base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    base_ms = int(base.timestamp() * 1000)
    rows = [
        [
            base_ms,
            "100.50",
            "110.00",
            "95.25",
            "105.75",
            "1234.50",
            base_ms + 86_400_000 - 1,
        ],
        [
            base_ms + 86_400_000,
            "105.75",
            "111.00",
            "101.00",
            "108.00",
            "2000.00",
            base_ms + 2 * 86_400_000 - 1,
        ],
    ]
    http_get, captures = _http_capture(_binance_payload(rows))
    provider = BinanceProvider(http_get=http_get)

    bars = provider.fetch_ohlcv(
        symbol="BTCUSDT",
        start=base,
        end=base + timedelta(days=2),
        interval="1d",
    )

    assert len(bars) == 2
    assert all(isinstance(bar, Bar) for bar in bars)
    assert bars[0].symbol == "BTCUSDT"
    assert bars[0].source == "binance"
    assert bars[0].data_version == "binance-1d-v1"
    assert bars[0].open == Decimal("100.50")
    assert bars[0].close == Decimal("105.75")
    assert bars[0].volume == Decimal("1234.50")
    assert bars[0].timestamp.tzinfo is not None
    assert bars[1].timestamp > bars[0].timestamp
    assert "api.binance.com" in str(captures[0]["url"])
    assert "symbol=BTCUSDT" in str(captures[0]["url"])
    assert "interval=1d" in str(captures[0]["url"])


def test_binance_provider_returns_empty_list_for_empty_array() -> None:
    http_get, _ = _http_capture(_binance_payload([]))
    provider = BinanceProvider(http_get=http_get)
    bars = provider.fetch_ohlcv(
        symbol="BTCUSDT",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 2, tzinfo=UTC),
        interval="1d",
    )
    assert bars == []


# ---------------------------------------------------------------------------
# Binance provider — error handling
# ---------------------------------------------------------------------------


def test_binance_provider_raises_on_invalid_config() -> None:
    with pytest.raises(MarketDataProviderError) as exc_info:
        BinanceProvider(timeout_seconds=0)
    assert exc_info.value.code == MarketDataProviderErrorCode.INVALID_CONFIG


def test_binance_provider_raises_on_lowercase_symbol() -> None:
    http_get, _ = _http_capture(b"[]")
    provider = BinanceProvider(http_get=http_get)
    with pytest.raises(MarketDataProviderError) as exc_info:
        provider.fetch_ohlcv(
            symbol="btcusdt",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            interval="1d",
        )
    assert exc_info.value.code == MarketDataProviderErrorCode.INVALID_SYMBOL


def test_binance_provider_raises_on_unsupported_interval() -> None:
    http_get, _ = _http_capture(b"[]")
    provider = BinanceProvider(http_get=http_get)
    with pytest.raises(MarketDataProviderError) as exc_info:
        provider.fetch_ohlcv(
            symbol="BTCUSDT",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            interval="1wk",
        )
    assert exc_info.value.code == MarketDataProviderErrorCode.INVALID_INTERVAL


def test_binance_provider_raises_on_http_error() -> None:
    def http_get(_request: Request, _timeout: float) -> bytes:
        raise HTTPError(
            "https://api.binance.com/api/v3/klines",
            500,
            "Internal Server Error",
            Message(),
            None,
        )

    provider = BinanceProvider(http_get=http_get)
    with pytest.raises(MarketDataProviderError) as exc_info:
        provider.fetch_ohlcv(
            symbol="BTCUSDT",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            interval="1d",
        )
    assert exc_info.value.code == MarketDataProviderErrorCode.HTTP_ERROR


def test_binance_provider_raises_on_rate_limit() -> None:
    def http_get(_request: Request, _timeout: float) -> bytes:
        raise HTTPError(
            "https://api.binance.com/api/v3/klines",
            429,
            "Too Many Requests",
            Message(),
            None,
        )

    provider = BinanceProvider(http_get=http_get)
    with pytest.raises(MarketDataProviderError) as exc_info:
        provider.fetch_ohlcv(
            symbol="BTCUSDT",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            interval="1d",
        )
    assert exc_info.value.code == MarketDataProviderErrorCode.RATE_LIMITED


def test_binance_provider_raises_on_network_error() -> None:
    def http_get(_request: Request, _timeout: float) -> bytes:
        raise URLError("dns failure")

    provider = BinanceProvider(http_get=http_get)
    with pytest.raises(MarketDataProviderError) as exc_info:
        provider.fetch_ohlcv(
            symbol="BTCUSDT",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            interval="1d",
        )
    assert exc_info.value.code == MarketDataProviderErrorCode.NETWORK_ERROR


def test_binance_provider_raises_on_invalid_kline_row() -> None:
    payload = _binance_payload([["not", "a", "valid", "kline", "row", "x"]])
    http_get, _ = _http_capture(payload)
    provider = BinanceProvider(http_get=http_get)
    with pytest.raises(MarketDataProviderError) as exc_info:
        provider.fetch_ohlcv(
            symbol="BTCUSDT",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            interval="1d",
        )
    assert exc_info.value.code == MarketDataProviderErrorCode.PARSE_ERROR


def test_binance_provider_raises_on_non_list_response() -> None:
    http_get, _ = _http_capture(b'{"error":"bad"}')
    provider = BinanceProvider(http_get=http_get)
    with pytest.raises(MarketDataProviderError) as exc_info:
        provider.fetch_ohlcv(
            symbol="BTCUSDT",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            interval="1d",
        )
    assert exc_info.value.code == MarketDataProviderErrorCode.PARSE_ERROR


# ---------------------------------------------------------------------------
# Phase 9 R2: retry policy and retry helper unit tests
# ---------------------------------------------------------------------------


def test_is_retryable_returns_true_for_rate_limit_codes() -> None:
    for code in (429, 418):
        exc = HTTPError("https://example/", code, "rate limited", Message(), None)
        assert is_retryable_exception(exc) is True


def test_is_retryable_returns_true_for_5xx_server_errors() -> None:
    for code in (500, 502, 503, 504):
        exc = HTTPError("https://example/", code, "server error", Message(), None)
        assert is_retryable_exception(exc) is True


def test_is_retryable_returns_false_for_non_rate_limit_4xx() -> None:
    for code in (400, 401, 403, 404, 422):
        exc = HTTPError("https://example/", code, "client error", Message(), None)
        assert is_retryable_exception(exc) is False


def test_is_retryable_returns_true_for_transient_network_errors() -> None:
    assert is_retryable_exception(URLError("connection refused")) is True
    assert is_retryable_exception(OSError("disk gone")) is True
    assert is_retryable_exception(TimeoutError("timed out")) is True
    assert is_retryable_exception(ConnectionError("reset")) is True


def test_is_retryable_returns_false_for_unrelated_errors() -> None:
    assert is_retryable_exception(ValueError("bad value")) is False
    assert is_retryable_exception(KeyError("missing")) is False
    assert is_retryable_exception(RuntimeError("oops")) is False


def test_retry_policy_rejects_invalid_max_retries() -> None:
    with pytest.raises(MarketDataProviderError) as exc_info:
        RetryPolicy(max_retries=-1)
    assert exc_info.value.code == MarketDataProviderErrorCode.INVALID_CONFIG


def test_retry_policy_rejects_invalid_jitter_factor() -> None:
    with pytest.raises(MarketDataProviderError) as exc_info:
        RetryPolicy(jitter_factor=1.0)
    assert exc_info.value.code == MarketDataProviderErrorCode.INVALID_CONFIG
    with pytest.raises(MarketDataProviderError) as exc_info:
        RetryPolicy(jitter_factor=-0.1)
    assert exc_info.value.code == MarketDataProviderErrorCode.INVALID_CONFIG


def test_compute_backoff_delay_is_deterministic_with_zero_jitter() -> None:
    policy = RetryPolicy(
        max_retries=3,
        initial_backoff_seconds=1.0,
        backoff_factor=2.0,
        max_backoff_seconds=30.0,
        jitter_factor=0.0,
    )
    # attempt=0 -> 1.0 * 1.0 = 1.0
    # attempt=1 -> 1.0 * 2.0 = 2.0
    # attempt=2 -> 1.0 * 4.0 = 4.0
    assert compute_backoff_delay(0, policy, random_fn=lambda: 0.5) == 1.0
    assert compute_backoff_delay(1, policy, random_fn=lambda: 0.5) == 2.0
    assert compute_backoff_delay(2, policy, random_fn=lambda: 0.5) == 4.0


def test_compute_backoff_delay_caps_at_max_backoff() -> None:
    policy = RetryPolicy(
        max_retries=10,
        initial_backoff_seconds=1.0,
        backoff_factor=2.0,
        max_backoff_seconds=4.0,
        jitter_factor=0.0,
    )
    # attempt=5 -> 1.0 * 32.0 = 32.0 -> capped at 4.0
    assert compute_backoff_delay(5, policy, random_fn=lambda: 0.5) == 4.0


def test_call_with_retry_succeeds_on_first_try() -> None:
    sleeps: list[float] = []
    result = call_with_retry(
        lambda: "ok",
        retry_policy=RetryPolicy(max_retries=3),
        sleep=sleeps.append,
    )
    assert result == "ok"
    assert sleeps == []


def test_call_with_retry_recovers_after_recoverable_failures() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def flaky() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise HTTPError("https://example/", 503, "down", Message(), None)
        return "ok"

    result = call_with_retry(
        flaky,
        retry_policy=RetryPolicy(
            max_retries=3,
            initial_backoff_seconds=0.0,
            jitter_factor=0.0,
        ),
        sleep=sleeps.append,
    )
    assert result == "ok"
    assert len(calls) == 3
    # Two sleeps between three attempts.
    assert len(sleeps) == 2


def test_call_with_retry_reraises_after_exhausting_budget() -> None:
    calls: list[int] = []

    def always_fails() -> None:
        calls.append(1)
        raise HTTPError("https://example/", 500, "down", Message(), None)

    with pytest.raises(HTTPError) as exc_info:
        call_with_retry(
            always_fails,
            retry_policy=RetryPolicy(
                max_retries=2,
                initial_backoff_seconds=0.0,
                jitter_factor=0.0,
            ),
            sleep=lambda _d: None,
        )
    # max_retries=2 → 3 total attempts.
    assert len(calls) == 3
    assert exc_info.value.code == 500


def test_call_with_retry_does_not_retry_4xx() -> None:
    calls: list[int] = []

    def always_400() -> None:
        calls.append(1)
        raise HTTPError("https://example/", 400, "bad", Message(), None)

    with pytest.raises(HTTPError):
        call_with_retry(
            always_400,
            retry_policy=RetryPolicy(
                max_retries=5,
                initial_backoff_seconds=0.0,
                jitter_factor=0.0,
            ),
            sleep=lambda _d: None,
        )
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Phase 9 R2: Yahoo interval expansion
# ---------------------------------------------------------------------------


def test_yahoo_provider_accepts_all_new_intervals() -> None:
    # Single queued response is never consumed because start==end
    # makes fetch_ohlcv return [] before the HTTP call.
    http_get, _ = _http_capture(
        b'{"chart":{"result":[],"error":null}}'
    )
    provider = YahooFinanceProvider(http_get=http_get)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start
    for interval in ("1m", "5m", "15m", "30m", "1h", "1d", "1wk", "1mo"):
        # No raise means validation passed.
        provider.fetch_ohlcv(
            symbol="AAPL", start=start, end=end, interval=interval
        )


def test_yahoo_provider_fetches_1wk_interval() -> None:
    base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    payload = _yahoo_payload(
        timestamps=[int(base.timestamp()), int(base.timestamp()) + 7 * 86_400],
        opens=[100.0, 101.0],
        highs=[110.0, 111.0],
        lows=[95.0, 96.0],
        closes=[105.0, 106.0],
        volumes=[1234.0, 1500.0],
    )
    http_get, captures = _http_capture(payload)
    provider = YahooFinanceProvider(http_get=http_get)

    bars = provider.fetch_ohlcv(
        symbol="AAPL",
        start=base,
        end=base + timedelta(days=14),
        interval="1wk",
    )
    assert len(bars) == 2
    assert all(bar.data_version == "yahoo-1wk-v1" for bar in bars)
    assert "interval=1wk" in str(captures[0]["url"])


def test_yahoo_provider_fetches_1mo_interval() -> None:
    base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    payload = _yahoo_payload(
        timestamps=[int(base.timestamp()), int(base.timestamp()) + 30 * 86_400],
        opens=[100.0, 101.0],
        highs=[110.0, 111.0],
        lows=[95.0, 96.0],
        closes=[105.0, 106.0],
        volumes=[1234.0, 1500.0],
    )
    http_get, captures = _http_capture(payload)
    provider = YahooFinanceProvider(http_get=http_get)

    bars = provider.fetch_ohlcv(
        symbol="AAPL",
        start=base,
        end=base + timedelta(days=60),
        interval="1mo",
    )
    assert len(bars) == 2
    assert all(bar.data_version == "yahoo-1mo-v1" for bar in bars)
    assert "interval=1mo" in str(captures[0]["url"])


def test_yahoo_provider_retries_5xx_then_succeeds() -> None:
    base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    payload = _yahoo_payload(
        timestamps=[int(base.timestamp()), int(base.timestamp()) + 86_400],
        opens=[100.0, 101.0],
        highs=[110.0, 111.0],
        lows=[95.0, 96.0],
        closes=[105.0, 106.0],
        volumes=[1234.0, 1500.0],
    )
    calls: list[int] = []

    def flaky_http_get(_request: Request, _timeout: float) -> bytes:
        calls.append(1)
        if len(calls) < 3:
            raise HTTPError(
                "https://query1.finance.yahoo.com",
                503,
                "down",
                Message(),
                None,
            )
        return payload

    provider = YahooFinanceProvider(
        http_get=flaky_http_get,
        retry_policy=RetryPolicy(
            max_retries=3,
            initial_backoff_seconds=0.0,
            jitter_factor=0.0,
        ),
    )
    bars = provider.fetch_ohlcv(
        symbol="AAPL",
        start=base,
        end=base + timedelta(days=2),
        interval="1d",
    )
    assert len(bars) == 2
    assert len(calls) == 3


def test_yahoo_provider_does_not_retry_4xx() -> None:
    calls: list[int] = []

    def always_400(_request: Request, _timeout: float) -> bytes:
        calls.append(1)
        raise HTTPError(
            "https://query1.finance.yahoo.com",
            400,
            "bad",
            Message(),
            None,
        )

    provider = YahooFinanceProvider(
        http_get=always_400,
        retry_policy=RetryPolicy(
            max_retries=5,
            initial_backoff_seconds=0.0,
            jitter_factor=0.0,
        ),
    )
    with pytest.raises(MarketDataProviderError) as exc_info:
        provider.fetch_ohlcv(
            symbol="AAPL",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            interval="1d",
        )
    assert exc_info.value.code == MarketDataProviderErrorCode.HTTP_ERROR
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Phase 9 R2: Binance interval expansion
# ---------------------------------------------------------------------------


def test_binance_provider_accepts_all_new_intervals() -> None:
    # Single queued response is never consumed because start==end
    # makes fetch_ohlcv return [] before the HTTP call.
    http_get, _ = _http_capture(_binance_payload([]))
    provider = BinanceProvider(http_get=http_get)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start
    for interval in ("1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1M"):
        provider.fetch_ohlcv(
            symbol="BTCUSDT", start=start, end=end, interval=interval
        )


def test_binance_provider_fetches_1w_interval() -> None:
    base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    base_ms = int(base.timestamp() * 1000)
    rows = [
        [
            base_ms,
            "100.50",
            "110.00",
            "95.25",
            "105.75",
            "1234.50",
            base_ms + 7 * 86_400_000 - 1,
        ]
    ]
    http_get, captures = _http_capture(_binance_payload(rows))
    provider = BinanceProvider(http_get=http_get)

    bars = provider.fetch_ohlcv(
        symbol="BTCUSDT",
        start=base,
        end=base + timedelta(days=10),
        interval="1w",
    )
    assert len(bars) == 1
    assert bars[0].data_version == "binance-1w-v1"
    assert "interval=1w" in str(captures[0]["url"])


def test_binance_provider_fetches_1M_capital_M_interval() -> None:
    base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    base_ms = int(base.timestamp() * 1000)
    rows = [
        [
            base_ms,
            "100.50",
            "110.00",
            "95.25",
            "105.75",
            "1234.50",
            base_ms + 30 * 86_400_000 - 1,
        ]
    ]
    http_get, captures = _http_capture(_binance_payload(rows))
    provider = BinanceProvider(http_get=http_get)

    bars = provider.fetch_ohlcv(
        symbol="BTCUSDT",
        start=base,
        end=base + timedelta(days=35),
        interval="1M",
    )
    assert len(bars) == 1
    assert bars[0].data_version == "binance-1M-v1"
    assert "interval=1M" in str(captures[0]["url"])


def test_binance_provider_retries_5xx_then_succeeds() -> None:
    base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    base_ms = int(base.timestamp() * 1000)
    rows = [
        [
            base_ms,
            "100.50",
            "110.00",
            "95.25",
            "105.75",
            "1234.50",
            base_ms + 86_400_000 - 1,
        ]
    ]
    calls: list[int] = []

    def flaky_http_get(_request: Request, _timeout: float) -> bytes:
        calls.append(1)
        if len(calls) < 3:
            raise HTTPError(
                "https://api.binance.com/api/v3/klines",
                500,
                "down",
                Message(),
                None,
            )
        return _binance_payload(rows)

    provider = BinanceProvider(
        http_get=flaky_http_get,
        retry_policy=RetryPolicy(
            max_retries=3,
            initial_backoff_seconds=0.0,
            jitter_factor=0.0,
        ),
    )
    bars = provider.fetch_ohlcv(
        symbol="BTCUSDT",
        start=base,
        end=base + timedelta(days=1),
        interval="1d",
    )
    assert len(bars) == 1
    assert len(calls) == 3


def test_binance_provider_does_not_retry_4xx() -> None:
    calls: list[int] = []

    def always_404(_request: Request, _timeout: float) -> bytes:
        calls.append(1)
        raise HTTPError(
            "https://api.binance.com/api/v3/klines",
            404,
            "not found",
            Message(),
            None,
        )

    provider = BinanceProvider(
        http_get=always_404,
        retry_policy=RetryPolicy(
            max_retries=5,
            initial_backoff_seconds=0.0,
            jitter_factor=0.0,
        ),
    )
    with pytest.raises(MarketDataProviderError) as exc_info:
        provider.fetch_ohlcv(
            symbol="BTCUSDT",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            interval="1d",
        )
    assert exc_info.value.code == MarketDataProviderErrorCode.HTTP_ERROR
    assert len(calls) == 1
