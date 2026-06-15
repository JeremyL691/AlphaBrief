"""Binance market data provider for AlphaBrief.

This module implements ``BinanceProvider`` — a free, key-less HTTP
adapter for Binance's public klines endpoint. The adapter uses the
Python standard library ``urllib.request`` only and never imports
the ``python-binance`` SDK. The HTTP layer is exposed as a
configurable ``http_get`` callable so tests can inject deterministic
responses.

Binance public klines endpoint
``https://api.binance.com/api/v3/klines`` returns a JSON array of
arrays. Each inner array has at least the following positional
fields::

    [
        open_time,   # 0  - int - millisecond unix timestamp
        open,        # 1  - str - open price
        high,        # 2  - str - high price
        low,         # 3  - str - low price
        close,       # 4  - str - close price
        volume,      # 5  - str - volume
        close_time,  # 6  - int - millisecond unix timestamp
        ...
    ]

Binance returns timestamps in **milliseconds** and prices as
**strings**. This module converts the timestamps to timezone-aware
:class:`datetime` objects using ``datetime.timezone.utc`` and parses
prices with :class:`decimal.Decimal` to avoid float precision loss.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast
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

# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------

_HttpGet = Callable[["Request", float], bytes]


def _default_http_get(request: Request, timeout_seconds: float) -> bytes:
    """Default HTTP GET implementation using ``urllib.request``."""
    with urlopen(request, timeout=timeout_seconds) as response:
        return cast(bytes, response.read())


# ---------------------------------------------------------------------------
# Binance constants
# ---------------------------------------------------------------------------

#: Binance supports many intervals. The MVP ships the documented
#: public set used by most retail charting tools.
_SUPPORTED_INTERVALS: frozenset[str] = frozenset(
    {"1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1M"}
)

#: Binance public klines endpoint base URL.
_BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

#: Maximum number of klines Binance returns per request. The endpoint
#: documents a hard limit of 1000 rows.
_BINANCE_MAX_ROWS = 1000


# ---------------------------------------------------------------------------
# BinanceProvider
# ---------------------------------------------------------------------------


@dataclass
class BinanceProvider:
    """Free, key-less market data provider backed by Binance klines.

    The provider performs a real HTTP request at runtime when its
    ``http_get`` callable is the default. Tests inject a fake
    ``http_get`` to make responses deterministic.

    Transient HTTP failures (HTTP 418, HTTP 429, HTTP 5xx, network
    errors) are recovered automatically using the supplied
    ``retry_policy``.
    """

    provider_name: str = field(init=False, default="binance")
    timeout_seconds: float = 30.0
    http_get: _HttpGet = field(default_factory=lambda: _default_http_get)
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise MarketDataProviderError(
                "binance provider: timeout_seconds must be positive",
                code=MarketDataProviderErrorCode.INVALID_CONFIG,
            )
        if self.http_get is None:
            raise MarketDataProviderError(
                "binance provider: http_get callable is required",
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
        """Fetch OHLCV klines for *symbol* from Binance.

        The range is treated as half-open ``[start, end)`` in the
        timezone of *start*. Empty date ranges produce empty results
        and do not raise.

        Binance symbols are uppercase with no separator
        (e.g. ``BTCUSDT``). This provider does not auto-convert
        ``BTC-USD`` to ``BTCUSDT`` — callers must pass the exact
        Binance symbol. Quote currency defaults to ``USDT`` only when
        the caller appends it explicitly; this is intentional to
        avoid silently changing user intent.
        """
        _validate_symbol(symbol)
        _validate_interval(interval)
        _validate_range(start, end)

        if start >= end:
            return []

        all_bars: list[Bar] = []
        cursor = start
        while cursor < end:
            page_end = min(
                end,
                cursor.fromtimestamp(
                    cursor.timestamp() + _interval_to_seconds(interval)
                    * _BINANCE_MAX_ROWS,
                    tz=UTC,
                ),
            )
            all_bars.extend(
                self._fetch_page(
                    symbol=symbol,
                    start=cursor,
                    end=page_end,
                    interval=interval,
                )
            )
            cursor = page_end

        all_bars.sort(key=lambda bar: bar.timestamp)
        return all_bars

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_page(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> list[Bar]:
        params = (
            f"symbol={quote(symbol, safe='')}"
            f"&interval={interval}"
            f"&startTime={int(start.timestamp() * 1000)}"
            f"&endTime={int(end.timestamp() * 1000)}"
            f"&limit={_BINANCE_MAX_ROWS}"
        )
        url = f"{_BINANCE_KLINES_URL}?{params}"
        request = Request(url, headers={"User-Agent": "alphabrief/0.0.0"})

        try:
            raw = call_with_retry(
                lambda: self.http_get(request, self.timeout_seconds),
                retry_policy=self.retry_policy,
            )
        except HTTPError as exc:
            if exc.code in (418, 429):
                raise MarketDataProviderError(
                    f"binance provider: rate limited (HTTP {exc.code})",
                    code=MarketDataProviderErrorCode.RATE_LIMITED,
                ) from exc
            raise MarketDataProviderError(
                f"binance provider: HTTP {exc.code} {exc.reason}",
                code=MarketDataProviderErrorCode.HTTP_ERROR,
            ) from exc
        except (URLError, OSError) as exc:
            raise MarketDataProviderError(
                f"binance provider: network error: {exc}",
                code=MarketDataProviderErrorCode.NETWORK_ERROR,
            ) from exc

        return _parse_klines(raw, symbol=symbol, interval=interval)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_symbol(symbol: str) -> None:
    if not isinstance(symbol, str) or not symbol.strip():
        raise MarketDataProviderError(
            "binance provider: symbol must be a non-empty string",
            code=MarketDataProviderErrorCode.INVALID_SYMBOL,
        )
    if any(ch.isspace() for ch in symbol):
        raise MarketDataProviderError(
            "binance provider: symbol must not contain whitespace",
            code=MarketDataProviderErrorCode.INVALID_SYMBOL,
        )
    if not symbol.isupper():
        raise MarketDataProviderError(
            "binance provider: symbol must be uppercase (e.g. BTCUSDT)",
            code=MarketDataProviderErrorCode.INVALID_SYMBOL,
        )


def _validate_interval(interval: str) -> None:
    if interval not in _SUPPORTED_INTERVALS:
        supported = ", ".join(sorted(_SUPPORTED_INTERVALS))
        raise MarketDataProviderError(
            f"binance provider: unsupported interval {interval!r}; "
            f"supported: {supported}",
            code=MarketDataProviderErrorCode.INVALID_INTERVAL,
        )


def _validate_range(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or start.utcoffset() is None:
        raise MarketDataProviderError(
            "binance provider: start must be timezone-aware",
            code=MarketDataProviderErrorCode.INVALID_DATE_RANGE,
        )
    if end.tzinfo is None or end.utcoffset() is None:
        raise MarketDataProviderError(
            "binance provider: end must be timezone-aware",
            code=MarketDataProviderErrorCode.INVALID_DATE_RANGE,
        )


def _interval_to_seconds(interval: str) -> int:
    """Return the duration of *interval* in whole seconds."""
    mapping: dict[str, int] = {
        "1m": 60,
        "3m": 180,
        "5m": 300,
        "15m": 900,
        "30m": 1_800,
        "1h": 3_600,
        "1d": 86_400,
        "1w": 604_800,
        # 30-day month approximation, matches Binance semantics.
        "1M": 2_592_000,
    }
    seconds = mapping.get(interval)
    if seconds is None:
        raise MarketDataProviderError(
            f"binance provider: cannot translate interval {interval!r}",
            code=MarketDataProviderErrorCode.INVALID_INTERVAL,
        )
    return seconds


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_klines(
    raw: bytes, *, symbol: str, interval: str
) -> list[Bar]:
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MarketDataProviderError(
            f"binance provider: response is not valid JSON: {exc}",
            code=MarketDataProviderErrorCode.PARSE_ERROR,
        ) from exc
    if not isinstance(decoded, list):
        raise MarketDataProviderError(
            "binance provider: response is not a JSON array",
            code=MarketDataProviderErrorCode.PARSE_ERROR,
        )
    if not decoded:
        return []

    data_version = f"binance-{interval}-v1"
    bars: list[Bar] = []
    for index, row in enumerate(decoded):
        try:
            bar = _parse_kline_row(
                row, index=index, symbol=symbol, data_version=data_version
            )
        except MarketDataProviderError as exc:
            raise MarketDataProviderError(
                f"binance provider: invalid kline at index {index}: "
                f"{exc}",
                code=exc.code,
            ) from exc
        bars.append(bar)
    return bars


def _parse_kline_row(
    row: Any, *, index: int, symbol: str, data_version: str
) -> Bar:
    if not isinstance(row, list) or len(row) < 6:
        raise MarketDataProviderError(
            "kline row is too short",
            code=MarketDataProviderErrorCode.PARSE_ERROR,
        )
    open_time = _parse_unix_milliseconds(row[0], "open_time")
    open_price = _parse_decimal(row[1], "open")
    high_price = _parse_decimal(row[2], "high")
    low_price = _parse_decimal(row[3], "low")
    close_price = _parse_decimal(row[4], "close")
    volume = _parse_decimal(row[5], "volume")

    try:
        return Bar(
            symbol=symbol,
            timestamp=open_time,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=volume,
            source="binance",
            data_version=data_version,
        )
    except ValueError as bar_exc:
        raise MarketDataProviderError(
            f"invalid bar: {bar_exc}",
            code=MarketDataProviderErrorCode.PARSE_ERROR,
        ) from bar_exc


def _parse_unix_milliseconds(value: Any, column: str) -> datetime:
    if isinstance(value, bool):
        raise MarketDataProviderError(
            f"{column} must not be a boolean",
            code=MarketDataProviderErrorCode.PARSE_ERROR,
        )
    if isinstance(value, int):
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    if isinstance(value, float):
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
        except ValueError as exc:
            raise MarketDataProviderError(
                f"{column} has invalid timestamp {value!r}",
                code=MarketDataProviderErrorCode.PARSE_ERROR,
            ) from exc
    raise MarketDataProviderError(
        f"{column} has unsupported type {type(value).__name__}",
        code=MarketDataProviderErrorCode.PARSE_ERROR,
    )


def _parse_decimal(value: Any, column: str) -> Decimal:
    if isinstance(value, bool):
        raise MarketDataProviderError(
            f"{column} must not be a boolean",
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
                f"{column} has invalid decimal {value!r}",
                code=MarketDataProviderErrorCode.PARSE_ERROR,
            ) from exc
    raise MarketDataProviderError(
        f"{column} has unsupported type {type(value).__name__}",
        code=MarketDataProviderErrorCode.PARSE_ERROR,
    )


__all__ = ["BinanceProvider"]
