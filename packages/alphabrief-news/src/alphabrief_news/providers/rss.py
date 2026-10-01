"""RSS / Atom feed reader for AlphaBrief news headlines.

This provider is intentionally minimal: it fetches a small hard-coded
allowlist of feeds, extracts only title / summary / published_at / source /
url, and ignores images, comments, and media enclosures. It uses only the
standard library so the package stays SDK-free.

Source identity (PROJECT_GUIDE S4-5): every feed carries the **publisher
label of the outlet that actually publishes it** plus its source family, so
a headline can never be attributed to the wrong outlet. Headlines are
currency-tagged (see :mod:`alphabrief_news.currency_tags`) instead of being
tagged with every traded symbol.
"""

from __future__ import annotations

import json
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.request import Request

from alphabrief_data.providers import (
    RetryPolicy,
    call_with_retry,
    is_retryable_exception,
)

from alphabrief_news.currency_tags import tag_headline_symbols
from alphabrief_news.providers.base import (
    HttpGet,
    NewsProviderError,
    NewsProviderErrorCode,
)
from alphabrief_news.types import NewsFetchQuery, NewsHeadline


@dataclass(frozen=True)
class FeedSource:
    """One allowlisted feed: its publisher, family, and currency focus."""

    key: str
    url: str
    publisher: str
    family: str
    default_currency: str | None = None


# Small allowlist of canonical, key-less RSS/Atom feeds. The provider does not
# accept arbitrary user URLs because untrusted external content must not change
# system rules. Each URL was verified to return a real RSS/Atom document
# (2026-10-01); the previous "reuters-rss" key pointed at a Bloomberg URL and
# the Bloomberg feeds themselves now redirect away from RSS, so they were
# removed rather than kept under a misleading name.
_FEED_SOURCES: dict[str, FeedSource] = {
    "marketwatch-rss": FeedSource(
        key="marketwatch-rss",
        url="https://feeds.content.dowjones.io/public/rss/mw_topstories",
        publisher="MarketWatch",
        family="marketwatch",
    ),
    "fxstreet-rss": FeedSource(
        key="fxstreet-rss",
        url="https://www.fxstreet.com/rss/news",
        publisher="FXStreet",
        family="fxstreet",
    ),
    "forexlive-rss": FeedSource(
        key="forexlive-rss",
        url="https://www.forexlive.com/feed/news",
        publisher="ForexLive",
        family="forexlive",
    ),
    "fed-press-rss": FeedSource(
        key="fed-press-rss",
        url="https://www.federalreserve.gov/feeds/press_all.xml",
        publisher="Federal Reserve",
        family="federal_reserve",
        default_currency="USD",
    ),
    "ecb-press-rss": FeedSource(
        key="ecb-press-rss",
        url="https://www.ecb.europa.eu/rss/press.html",
        publisher="European Central Bank",
        family="ecb",
        default_currency="EUR",
    ),
    "boe-news-rss": FeedSource(
        key="boe-news-rss",
        url="https://www.bankofengland.co.uk/rss/news",
        publisher="Bank of England",
        family="bank_of_england",
        default_currency="GBP",
    ),
}

#: key -> url, derived from the source table (kept for CLI/operator use).
_ALLOWED_FEEDS: dict[str, str] = {
    key: source.url for key, source in _FEED_SOURCES.items()
}

#: The independent source families the provider covers. PROJECT_GUIDE S4-5
#: requires at least three; the default table has six.
SOURCE_FAMILIES: frozenset[str] = frozenset(
    source.family for source in _FEED_SOURCES.values()
)


def feed_source(key: str) -> FeedSource:
    """The allowlisted source for one feed key."""
    source = _FEED_SOURCES.get(key)
    if source is None:
        allowed = ", ".join(sorted(_FEED_SOURCES))
        raise NewsProviderError(
            NewsProviderErrorCode.INVALID_SYMBOL,
            f"symbol must be one of the allowed feeds: {allowed}",
        )
    return source

_DEFAULT_TIMEOUT = 30.0


def _default_http_get(request: Request, timeout_seconds: float) -> bytes:
    """Perform a blocking GET and return the response body."""
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return cast(bytes, response.read())


def _http_get_with_retry(
    http_get: HttpGet, request: Request, timeout: float
) -> bytes:
    """Wrap ``http_get`` with the shared retry policy."""
    policy = RetryPolicy()

    def _get() -> bytes:
        return http_get(request, timeout)

    try:
        return cast(
            bytes,
            call_with_retry(
                _get,
                retry_policy=policy,
                is_retryable=is_retryable_exception,
            ),
        )
    except NewsProviderError:
        raise
    except HTTPError as exc:
        if exc.code in {418, 429} or exc.code >= 500:
            raise NewsProviderError(
                NewsProviderErrorCode.RATE_LIMITED,
                f"rate limited or server error after retries: {exc.code}",
            ) from exc
        raise NewsProviderError(
            NewsProviderErrorCode.HTTP_ERROR,
            f"HTTP error: {exc.code}",
        ) from exc
    except URLError as exc:
        raise NewsProviderError(
            NewsProviderErrorCode.NETWORK_ERROR,
            f"network error: {exc}",
        ) from exc
    except Exception as exc:
        raise NewsProviderError(
            NewsProviderErrorCode.NETWORK_ERROR,
            f"unexpected network error: {exc}",
        ) from exc


def _parse_iso_like(value: str) -> datetime:
    """Parse an RFC-3339 / RSS date string into a timezone-aware UTC datetime."""
    value = value.strip()
    # Try RFC 3339 first.
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.astimezone(UTC)
        except ValueError:
            continue
    # Try common RSS date formats.
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
    ):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.astimezone(UTC)
        except ValueError:
            continue
    raise ValueError(f"unsupported date format: {value}")


def _extract_text(element: ET.Element | None, tag: str) -> str | None:
    """Return stripped text of the first child matching *tag* or None."""
    if element is None:
        return None
    child = element.find(tag)
    if child is None or child.text is None:
        return None
    return child.text.strip()


def _extract_atom_text(element: ET.Element | None, ns: str, tag: str) -> str | None:
    """Return stripped text of the first Atom-namespaced child."""
    if element is None:
        return None
    child = element.find(f"{{{ns}}}{tag}")
    if child is None or child.text is None:
        return None
    return child.text.strip()


def _parse_rss_feed(xml_bytes: bytes, source: FeedSource) -> list[NewsHeadline]:
    """Parse RSS 2.0 XML into a list of headlines."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise NewsProviderError(
            NewsProviderErrorCode.PARSE_ERROR,
            f"invalid RSS XML: {exc}",
        ) from exc

    channel = root.find("channel")
    if channel is None:
        raise NewsProviderError(
            NewsProviderErrorCode.PARSE_ERROR,
            "RSS feed missing <channel>",
        )

    items = channel.findall("item")
    headlines: list[NewsHeadline] = []

    for idx, item in enumerate(items):
        title = _extract_text(item, "title")
        if not title:
            continue
        description = _extract_text(item, "description") or ""
        link = _extract_text(item, "link") or None
        pub_date = _extract_text(item, "pubDate")
        published_at = (
            _parse_iso_like(pub_date) if pub_date else datetime.now(UTC)
        )

        headlines.append(
            NewsHeadline(
                headline_id=f"{source.key}-{idx}",
                published_at=published_at,
                symbols=tag_headline_symbols(
                    title,
                    description,
                    default_currency=source.default_currency,
                ),
                category="other",
                # The publisher label from the allowlist, never the feed's
                # own <channel><title> (which can name a different outlet
                # than the one publishing the document).
                source=source.publisher,
                title=title,
                summary=description,
                url=link,
                sentiment=None,
                data_version="rss-v1",
            )
        )

    return headlines


def _parse_atom_feed(xml_bytes: bytes, source: FeedSource) -> list[NewsHeadline]:
    """Parse Atom 1.0 XML into a list of headlines."""
    ns = "http://www.w3.org/2005/Atom"
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise NewsProviderError(
            NewsProviderErrorCode.PARSE_ERROR,
            f"invalid Atom XML: {exc}",
        ) from exc

    entries = root.findall(f"{{{ns}}}entry")
    headlines: list[NewsHeadline] = []

    for idx, entry in enumerate(entries):
        title = _extract_atom_text(entry, ns, "title")
        if not title:
            continue
        summary = _extract_atom_text(entry, ns, "summary") or ""
        link_el = entry.find(f"{{{ns}}}link")
        link = None
        if link_el is not None:
            link = link_el.get("href")
        published = _extract_atom_text(entry, ns, "published")
        updated = _extract_atom_text(entry, ns, "updated")
        date_str = published or updated
        published_at = (
            _parse_iso_like(date_str) if date_str else datetime.now(UTC)
        )

        headlines.append(
            NewsHeadline(
                headline_id=f"{source.key}-{idx}",
                published_at=published_at,
                symbols=tag_headline_symbols(
                    title,
                    summary,
                    default_currency=source.default_currency,
                ),
                category="other",
                source=source.publisher,
                title=title,
                summary=summary,
                url=link,
                sentiment=None,
                data_version="rss-v1",
            )
        )

    return headlines


def _detect_and_parse(xml_bytes: bytes, source: FeedSource) -> list[NewsHeadline]:
    """Detect RSS vs Atom and parse accordingly."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise NewsProviderError(
            NewsProviderErrorCode.PARSE_ERROR,
            f"invalid XML: {exc}",
        ) from exc

    tag = root.tag.split("}")[-1] if root.tag.startswith("{") else root.tag
    if tag == "rss":
        return _parse_rss_feed(xml_bytes, source)
    if tag == "feed":
        return _parse_atom_feed(xml_bytes, source)
    raise NewsProviderError(
        NewsProviderErrorCode.PARSE_ERROR,
        f"unsupported feed root element: {root.tag}",
    )


class RssNewsProvider:
    """Provider that reads a hard-coded allowlist of RSS/Atom feeds."""

    def __init__(
        self,
        http_get: HttpGet | None = None,
        *,
        auto_sentiment: bool = True,
    ) -> None:
        self._http_get = http_get or _default_http_get
        self._auto_sentiment = auto_sentiment

    def fetch_headlines(self, query: NewsFetchQuery) -> list[NewsHeadline]:
        """Fetch and parse allowed RSS feeds, filtering by query window."""
        if len(query.symbols) != 1:
            allowed = ", ".join(sorted(_FEED_SOURCES))
            raise NewsProviderError(
                NewsProviderErrorCode.INVALID_SYMBOL,
                f"symbol must be one of the allowed feeds: {allowed}",
            )
        feed_key = query.symbols[0]
        source = feed_source(feed_key)
        request = Request(source.url, headers={"User-Agent": "AlphaBrief/0.0"})

        try:
            body = _http_get_with_retry(self._http_get, request, _DEFAULT_TIMEOUT)
        except NewsProviderError:
            raise

        if not body:
            raise NewsProviderError(
                NewsProviderErrorCode.EMPTY_RESPONSE,
                "provider returned an empty response",
            )

        headlines = _detect_and_parse(body, source)

        if self._auto_sentiment:
            from alphabrief_news.sentiment import RuleBasedSentimentAnalyzer
            analyzer = RuleBasedSentimentAnalyzer()
            headlines = [analyzer.annotate(h) for h in headlines]

        results = [
            headline
            for headline in headlines
            if query.start <= headline.published_at < query.end
        ]
        return results[: query.limit]


def _encode_symbols(symbols: list[str]) -> str:
    """Return a JSON-encoded string for storage in a VARCHAR column."""
    return json.dumps(symbols, separators=(",", ":"))


def _decode_symbols(value: str) -> list[str]:
    """Decode a JSON-encoded symbol list stored in a VARCHAR column."""
    return cast(list[str], json.loads(value))


__all__ = [
    "SOURCE_FAMILIES",
    "FeedSource",
    "RssNewsProvider",
    "_ALLOWED_FEEDS",
    "_FEED_SOURCES",
    "_decode_symbols",
    "_encode_symbols",
    "feed_source",
]
