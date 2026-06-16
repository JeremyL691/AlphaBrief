"""Unit tests for the AlphaBrief news & macro data layer."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from urllib.error import HTTPError
from urllib.request import Request

import pytest
from alphabrief_news import (
    MacroFetchQuery,
    MacroIndicator,
    NewsFetchQuery,
    NewsHeadline,
)
from alphabrief_news.providers import (
    FredMacroProvider,
    MacroProvider,
    MockMacroProvider,
    MockNewsProvider,
    NewsProvider,
    NewsProviderError,
    NewsProviderErrorCode,
    RssNewsProvider,
    build_default_mock_macro,
    build_default_mock_news,
)
from alphabrief_news.quality import (
    check_headline_quality,
    check_indicator_quality,
)

# ---------------------------------------------------------------------------
# Type validation
# ---------------------------------------------------------------------------


def test_news_headline_requires_timezone() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        NewsHeadline(
            headline_id="h1",
            published_at=datetime(2024, 6, 1, 9, 30),
            symbols=["AAPL"],
            category="earnings",
            source="test",
            title="Earnings",
        )


def test_news_headline_rejects_blank_title() -> None:
    with pytest.raises(ValueError, match="blank"):
        NewsHeadline(
            headline_id="h1",
            published_at=datetime(2024, 6, 1, 9, 30, tzinfo=UTC),
            symbols=["AAPL"],
            category="earnings",
            source="test",
            title="   ",
        )


def test_news_fetch_query_requires_end_after_start() -> None:
    with pytest.raises(ValueError, match="end must be after start"):
        NewsFetchQuery(
            symbols=["AAPL"],
            start=datetime(2024, 6, 2, tzinfo=UTC),
            end=datetime(2024, 6, 1, tzinfo=UTC),
        )


def test_macro_indicator_rejects_invalid_value() -> None:
    with pytest.raises(ValueError):
        MacroIndicator(
            indicator_id="CPI",
            name="CPI",
            released_at=datetime(2024, 6, 1, tzinfo=UTC),
            value=Decimal("NaN"),
            source="test",
        )


# ---------------------------------------------------------------------------
# Mock providers
# ---------------------------------------------------------------------------


def test_mock_news_provider_filters_by_symbol_and_window() -> None:
    headlines = build_default_mock_news(["AAPL", "TSLA"])
    provider = MockNewsProvider(seed_headlines=headlines)

    query = NewsFetchQuery(
        symbols=["AAPL"],
        start=datetime(2024, 6, 1, 8, 0, tzinfo=UTC),
        end=datetime(2024, 6, 1, 12, 0, tzinfo=UTC),
        limit=10,
    )
    results = provider.fetch_headlines(query)

    assert len(results) == 1
    assert results[0].symbols == ["AAPL"]


def test_mock_news_provider_respects_limit() -> None:
    headlines = build_default_mock_news(["AAPL", "TSLA", "NVDA"])
    provider = MockNewsProvider(seed_headlines=headlines)

    query = NewsFetchQuery(
        symbols=["AAPL", "TSLA", "NVDA"],
        start=datetime(2024, 6, 1, 0, 0, tzinfo=UTC),
        end=datetime(2024, 6, 2, 0, 0, tzinfo=UTC),
        limit=2,
    )
    results = provider.fetch_headlines(query)

    assert len(results) == 2


def test_mock_macro_provider_returns_requested_indicators() -> None:
    indicators = build_default_mock_macro(["CPIAUCSL", "UNRATE"])
    provider = MockMacroProvider(seed_indicators=indicators)

    query = MacroFetchQuery(
        indicators=["CPIAUCSL"],
        start=datetime(2024, 5, 1, tzinfo=UTC),
        end=datetime(2024, 7, 1, tzinfo=UTC),
    )
    results = provider.fetch_indicators(query)

    assert len(results) == 1
    assert results[0].indicator_id == "CPIAUCSL"


def test_mock_providers_satisfy_protocols() -> None:
    assert isinstance(MockNewsProvider(), NewsProvider)
    assert isinstance(MockMacroProvider(), MacroProvider)


# ---------------------------------------------------------------------------
# RSS provider
# ---------------------------------------------------------------------------


def _make_request(url: str, timeout: float) -> Request:
    return Request(url)


def test_rss_provider_parses_rss_feed() -> None:
    xml = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Market rises on tech rally</title>
      <description>Stocks climbed.</description>
      <link>https://example.com/1</link>
      <pubDate>Mon, 03 Jun 2024 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

    def fake_get(request: Request, timeout: float) -> bytes:
        return xml

    provider = RssNewsProvider(http_get=fake_get)
    query = NewsFetchQuery(
        symbols=["marketwatch-rss"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    results = provider.fetch_headlines(query)

    assert len(results) == 1
    assert results[0].title == "Market rises on tech rally"
    assert results[0].source == "Test Feed"
    assert results[0].url == "https://example.com/1"


def test_rss_provider_parses_atom_feed() -> None:
    xml = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <entry>
    <title>Fed holds rates steady</title>
    <summary>Policy unchanged.</summary>
    <link href="https://example.com/2"/>
    <published>2024-06-03T12:00:00+00:00</published>
  </entry>
</feed>
"""

    def fake_get(request: Request, timeout: float) -> bytes:
        return xml

    provider = RssNewsProvider(http_get=fake_get)
    query = NewsFetchQuery(
        symbols=["reuters-rss"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    results = provider.fetch_headlines(query)

    assert len(results) == 1
    assert results[0].title == "Fed holds rates steady"
    assert results[0].source == "Atom Feed"


def test_rss_provider_skips_items_without_title() -> None:
    xml = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Feed</title>
    <item>
      <description>No title here.</description>
      <pubDate>Mon, 03 Jun 2024 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Valid title</title>
      <pubDate>Mon, 03 Jun 2024 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

    def fake_get(request: Request, timeout: float) -> bytes:
        return xml

    provider = RssNewsProvider(http_get=fake_get)
    query = NewsFetchQuery(
        symbols=["marketwatch-rss"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    results = provider.fetch_headlines(query)

    assert len(results) == 1
    assert results[0].title == "Valid title"


def test_rss_provider_rejects_unknown_symbol() -> None:
    provider = RssNewsProvider()
    query = NewsFetchQuery(
        symbols=["unknown-feed"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    with pytest.raises(NewsProviderError) as exc_info:
        provider.fetch_headlines(query)
    assert exc_info.value.code == NewsProviderErrorCode.INVALID_SYMBOL


def test_rss_provider_raises_parse_error_on_bad_xml() -> None:
    def fake_get(request: Request, timeout: float) -> bytes:
        return b"not xml"

    provider = RssNewsProvider(http_get=fake_get)
    query = NewsFetchQuery(
        symbols=["marketwatch-rss"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    with pytest.raises(NewsProviderError) as exc_info:
        provider.fetch_headlines(query)
    assert exc_info.value.code == NewsProviderErrorCode.PARSE_ERROR


def test_rss_provider_retries_5xx_then_succeeds() -> None:
    xml = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>F</title></channel></rss>
"""
    calls: list[int] = []

    def fake_get(request: Request, timeout: float) -> bytes:
        calls.append(1)
        if len(calls) == 1:
            raise HTTPError(
                "https://example.com", 503, "Service Unavailable", {}, None
            )
        return xml

    provider = RssNewsProvider(http_get=fake_get)
    query = NewsFetchQuery(
        symbols=["marketwatch-rss"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    results = provider.fetch_headlines(query)

    assert len(calls) == 2
    assert results == []


def test_rss_provider_does_not_retry_4xx() -> None:
    calls: list[int] = []

    def fake_get(request: Request, timeout: float) -> bytes:
        calls.append(1)
        raise HTTPError(
            "https://example.com", 404, "Not Found", {}, None
        )

    provider = RssNewsProvider(http_get=fake_get)
    query = NewsFetchQuery(
        symbols=["marketwatch-rss"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    with pytest.raises(NewsProviderError) as exc_info:
        provider.fetch_headlines(query)

    assert len(calls) == 1
    assert exc_info.value.code == NewsProviderErrorCode.HTTP_ERROR


# ---------------------------------------------------------------------------
# FRED stub provider
# ---------------------------------------------------------------------------


def test_fred_provider_raises_no_api_key() -> None:
    provider = FredMacroProvider()
    query = MacroFetchQuery(
        indicators=["CPIAUCSL"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    with pytest.raises(NewsProviderError) as exc_info:
        provider.fetch_indicators(query)
    assert exc_info.value.code == NewsProviderErrorCode.NO_API_KEY


# ---------------------------------------------------------------------------
# Quality checks
# ---------------------------------------------------------------------------


def test_headline_quality_passes_on_valid_list() -> None:
    headlines = build_default_mock_news(["AAPL"])
    report = check_headline_quality(headlines)
    assert report.passed is True
    assert report.headline_count == 1


def test_headline_quality_fails_on_empty_list() -> None:
    report = check_headline_quality([])
    assert report.passed is False
    assert any(issue.code == "empty" for issue in report.issues)


def test_headline_quality_fails_on_mixed_data_version() -> None:
    h1 = build_default_mock_news(["AAPL"])[0]
    h2 = build_default_mock_news(["TSLA"])[0]
    h2.data_version = "news-v2"
    report = check_headline_quality([h1, h2])
    assert report.passed is False
    assert any(issue.code == "mixed_data_version" for issue in report.issues)


def test_headline_quality_fails_on_blank_title() -> None:
    headline = build_default_mock_news(["AAPL"])[0]
    headline.title = "   "
    report = check_headline_quality([headline])
    assert report.passed is False
    assert any(issue.code == "blank_title" for issue in report.issues)


def test_headline_quality_fails_on_duplicate_id() -> None:
    headlines = build_default_mock_news(["AAPL"])
    report = check_headline_quality(headlines + headlines)
    assert report.passed is False
    assert any(issue.code == "duplicate_id" for issue in report.issues)


def test_indicator_quality_passes_on_valid_list() -> None:
    indicators = build_default_mock_macro(["CPIAUCSL"])
    report = check_indicator_quality(indicators)
    assert report.passed is True


def test_indicator_quality_fails_on_empty_list() -> None:
    report = check_indicator_quality([])
    assert report.passed is False
    assert any(issue.code == "empty" for issue in report.issues)


def test_indicator_quality_fails_on_nan_value() -> None:
    indicator = build_default_mock_macro(["CPIAUCSL"])[0]
    indicator.value = Decimal("NaN")
    report = check_indicator_quality([indicator])
    assert report.passed is False
    assert any(issue.code == "invalid_value" for issue in report.issues)


# ---------------------------------------------------------------------------
# Retry helper re-export
# ---------------------------------------------------------------------------


def test_retry_helpers_are_available_from_provider_base() -> None:
    from alphabrief_news.providers.base import (
        RetryPolicy,
        call_with_retry,
        compute_backoff_delay,
        is_retryable_exception,
    )

    assert RetryPolicy is not None
    assert callable(call_with_retry)
    assert callable(compute_backoff_delay)
    assert callable(is_retryable_exception)


def test_is_retryable_classifies_429_and_5xx() -> None:
    from alphabrief_news.providers.base import is_retryable_exception

    assert is_retryable_exception(HTTPError("url", 429, "", {}, None)) is True
    assert is_retryable_exception(HTTPError("url", 503, "", {}, None)) is True
    assert is_retryable_exception(HTTPError("url", 404, "", {}, None)) is False
