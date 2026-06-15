"""Yahoo Finance market data provider for AlphaBrief.

This module implements ``YahooFinanceProvider`` — a free, key-less
HTTP adapter for Yahoo Finance's unofficial chart endpoint. The
adapter uses the Python standard library ``urllib.request`` only and
never imports the ``yfinance`` SDK. The HTTP layer is exposed as a
configurable ``http_get`` callable so tests can inject deterministic
responses.

Yahoo Finance chart endpoint
``https://query1.finance.yahoo.com/v8/finance/chart/{symbol}`` returns
a JSON payload of the shape::

    {
        "chart": {
            "result": [
                {
                    "meta": {"symbol": "AAPL", ...},
                    "timestamp": [1704067200, 1704153600, ...],
                    "indicators": {
                        "quote": [
                            {
                                "open":  [100.0, 101.0, ...],
                                "high":  [110.0, 111.0, ...],
                                "low":   [ 95.0,  96.0, ...],
                                "close": [105.0, 106.0, ...],
                                "volume":[1234, 1500, ...]
                            }
                        ]
                    }
                }
            ],
            "error": null
        }
    }

Yahoo returns UNIX timestamps in **seconds**, always UTC. This module
converts them to timezone-aware :class:`datetime` objects using
``datetime.timezone.utc`` so they satisfy the AlphaBrief Bar model
constraint that all timestamps must be timezone-aware.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from alphabrief_core import Bar

from alphabrief_data.providers.base import (
    MarketDataProviderError,
    MarketDataProviderErrorCode,
    RetryPolicy,
    call_with_retry,
)

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------

_HttpGet = Callable[["Request", float], bytes]


def _default_http_get(request: Request, timeout_seconds: float) -> bytes:
    """Default HTTP GET implementation using ``urllib.request``."""
    with urlopen(request, timeout=timeout_seconds) as response:
        return cast(bytes, response.read())


# ---------------------------------------------------------------------------
# Yahoo Finance constants
# ---------------------------------------------------------------------------

#: Yahoo supports a standard set of intraday and longer-term
#: intervals. The list is intentionally limited to the values the
#: chart endpoint documents as reliable; very short or very long
#: intervals are out of scope for this MVP.
_SUPPORTED_INTERVALS: frozenset[str] = frozenset(
    {"1m", "5m", "15m", "30m", "1h", "1d", "1wk", "1mo"}
)

#: Yahoo chart endpoint base URL.
_YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"


# ---------------------------------------------------------------------------
# YahooFinanceProvider
# ---------------------------------------------------------------------------


@dataclass
class YahooFinanceProvider:
    """Free, key-less market data provider backed by Yahoo Finance.

    The provider performs a real HTTP request at runtime when its
    ``http_get`` callable is the default. Tests inject a fake
    ``http_get`` to make responses deterministic.

    Transient HTTP failures (HTTP 429, HTTP 5xx, network errors) are
    recovered automatically using the supplied ``retry_policy``.
    """

    provider_name: str = field(init=False, default="yahoo")
    timeout_seconds: float = 30.0
    http_get: _HttpGet = field(default_factory=lambda: _default_http_get)
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise MarketDataProviderError(
                "yahoo provider: timeout_seconds must be positive",
                code=MarketDataProviderErrorCode.INVALID_CONFIG,
            )
        if self.http_get is None:
            raise MarketDataProviderError(
                "yahoo provider: http_get callable is required",
                code=MarketDataProviderErrorCode.INVALID_CONFIG,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_ohlcv(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> list[Bar]:
        """Fetch OHLCV bars for *symbol* from Yahoo Finance.

        The range is treated as half-open ``[start, end)`` in the
        timezone of *start*. Empty date ranges produce empty results
        and do not raise.
        """
        _validate_symbol(symbol)
        _validate_interval(interval)
        _validate_range(start, end)

        if start >= end:
            return []

        params = (
            f"period1={int(start.timestamp())}"
            f"&period2={int(end.timestamp())}"
            f"&interval={interval}"
        )
        url = f"{_YAHOO_CHART_URL}/{quote(symbol, safe='')}?{params}"
        request = Request(url, headers={"User-Agent": "alphabrief/0.0.0"})

        try:
            raw = call_with_retry(
                lambda: self.http_get(request, self.timeout_seconds),
                retry_policy=self.retry_policy,
            )
        except HTTPError as exc:
            if exc.code in (429, 503):
                raise MarketDataProviderError(
                    f"yahoo provider: rate limited (HTTP {exc.code})",
                    code=MarketDataProviderErrorCode.RATE_LIMITED,
                ) from exc
            raise MarketDataProviderError(
                f"yahoo provider: HTTP {exc.code} {exc.reason}",
                code=MarketDataProviderErrorCode.HTTP_ERROR,
            ) from exc
        except (URLError, OSError) as exc:
            raise MarketDataProviderError(
                f"yahoo provider: network error: {exc}",
                code=MarketDataProviderErrorCode.NETWORK_ERROR,
            ) from exc

        payload = _decode_json(raw)
        result_block = _extract_result_block(payload)
        bars = _parse_chart_result(
            result_block, symbol=symbol, interval=interval
        )
        return bars


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_symbol(symbol: str) -> None:
    if not isinstance(symbol, str) or not symbol.strip():
        raise MarketDataProviderError(
            "yahoo provider: symbol must be a non-empty string",
            code=MarketDataProviderErrorCode.INVALID_SYMBOL,
        )
    if any(ch.isspace() for ch in symbol):
        raise MarketDataProviderError(
            "yahoo provider: symbol must not contain whitespace",
            code=MarketDataProviderErrorCode.INVALID_SYMBOL,
        )


def _validate_interval(interval: str) -> None:
    if interval not in _SUPPORTED_INTERVALS:
        supported = ", ".join(sorted(_SUPPORTED_INTERVALS))
        raise MarketDataProviderError(
            f"yahoo provider: unsupported interval {interval!r}; "
            f"supported: {supported}",
            code=MarketDataProviderErrorCode.INVALID_INTERVAL,
        )


def _validate_range(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or start.utcoffset() is None:
        raise MarketDataProviderError(
            "yahoo provider: start must be timezone-aware",
            code=MarketDataProviderErrorCode.INVALID_DATE_RANGE,
        )
    if end.tzinfo is None or end.utcoffset() is None:
        raise MarketDataProviderError(
            "yahoo provider: end must be timezone-aware",
            code=MarketDataProviderErrorCode.INVALID_DATE_RANGE,
        )


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _decode_json(raw: bytes) -> dict[str, Any]:
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MarketDataProviderError(
            f"yahoo provider: response is not valid JSON: {exc}",
            code=MarketDataProviderErrorCode.PARSE_ERROR,
        ) from exc
    if not isinstance(decoded, dict):
        raise MarketDataProviderError(
            "yahoo provider: response is not a JSON object",
            code=MarketDataProviderErrorCode.PARSE_ERROR,
        )
    return decoded


def _extract_result_block(payload: dict[str, Any]) -> dict[str, Any]:
    chart = payload.get("chart")
    if not isinstance(chart, dict):
        raise MarketDataProviderError(
            "yahoo provider: response is missing 'chart' object",
            code=MarketDataProviderErrorCode.PARSE_ERROR,
        )

    err = chart.get("error")
    if err:
        raise MarketDataProviderError(
            f"yahoo provider: API error: {err}",
            code=MarketDataProviderErrorCode.HTTP_ERROR,
        )

    results = chart.get("result")
    if results is None:
        raise MarketDataProviderError(
            "yahoo provider: response is missing 'chart.result'",
            code=MarketDataProviderErrorCode.EMPTY_RESPONSE,
        )
    if not isinstance(results, list):
        raise MarketDataProviderError(
            "yahoo provider: 'chart.result' is not a list",
            code=MarketDataProviderErrorCode.PARSE_ERROR,
        )
    if not results:
        # Empty result array means the provider has no data for the
        # requested range. The caller is expected to treat this as a
        # successful fetch that produced zero bars.
        return {}
    first = results[0]
    if not isinstance(first, dict):
        raise MarketDataProviderError(
            "yahoo provider: chart.result[0] is not an object",
            code=MarketDataProviderErrorCode.PARSE_ERROR,
        )
    return first


def _parse_chart_result(
    result: dict[str, Any], *, symbol: str, interval: str
) -> list[Bar]:
    if not result:
        return []
    timestamps = result.get("timestamp")
    indicators = result.get("indicators")
    if not isinstance(timestamps, list) or not isinstance(indicators, dict):
        raise MarketDataProviderError(
            "yahoo provider: result is missing timestamp or indicators",
            code=MarketDataProviderErrorCode.PARSE_ERROR,
        )

    quote_container = indicators.get("quote")
    if not isinstance(quote_container, list) or not quote_container:
        raise MarketDataProviderError(
            "yahoo provider: indicators.quote is missing",
            code=MarketDataProviderErrorCode.PARSE_ERROR,
        )

    quote_obj = quote_container[0]
    if not isinstance(quote_obj, dict):
        raise MarketDataProviderError(
            "yahoo provider: indicators.quote[0] is not an object",
            code=MarketDataProviderErrorCode.PARSE_ERROR,
        )

    opens = quote_obj.get("open", [])
    highs = quote_obj.get("high", [])
    lows = quote_obj.get("low", [])
    closes = quote_obj.get("close", [])
    volumes = quote_obj.get("volume", [])

    data_version = f"yahoo-{interval}-v1"
    bars: list[Bar] = []
    for index, raw_ts in enumerate(timestamps):
        try:
            ts = _parse_unix_seconds(raw_ts)
            o = _parse_decimal(_series_at(opens, index), "open")
            h = _parse_decimal(_series_at(highs, index), "high")
            low = _parse_decimal(_series_at(lows, index), "low")
            c = _parse_decimal(_series_at(closes, index), "close")
            v = _parse_decimal(_series_at(volumes, index), "volume")
        except MarketDataProviderError as exc:
            # Skip individual rows where Yahoo returns null entries.
            # These are common in the first/last entries of pre/post
            # market data and are not an error condition.
            if exc.code == MarketDataProviderErrorCode.PARSE_ERROR:
                continue
            raise

        try:
            bars.append(
                Bar(
                    symbol=symbol,
                    timestamp=ts,
                    open=o,
                    high=h,
                    low=low,
                    close=c,
                    volume=v,
                    source="yahoo",
                    data_version=data_version,
                )
            )
        except ValueError as bar_exc:
            raise MarketDataProviderError(
                f"yahoo provider: invalid bar at index {index}: {bar_exc}",
                code=MarketDataProviderErrorCode.PARSE_ERROR,
            ) from bar_exc

    bars.sort(key=lambda bar: bar.timestamp)
    return bars


def _series_at(series: Any, index: int) -> Any:
    if not isinstance(series, list):
        raise MarketDataProviderError(
            "yahoo provider: OHLCV series is not a list",
            code=MarketDataProviderErrorCode.PARSE_ERROR,
        )
    if index >= len(series):
        raise MarketDataProviderError(
            f"yahoo provider: series too short at index {index}",
            code=MarketDataProviderErrorCode.PARSE_ERROR,
        )
    return series[index]


def _parse_unix_seconds(value: Any) -> datetime:
    if isinstance(value, bool):
        raise MarketDataProviderError(
            "yahoo provider: invalid timestamp",
            code=MarketDataProviderErrorCode.PARSE_ERROR,
        )
    if isinstance(value, int):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, float):
        return datetime.fromtimestamp(int(value), tz=UTC)
    raise MarketDataProviderError(
        f"yahoo provider: timestamp must be a number, got "
        f"{type(value).__name__}",
        code=MarketDataProviderErrorCode.PARSE_ERROR,
    )


def _parse_decimal(value: Any, column: str) -> Decimal:
    if value is None:
        raise MarketDataProviderError(
            f"yahoo provider: {column} is missing",
            code=MarketDataProviderErrorCode.PARSE_ERROR,
        )
    if isinstance(value, bool):
        raise MarketDataProviderError(
            f"yahoo provider: {column} must not be a boolean",
            code=MarketDataProviderErrorCode.PARSE_ERROR,
        )
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation as exc:
            raise MarketDataProviderError(
                f"yahoo provider: {column} has invalid decimal {value!r}",
                code=MarketDataProviderErrorCode.PARSE_ERROR,
            ) from exc
    raise MarketDataProviderError(
        f"yahoo provider: {column} has unsupported type "
        f"{type(value).__name__}",
        code=MarketDataProviderErrorCode.PARSE_ERROR,
    )


__all__ = ["YahooFinanceProvider"]
