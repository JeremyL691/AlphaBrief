"""Unit tests for the AlphaBrief news & macro data layer."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from email.message import Message
from typing import cast
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
    SecEdgarNewsProvider,
    SocialSentimentNewsProvider,
    build_default_mock_macro,
    build_default_mock_news,
)
from alphabrief_news.quality import (
    check_headline_quality,
    check_indicator_quality,
)


def _empty_headers() -> Message:
    """Return an empty ``Message`` suitable for ``HTTPError`` headers."""
    return Message()

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
                "https://example.com", 503, "Service Unavailable",
                _empty_headers(), None,
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
            "https://example.com", 404, "Not Found", _empty_headers(), None
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


def test_fred_provider_uses_env_api_key() -> None:
    import os

    previous = os.environ.pop("FRED_API_KEY", None)
    os.environ["FRED_API_KEY"] = "test-key"
    try:
        provider = FredMacroProvider()
        captured: dict[str, object] = {}

        def fake_get(request: Request, timeout: float) -> bytes:
            captured["url"] = request.full_url
            return json_response()

        provider._http_get = fake_get
        query = MacroFetchQuery(
            indicators=["CPIAUCSL"],
            start=datetime(2024, 6, 1, tzinfo=UTC),
            end=datetime(2024, 6, 5, tzinfo=UTC),
        )
        results = provider.fetch_indicators(query)

        url = str(captured["url"])
        assert "api_key=test-key" in url
        assert "series_id=CPIAUCSL" in url
        assert len(results) == 1
        assert results[0].indicator_id == "fred:CPIAUCSL"
    finally:
        if previous is None:
            os.environ.pop("FRED_API_KEY", None)
        else:
            os.environ["FRED_API_KEY"] = previous


def test_fred_provider_uses_explicit_api_key() -> None:
    captured: dict[str, object] = {}

    def fake_get(request: Request, timeout: float) -> bytes:
        captured["url"] = request.full_url
        return json_response()

    provider = FredMacroProvider(api_key="explicit-key", http_get=fake_get)
    query = MacroFetchQuery(
        indicators=["UNRATE"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    results = provider.fetch_indicators(query)

    url = str(captured["url"])
    assert "api_key=explicit-key" in url
    assert "UNRATE" in url
    assert len(results) == 1
    assert results[0].name == "UNRATE"


def test_fred_provider_skips_missing_values() -> None:
    payload = (
        b'{"observations": ['
        b'{"date": "2024-06-01", "value": "3.7"},'
        b'{"date": "2024-06-02", "value": "."},'
        b'{"date": "2024-06-03", "value": ""}'
        b"]}"
    )

    def fake_get(request: Request, timeout: float) -> bytes:
        return payload

    provider = FredMacroProvider(api_key="key", http_get=fake_get)
    query = MacroFetchQuery(
        indicators=["UNRATE"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    results = provider.fetch_indicators(query)
    assert len(results) == 1
    assert results[0].value == Decimal("3.7")


def test_fred_provider_raises_parse_error_on_bad_json() -> None:
    def fake_get(request: Request, timeout: float) -> bytes:
        return b"not json"

    provider = FredMacroProvider(api_key="key", http_get=fake_get)
    query = MacroFetchQuery(
        indicators=["CPIAUCSL"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    with pytest.raises(NewsProviderError) as exc_info:
        provider.fetch_indicators(query)
    assert exc_info.value.code == NewsProviderErrorCode.PARSE_ERROR


def test_fred_provider_raises_network_error_on_url_error() -> None:
    from urllib.error import URLError

    def fake_get(request: Request, timeout: float) -> bytes:
        raise URLError("network down")

    provider = FredMacroProvider(api_key="key", http_get=fake_get)
    query = MacroFetchQuery(
        indicators=["CPIAUCSL"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    with pytest.raises(NewsProviderError) as exc_info:
        provider.fetch_indicators(query)
    assert exc_info.value.code == NewsProviderErrorCode.NETWORK_ERROR


def test_fred_provider_raises_http_error_on_4xx() -> None:
    from urllib.error import HTTPError

    def fake_get(request: Request, timeout: float) -> bytes:
        raise HTTPError(
            "https://api.stlouisfed.org", 400, "Bad Request",
            _empty_headers(), None,
        )

    provider = FredMacroProvider(api_key="key", http_get=fake_get)
    query = MacroFetchQuery(
        indicators=["CPIAUCSL"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    with pytest.raises(NewsProviderError) as exc_info:
        provider.fetch_indicators(query)
    assert exc_info.value.code == NewsProviderErrorCode.HTTP_ERROR


def test_fred_provider_raises_empty_response() -> None:
    def fake_get(request: Request, timeout: float) -> bytes:
        return b""

    provider = FredMacroProvider(api_key="key", http_get=fake_get)
    query = MacroFetchQuery(
        indicators=["CPIAUCSL"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    with pytest.raises(NewsProviderError) as exc_info:
        provider.fetch_indicators(query)
    assert exc_info.value.code == NewsProviderErrorCode.EMPTY_RESPONSE


def test_fred_provider_does_not_echo_api_key_in_error() -> None:
    provider = FredMacroProvider(api_key="supersecret")
    query = MacroFetchQuery(
        indicators=["CPIAUCSL"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )

    with pytest.raises(NewsProviderError) as exc_info:
        provider.fetch_indicators(query)

    assert "supersecret" not in str(exc_info.value)


def json_response() -> bytes:
    return (
        b'{"observations": ['
        b'{"date": "2024-06-01", "value": "3.7"}'
        b"]}"
    )


def test_sec_edgar_provider_parses_atom_feed() -> None:
    xml = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>SEC EDGAR filings</title>
  <entry>
    <id>urn:sec:1</id>
    <title>10-K - Annual report</title>
    <link href="https://www.sec.gov/Archives/edgar/data/1/10k.htm"/>
    <updated>2024-06-01T12:00:00Z</updated>
    <summary>Annual report for fiscal year 2023.</summary>
  </entry>
  <entry>
    <id>urn:sec:2</id>
    <title>8-K - Material event</title>
    <link href="https://www.sec.gov/Archives/edgar/data/1/8k.htm"/>
    <updated>2024-06-02T12:00:00Z</updated>
    <summary>Material event disclosure.</summary>
  </entry>
</feed>
"""
    captured: dict[str, object] = {}

    def fake_get(request: Request, timeout: float) -> bytes:
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        return xml

    provider = SecEdgarNewsProvider(http_get=fake_get)
    query = NewsFetchQuery(
        symbols=["AAPL"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    results = provider.fetch_headlines(query)

    assert len(results) == 2
    assert all(h.category == "earnings" for h in results)
    assert all(h.symbols == ["AAPL"] for h in results)
    assert all(h.source == "sec-edgar" for h in results)
    assert "AAPL" in str(captured["url"])
    assert "atom" in str(captured["url"])
    headers = cast("dict[str, str]", captured["headers"])
    assert any("AlphaBrief" in v for v in headers.values())


def test_sec_edgar_provider_filters_by_window() -> None:
    xml = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>urn:sec:1</id>
    <title>10-K - Annual report</title>
    <link href="https://www.sec.gov/1"/>
    <updated>2024-06-01T12:00:00Z</updated>
    <summary>Annual.</summary>
  </entry>
  <entry>
    <id>urn:sec:2</id>
    <title>8-K - Material event</title>
    <link href="https://www.sec.gov/2"/>
    <updated>2024-07-01T12:00:00Z</updated>
    <summary>Event.</summary>
  </entry>
</feed>
"""

    def fake_get(request: Request, timeout: float) -> bytes:
        return xml

    provider = SecEdgarNewsProvider(http_get=fake_get)
    query = NewsFetchQuery(
        symbols=["AAPL"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 30, tzinfo=UTC),
    )
    results = provider.fetch_headlines(query)
    assert len(results) == 1
    assert "10-K" in results[0].title


def test_sec_edgar_provider_rejects_invalid_ticker() -> None:
    provider = SecEdgarNewsProvider()
    query = NewsFetchQuery(
        symbols=["AAPL$"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    with pytest.raises(NewsProviderError) as exc_info:
        provider.fetch_headlines(query)
    assert exc_info.value.code == NewsProviderErrorCode.INVALID_SYMBOL


def test_sec_edgar_provider_rejects_too_long_ticker() -> None:
    provider = SecEdgarNewsProvider()
    query = NewsFetchQuery(
        symbols=["TOOLONGTICKER"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    with pytest.raises(NewsProviderError) as exc_info:
        provider.fetch_headlines(query)
    assert exc_info.value.code == NewsProviderErrorCode.INVALID_SYMBOL


def test_sec_edgar_provider_returns_empty_list_when_no_entries() -> None:
    xml = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Empty feed</title>
</feed>
"""

    def fake_get(request: Request, timeout: float) -> bytes:
        return xml

    provider = SecEdgarNewsProvider(http_get=fake_get)
    query = NewsFetchQuery(
        symbols=["AAPL"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    results = provider.fetch_headlines(query)
    assert results == []


def test_sec_edgar_provider_raises_parse_error_on_bad_xml() -> None:
    def fake_get(request: Request, timeout: float) -> bytes:
        return b"not xml"

    provider = SecEdgarNewsProvider(http_get=fake_get)
    query = NewsFetchQuery(
        symbols=["AAPL"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    with pytest.raises(NewsProviderError) as exc_info:
        provider.fetch_headlines(query)
    assert exc_info.value.code == NewsProviderErrorCode.PARSE_ERROR


def test_sec_edgar_provider_raises_http_error_on_4xx() -> None:
    from urllib.error import HTTPError

    def fake_get(request: Request, timeout: float) -> bytes:
        raise HTTPError(
            "https://www.sec.gov", 404, "Not Found", _empty_headers(), None,
        )

    provider = SecEdgarNewsProvider(http_get=fake_get)
    query = NewsFetchQuery(
        symbols=["AAPL"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    with pytest.raises(NewsProviderError) as exc_info:
        provider.fetch_headlines(query)
    assert exc_info.value.code == NewsProviderErrorCode.HTTP_ERROR


def test_sec_edgar_provider_retries_5xx() -> None:
    from urllib.error import HTTPError

    xml = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>urn:sec:1</id>
    <title>10-K</title>
    <link href="https://www.sec.gov/1"/>
    <updated>2024-06-01T12:00:00Z</updated>
    <summary>Annual.</summary>
  </entry>
</feed>
"""
    calls: list[int] = []

    def fake_get(request: Request, timeout: float) -> bytes:
        calls.append(1)
        if len(calls) == 1:
            raise HTTPError(
                "https://www.sec.gov", 503, "Service Unavailable",
                _empty_headers(), None,
            )
        return xml

    provider = SecEdgarNewsProvider(http_get=fake_get)
    query = NewsFetchQuery(
        symbols=["AAPL"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    results = provider.fetch_headlines(query)
    assert len(calls) == 2
    assert len(results) == 1


def test_sec_edgar_provider_uses_custom_user_agent() -> None:
    captured: dict[str, object] = {}

    def fake_get(request: Request, timeout: float) -> bytes:
        captured["headers"] = dict(request.header_items())
        return b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'

    provider = SecEdgarNewsProvider(
        user_agent="AlphaBrief test@example.com",
        http_get=fake_get,
    )
    query = NewsFetchQuery(
        symbols=["AAPL"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    provider.fetch_headlines(query)
    headers = cast("dict[str, str]", captured["headers"])
    assert "AlphaBrief test@example.com" in headers.values()


def test_social_sentiment_provider_returns_deterministic_data() -> None:
    provider = SocialSentimentNewsProvider()
    query = NewsFetchQuery(
        symbols=["AAPL", "TSLA"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    results = provider.fetch_headlines(query)
    assert len(results) == 2
    assert all(h.sentiment in {"positive", "negative", "neutral"} for h in results)
    assert all(h.source == "social-sentiment-stub" for h in results)
    assert all(h.category == "other" for h in results)


def test_social_sentiment_provider_respects_limit() -> None:
    provider = SocialSentimentNewsProvider()
    query = NewsFetchQuery(
        symbols=["AAPL", "TSLA", "NVDA"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
        limit=2,
    )
    results = provider.fetch_headlines(query)
    assert len(results) == 2


def test_social_sentiment_provider_returns_one_per_symbol() -> None:
    provider = SocialSentimentNewsProvider()
    query = NewsFetchQuery(
        symbols=["AAPL"],
        start=datetime(2024, 6, 1, tzinfo=UTC),
        end=datetime(2024, 6, 5, tzinfo=UTC),
    )
    results = provider.fetch_headlines(query)
    assert len(results) == 1
    assert results[0].symbols == ["AAPL"]


def test_social_sentiment_provider_satisfies_protocol() -> None:
    assert isinstance(SocialSentimentNewsProvider(), NewsProvider)


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

    assert is_retryable_exception(
        HTTPError("url", 429, "", _empty_headers(), None)
    ) is True
    assert is_retryable_exception(
        HTTPError("url", 503, "", _empty_headers(), None)
    ) is True
    assert is_retryable_exception(
        HTTPError("url", 404, "", _empty_headers(), None)
    ) is False
