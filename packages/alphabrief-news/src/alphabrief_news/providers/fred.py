"""FRED macro-economic data provider (Phase 11 real implementation).

FRED is the Federal Reserve Economic Data service from the Federal
Reserve Bank of St. Louis. A free API key is required and can be
obtained from https://fred.stlouisfed.org/docs/api/api_key.html.

This provider:

* reads the API key from the ``FRED_API_KEY`` environment variable
  (or an explicit ``api_key`` constructor argument);
* refuses to operate when the key is missing — callers see a
  structured ``NO_API_KEY`` error instead of a request failure;
* calls only ``api.stlouisfed.org`` via ``urllib``;
* never logs, stores, or returns the API key in any exception
  message or payload.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import cast

from alphabrief_data.providers import (
    RetryPolicy,
    call_with_retry,
    is_retryable_exception,
)

from alphabrief_news.providers.base import (
    HttpGet,
    NewsProviderError,
    NewsProviderErrorCode,
)
from alphabrief_news.types import MacroFetchQuery, MacroIndicator

_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
_DEFAULT_TIMEOUT = 30.0


def _default_http_get(request: urllib.request.Request, timeout_seconds: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return cast(bytes, response.read())


class FredMacroProvider:
    """Real FRED macro provider.

    A free FRED API key is required. The key can be supplied directly or
    read from the ``FRED_API_KEY`` environment variable at call time.
    """

    provider_name = "fred"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        http_get: HttpGet | None = None,
    ) -> None:
        self._explicit_key = api_key
        self._http_get = http_get or _default_http_get

    def _resolve_api_key(self) -> str:
        key = self._explicit_key or os.environ.get("FRED_API_KEY")
        if not key or not key.strip():
            raise NewsProviderError(
                NewsProviderErrorCode.NO_API_KEY,
                (
                    "FRED macro provider requires a FRED_API_KEY environment "
                    "variable. Set it at runtime and retry. No key is "
                    "stored in AlphaBrief code."
                ),
            )
        return key.strip()

    def fetch_indicators(self, query: MacroFetchQuery) -> list[MacroIndicator]:
        """Fetch macro observations for every requested series."""
        if not query.indicators:
            raise NewsProviderError(
                NewsProviderErrorCode.INVALID_CONFIG,
                "at least one indicator is required",
            )
        if query.end <= query.start:
            raise NewsProviderError(
                NewsProviderErrorCode.INVALID_CONFIG,
                "end must be after start",
            )

        api_key = self._resolve_api_key()

        results: list[MacroIndicator] = []
        for series_id in query.indicators:
            results.extend(self._fetch_series(series_id, query, api_key))
        return results

    def _fetch_series(
        self,
        series_id: str,
        query: MacroFetchQuery,
        api_key: str,
    ) -> list[MacroIndicator]:
        params = {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": query.start.date().isoformat(),
            "observation_end": query.end.date().isoformat(),
        }
        url = f"{_BASE_URL}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "AlphaBrief/0.0"},
        )

        try:
            body = self._http_with_retry(request)
        except NewsProviderError:
            raise

        if not body:
            raise NewsProviderError(
                NewsProviderErrorCode.EMPTY_RESPONSE,
                "FRED returned an empty response",
            )

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise NewsProviderError(
                NewsProviderErrorCode.PARSE_ERROR,
                f"invalid FRED JSON: {exc}",
            ) from exc

        observations = payload.get("observations", [])
        if not isinstance(observations, list):
            raise NewsProviderError(
                NewsProviderErrorCode.PARSE_ERROR,
                "FRED response missing observations list",
            )

        results: list[MacroIndicator] = []
        for entry in observations:
            value_raw = entry.get("value")
            if value_raw in (None, "", "."):
                continue
            try:
                value = Decimal(str(value_raw))
            except Exception as exc:
                raise NewsProviderError(
                    NewsProviderErrorCode.PARSE_ERROR,
                    f"FRED observation value is not numeric: {value_raw}",
                ) from exc
            date_str = entry.get("date")
            if not date_str:
                continue
            from datetime import UTC, datetime

            released_at = datetime.fromisoformat(f"{date_str}T00:00:00+00:00")
            released_at = released_at.astimezone(UTC)
            results.append(
                MacroIndicator(
                    indicator_id=f"fred:{series_id}",
                    name=series_id,
                    country="US",
                    released_at=released_at,
                    period=date_str,
                    value=value,
                    unit=None,
                    source="fred",
                    data_version=query.data_version,
                )
            )
        return results

    def _http_with_retry(self, request: urllib.request.Request) -> bytes:
        policy = RetryPolicy()

        def _do() -> bytes:
            return self._http_get(request, _DEFAULT_TIMEOUT)

        try:
            return cast(
                bytes,
                call_with_retry(
                    _do,
                    retry_policy=policy,
                    is_retryable=is_retryable_exception,
                ),
            )
        except NewsProviderError:
            raise
        except Exception as exc:
            from urllib.error import HTTPError, URLError

            if isinstance(exc, HTTPError):
                if exc.code in (418, 429) or exc.code >= 500:
                    raise NewsProviderError(
                        NewsProviderErrorCode.RATE_LIMITED,
                        f"FRED rate limited or server error: {exc.code}",
                    ) from exc
                raise NewsProviderError(
                    NewsProviderErrorCode.HTTP_ERROR,
                    f"FRED HTTP error: {exc.code}",
                ) from exc
            if isinstance(exc, URLError):
                raise NewsProviderError(
                    NewsProviderErrorCode.NETWORK_ERROR,
                    f"FRED network error: {exc}",
                ) from exc
            raise NewsProviderError(
                NewsProviderErrorCode.NETWORK_ERROR,
                f"FRED unexpected error: {exc}",
            ) from exc


__all__ = ["FredMacroProvider"]
