"""Tests for the Alpha Vantage market data provider."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from email.message import Message
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request

import pytest
from alphabrief_data import (
    AlphaVantageProvider,
    MarketDataProvider,
    MarketDataProviderError,
)


def _empty_headers() -> Message:
    """Return an empty ``Message`` suitable for ``HTTPError`` headers."""
    return Message()


def _payload(
    rows: dict[str, dict[str, str]],
    series_key: str = "Time Series (Daily)",
) -> bytes:
    return json.dumps({series_key: rows}).encode("utf-8")


def _alpha_response(body: bytes) -> Any:
    """Simple capture helper for HTTP."""
    captures: list[dict[str, Any]] = []

    def fake_get(request: Request, timeout: float) -> bytes:
        captures.append(
            {"url": request.full_url, "headers": dict(request.header_items())},
        )
        return body

    return fake_get, captures


def test_alpha_vantage_provider_raises_missing_api_key() -> None:
    import os

    previous = os.environ.pop("ALPHAVANTAGE_API_KEY", None)
    try:
        provider = AlphaVantageProvider()
        with pytest.raises(MarketDataProviderError) as exc_info:
            provider.fetch_ohlcv(
                symbol="AAPL",
                start=datetime(2024, 1, 1, tzinfo=UTC),
                end=datetime(2024, 1, 5, tzinfo=UTC),
                interval="1d",
            )
        assert exc_info.value.code == "missing_api_key"
    finally:
        if previous is not None:
            os.environ["ALPHAVANTAGE_API_KEY"] = previous


def test_alpha_vantage_provider_uses_explicit_api_key() -> None:
    body = _payload({
        "2024-01-02": {
            "1. open": "100.0",
            "2. high": "110.0",
            "3. low": "99.0",
            "4. close": "105.0",
            "5. volume": "1000",
        },
    })
    fake_get, captures = _alpha_response(body)
    provider = AlphaVantageProvider(api_key="explicit-key", http_get=fake_get)
    bars = provider.fetch_ohlcv(
        symbol="AAPL",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 5, tzinfo=UTC),
        interval="1d",
    )
    assert len(bars) == 1
    assert "apikey=explicit-key" in captures[0]["url"]
    assert bars[0].symbol == "AAPL"
    assert bars[0].close == 105.0
    assert bars[0].source == "alphavantage"


def test_alpha_vantage_provider_uses_env_api_key() -> None:
    import os

    previous = os.environ.pop("ALPHAVANTAGE_API_KEY", None)
    os.environ["ALPHAVANTAGE_API_KEY"] = "env-key"
    try:
        fake_get, captures = _alpha_response(
            _payload({
                "2024-01-02": {
                    "1. open": "1.0",
                    "2. high": "1.1",
                    "3. low": "0.9",
                    "4. close": "1.05",
                    "5. volume": "10",
                },
            }),
        )
        provider = AlphaVantageProvider(http_get=fake_get)
        provider.fetch_ohlcv(
            symbol="MSFT",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 5, tzinfo=UTC),
            interval="1d",
        )
        assert "apikey=env-key" in captures[0]["url"]
    finally:
        if previous is None:
            os.environ.pop("ALPHAVANTAGE_API_KEY", None)
        else:
            os.environ["ALPHAVANTAGE_API_KEY"] = previous


def test_alpha_vantage_provider_filters_by_window() -> None:
    body = _payload({
        "2024-01-02": {
            "1. open": "1", "2. high": "1", "3. low": "1",
            "4. close": "1", "5. volume": "1",
        },
        "2024-01-10": {
            "1. open": "2", "2. high": "2", "3. low": "2",
            "4. close": "2", "5. volume": "2",
        },
    })
    fake_get, _ = _alpha_response(body)
    provider = AlphaVantageProvider(api_key="k", http_get=fake_get)
    bars = provider.fetch_ohlcv(
        symbol="AAPL",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 5, tzinfo=UTC),
        interval="1d",
    )
    assert len(bars) == 1


def test_alpha_vantage_provider_sorts_bars_ascending() -> None:
    body = _payload({
        "2024-01-04": {
            "1. open": "1", "2. high": "1", "3. low": "1",
            "4. close": "1", "5. volume": "1",
        },
        "2024-01-02": {
            "1. open": "1", "2. high": "1", "3. low": "1",
            "4. close": "1", "5. volume": "1",
        },
    })
    fake_get, _ = _alpha_response(body)
    provider = AlphaVantageProvider(api_key="k", http_get=fake_get)
    bars = provider.fetch_ohlcv(
        symbol="AAPL",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 10, tzinfo=UTC),
        interval="1d",
    )
    assert len(bars) == 2
    assert bars[0].timestamp < bars[1].timestamp


def test_alpha_vantage_provider_supports_weekly() -> None:
    body = _payload(
        {
            "2024-01-05": {
                "1. open": "1", "2. high": "1", "3. low": "1",
                "4. close": "1", "5. volume": "1",
            },
        },
        series_key="Weekly Time Series",
    )
    fake_get, captures = _alpha_response(body)
    provider = AlphaVantageProvider(api_key="k", http_get=fake_get)
    bars = provider.fetch_ohlcv(
        symbol="AAPL",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 10, tzinfo=UTC),
        interval="1wk",
    )
    assert len(bars) == 1
    assert "TIME_SERIES_WEEKLY" in captures[0]["url"]


def test_alpha_vantage_provider_rejects_invalid_interval() -> None:
    provider = AlphaVantageProvider(api_key="k")
    with pytest.raises(MarketDataProviderError) as exc_info:
        provider.fetch_ohlcv(
            symbol="AAPL",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 5, tzinfo=UTC),
            interval="1m",
        )
    assert exc_info.value.code == "invalid_interval"


def test_alpha_vantage_provider_rejects_invalid_range() -> None:
    provider = AlphaVantageProvider(api_key="k")
    with pytest.raises(MarketDataProviderError) as exc_info:
        provider.fetch_ohlcv(
            symbol="AAPL",
            start=datetime(2024, 1, 5, tzinfo=UTC),
            end=datetime(2024, 1, 1, tzinfo=UTC),
            interval="1d",
        )
    assert exc_info.value.code == "invalid_date_range"


def test_alpha_vantage_provider_raises_on_rate_limit_note() -> None:
    body = json.dumps({"Note": "API rate limit hit"}).encode("utf-8")
    fake_get, _ = _alpha_response(body)
    provider = AlphaVantageProvider(api_key="k", http_get=fake_get)
    with pytest.raises(MarketDataProviderError) as exc_info:
        provider.fetch_ohlcv(
            symbol="AAPL",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 5, tzinfo=UTC),
            interval="1d",
        )
    assert exc_info.value.code == "rate_limited"


def test_alpha_vantage_provider_raises_on_error_message() -> None:
    body = json.dumps({"Error Message": "Invalid API key"}).encode("utf-8")
    fake_get, _ = _alpha_response(body)
    provider = AlphaVantageProvider(api_key="k", http_get=fake_get)
    with pytest.raises(MarketDataProviderError) as exc_info:
        provider.fetch_ohlcv(
            symbol="AAPL",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 5, tzinfo=UTC),
            interval="1d",
        )
    assert exc_info.value.code == "invalid_symbol"


def test_alpha_vantage_provider_raises_on_http_error() -> None:
    def fake_get(request: Request, timeout: float) -> bytes:
        raise HTTPError(
            "https://alphavantage", 503, "Service Unavailable", _empty_headers(), None,
        )

    provider = AlphaVantageProvider(api_key="k", http_get=fake_get)
    with pytest.raises(MarketDataProviderError) as exc_info:
        provider.fetch_ohlcv(
            symbol="AAPL",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 5, tzinfo=UTC),
            interval="1d",
        )
    assert exc_info.value.code in {"rate_limited", "http_error"}


def test_alpha_vantage_provider_satisfies_protocol() -> None:
    assert isinstance(AlphaVantageProvider(api_key="k"), MarketDataProvider)
