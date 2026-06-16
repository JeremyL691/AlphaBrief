"""Alpha Vantage market data provider for AlphaBrief.

Alpha Vantage offers free daily/intraday OHLCV endpoints but requires
an API key. The key is read from the ``ALPHAVANTAGE_API_KEY``
environment variable or supplied via the constructor.

The provider uses only ``urllib`` and the standard library. It never
stores or logs the API key. On missing key it raises a structured
``MISSING_API_KEY`` error.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import UTC
from decimal import Decimal
from typing import cast

from alphabrief_core import Bar

from alphabrief_data.providers.base import (
    RetryPolicy,
    call_with_retry,
    is_retryable_exception,
)

_BASE_URL = "https://www.alphavantage.co/query"
_DEFAULT_TIMEOUT = 30.0

_SUPPORTED_INTERVALS: frozenset[str] = frozenset(
    {"1d", "1wk", "1mo"}
)

_INTERVAL_TO_FUNCTION: dict[str, str] = {
    "1d": "TIME_SERIES_DAILY",
    "1wk": "TIME_SERIES_WEEKLY",
    "1mo": "TIME_SERIES_MONTHLY",
}


def _default_http_get(
    request: urllib.request.Request, timeout_seconds: float,
) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return cast(bytes, response.read())


def _to_decimal(value: object) -> Decimal:
    if value is None:
        raise ValueError("Alpha Vantage returned a null value")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    return Decimal(str(value))


class AlphaVantageProvider:
    """Free Alpha Vantage OHLCV provider.

    Supports the daily / weekly / monthly endpoints. Intraday endpoints
    are not implemented in this round to keep the surface area small
    and well tested; they can be added in a later round without
    breaking the public contract.
    """

    provider_name = "alphavantage"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        http_get: object = None,
    ) -> None:
        self._explicit_key = api_key
        self._http_get = http_get or _default_http_get

    def _resolve_api_key(self) -> str:
        key = self._explicit_key or os.environ.get("ALPHAVANTAGE_API_KEY")
        if not key or not key.strip():
            raise _alphavantage_error(
                "missing_api_key",
                (
                    "Alpha Vantage provider requires ALPHAVANTAGE_API_KEY "
                    "environment variable. Set it at runtime and retry. "
                    "No key is stored in AlphaBrief code."
                ),
            )
        return key.strip()

    def fetch_ohlcv(
        self,
        *,
        symbol: str,
        start: object,
        end: object,
        interval: str,
    ) -> list[Bar]:
        """Fetch daily/weekly/monthly bars for *symbol* in [start, end)."""
        if interval not in _SUPPORTED_INTERVALS:
            raise _alphavantage_error(
                "invalid_interval",
                f"unsupported interval {interval!r}; expected one of "
                f"{sorted(_SUPPORTED_INTERVALS)}",
            )

        from datetime import datetime

        if not isinstance(start, datetime):
            start = datetime.fromisoformat(str(start))
        if not isinstance(end, datetime):
            end = datetime.fromisoformat(str(end))
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        if end <= start:
            raise _alphavantage_error(
                "invalid_date_range",
                "end must be after start",
            )

        api_key = self._resolve_api_key()
        function_name = _INTERVAL_TO_FUNCTION[interval]
        params = {
            "function": function_name,
            "symbol": symbol.upper(),
            "apikey": api_key,
            "outputsize": "full",
            "datatype": "json",
        }
        url = f"{_BASE_URL}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "AlphaBrief/0.0"},
        )

        try:
            body = self._http_with_retry(request)
        except Exception:
            raise

        if not body:
            raise _alphavantage_error(
                "empty_response",
                "Alpha Vantage returned an empty response",
            )

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise _alphavantage_error(
                "parse_error",
                f"invalid Alpha Vantage JSON: {exc}",
            ) from exc

        if "Note" in payload or "Information" in payload:
            raise _alphavantage_error(
                "rate_limited",
                f"Alpha Vantage: {payload.get('Note') or payload.get('Information')}",
            )
        if "Error Message" in payload:
            raise _alphavantage_error(
                "invalid_symbol",
                f"Alpha Vantage: {payload['Error Message']}",
            )

        series_key = next(
            (
                k for k in payload
                if k.startswith("Time Series") or "Time Series" in k
            ),
            None,
        )
        if not series_key:
            raise _alphavantage_error(
                "parse_error",
                "Alpha Vantage response missing time series",
            )

        from datetime import datetime

        bars: list[Bar] = []
        series = payload[series_key]
        if not isinstance(series, dict):
            raise _alphavantage_error(
                "parse_error",
                "Alpha Vantage time series is not a mapping",
            )

        for date_str, row in series.items():
            try:
                bar_ts = datetime.fromisoformat(date_str).replace(
                    tzinfo=UTC,
                )
            except ValueError:
                continue
            if not (start <= bar_ts < end):
                continue
            if not isinstance(row, dict):
                continue
            try:
                open_ = _to_decimal(row.get("1. open"))
                high = _to_decimal(row.get("2. high"))
                low = _to_decimal(row.get("3. low"))
                close = _to_decimal(row.get("4. close"))
                volume = _to_decimal(row.get("5. volume"))
            except Exception as exc:
                raise _alphavantage_error(
                    "parse_error",
                    f"invalid Alpha Vantage row: {exc}",
                ) from exc
            bars.append(
                Bar(
                    symbol=symbol.upper(),
                    timestamp=bar_ts,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    source="alphavantage",
                    data_version=f"alphavantage:{interval}",
                )
            )
        bars.sort(key=lambda bar: bar.timestamp)
        return bars

    def _http_with_retry(self, request: urllib.request.Request) -> bytes:
        policy = RetryPolicy()

        def _do() -> bytes:
            return self._http_get(request, _DEFAULT_TIMEOUT)  # type: ignore[operator,no-any-return]

        try:
            return cast(
                bytes,
                call_with_retry(
                    _do,
                    retry_policy=policy,
                    is_retryable=is_retryable_exception,
                ),
            )
        except Exception as exc:
            from urllib.error import HTTPError, URLError

            if isinstance(exc, HTTPError):
                if exc.code in (418, 429) or exc.code >= 500:
                    raise _alphavantage_error(
                        "rate_limited",
                        f"Alpha Vantage rate limited or server error: {exc.code}",
                    ) from exc
                raise _alphavantage_error(
                    "http_error",
                    f"Alpha Vantage HTTP error: {exc.code}",
                ) from exc
            if isinstance(exc, URLError):
                raise _alphavantage_error(
                    "network_error",
                    f"Alpha Vantage network error: {exc}",
                ) from exc
            raise _alphavantage_error(
                "network_error",
                f"Alpha Vantage unexpected error: {exc}",
            ) from exc


def _alphavantage_error(code: str, message: str) -> Exception:
    from alphabrief_data.providers import MarketDataProviderError

    return MarketDataProviderError(message, code=code)


__all__ = ["AlphaVantageProvider"]
