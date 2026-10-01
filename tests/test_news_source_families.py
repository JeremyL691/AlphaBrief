"""Tests for the news source families and currency tagging (PROJECT_GUIDE S4-5).

Pins the two things the guide requires of the news layer:

* at least three independent source families, each headline attributed to
  the publisher that really publishes it;
* currency-relevance tagging instead of "every headline tagged with every
  symbol".
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.request import Request

import pytest
from alphabrief_news.currency_tags import (
    GENERAL_TAG,
    TRADED_INSTRUMENTS,
    currencies_in_text,
    instruments_for_currencies,
    tag_headline_symbols,
)
from alphabrief_news.providers.base import NewsProviderError
from alphabrief_news.providers.rss import (
    _ALLOWED_FEEDS,
    _FEED_SOURCES,
    SOURCE_FAMILIES,
    RssNewsProvider,
    feed_source,
)
from alphabrief_news.types import NewsFetchQuery

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class TestSourceFamilies:
    def test_at_least_three_independent_families(self) -> None:
        assert len(SOURCE_FAMILIES) >= 3
        assert {
            "marketwatch",
            "fxstreet",
            "forexlive",
            "federal_reserve",
            "ecb",
            "bank_of_england",
        } <= SOURCE_FAMILIES

    def test_every_feed_has_a_distinct_publisher_and_url(self) -> None:
        publishers = [source.publisher for source in _FEED_SOURCES.values()]
        urls = [source.url for source in _FEED_SOURCES.values()]

        assert len(set(publishers)) == len(publishers)
        assert len(set(urls)) == len(urls)
        # The old mislabelled keys are gone: "reuters-rss" pointed at a
        # Bloomberg URL, and the Bloomberg feeds no longer serve RSS.
        assert "reuters-rss" not in _FEED_SOURCES
        assert "bloomberg-atom" not in _FEED_SOURCES
        assert set(_ALLOWED_FEEDS) == set(_FEED_SOURCES)

    def test_official_central_bank_feeds_carry_a_default_currency(self) -> None:
        assert feed_source("fed-press-rss").default_currency == "USD"
        assert feed_source("ecb-press-rss").default_currency == "EUR"
        assert feed_source("boe-news-rss").default_currency == "GBP"
        assert feed_source("fxstreet-rss").default_currency is None

    def test_unknown_feed_key_is_refused(self) -> None:
        with pytest.raises(NewsProviderError) as excinfo:
            feed_source("reuters-rss")

        assert excinfo.value.code == "invalid_symbol"


class TestCurrencyTagging:
    def test_currency_specific_items_tag_only_their_pairs(self) -> None:
        assert tag_headline_symbols("Bank of Japan keeps policy steady") == [
            "USD_JPY"
        ]
        assert tag_headline_symbols("RBA holds the cash rate") == ["AUD_USD"]
        assert tag_headline_symbols("Bank of Canada signals a pause") == [
            "USD_CAD"
        ]

    def test_usd_items_touch_every_usd_pair(self) -> None:
        # Not "all symbols by default": every traded pair genuinely
        # contains USD, so a USD item is relevant to all of them.
        tagged = tag_headline_symbols("FOMC minutes show a hawkish split")

        assert set(tagged) == set(TRADED_INSTRUMENTS)

    def test_two_currency_item_tags_both_pairs(self) -> None:
        tagged = tag_headline_symbols("ECB and BoE diverge on rate cuts")

        assert tagged == ["EUR_USD", "GBP_USD"]

    def test_no_signal_is_general_not_everything(self) -> None:
        assert tag_headline_symbols("Tech shares rally into the close") == [
            GENERAL_TAG
        ]

    def test_generic_dollar_does_not_steal_other_currencies(self) -> None:
        assert currencies_in_text("Australian dollar firms") == ("AUD",)
        assert currencies_in_text("Canadian dollar slides") == ("CAD",)
        # A bare "dollar" with no other currency is USD.
        assert currencies_in_text("The dollar firms broadly") == ("USD",)

    def test_short_codes_match_on_word_boundaries(self) -> None:
        # Substring matching would tag these wrongly.
        assert currencies_in_text("A decade of low volatility") == ()
        assert currencies_in_text("Prosecutors allege fraud") == ()
        assert currencies_in_text("CAD weakens") == ("CAD",)

    def test_instruments_for_unknown_currency_is_general(self) -> None:
        assert instruments_for_currencies(()) == [GENERAL_TAG]
        assert instruments_for_currencies(("CHF",)) == [GENERAL_TAG]

    def test_source_default_applies_only_without_a_text_signal(self) -> None:
        assert tag_headline_symbols(
            "Policy statement released", default_currency="GBP"
        ) == ["GBP_USD"]
        # The text wins over the source default.
        assert tag_headline_symbols(
            "Fed cuts rates", default_currency="GBP"
        ) != ["GBP_USD"]


class TestProviderTagging:
    """The provider must apply the tags, not the blanket symbol list."""

    def _xml(self, title: str, summary: str = "") -> bytes:
        return f"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Ignored Channel Title</title>
<item><title>{title}</title><description>{summary}</description>
<link>https://example.com/a</link>
<pubDate>Mon, 01 Jun 2026 12:00:00 GMT</pubDate></item>
</channel></rss>""".encode()

    def _fetch(self, feed: str, title: str, summary: str = "") -> object:
        xml = self._xml(title, summary)

        def fake_get(request: Request, timeout: float) -> bytes:
            return xml

        provider = RssNewsProvider(http_get=fake_get)
        results = provider.fetch_headlines(
            NewsFetchQuery(
                symbols=[feed],
                start=datetime(2026, 6, 1, tzinfo=UTC),
                end=datetime(2026, 6, 2, tzinfo=UTC),
            )
        )
        assert len(results) == 1
        return results[0]

    def test_publisher_label_comes_from_the_allowlist(self) -> None:
        headline = self._fetch("fxstreet-rss", "Yen slides as BOJ holds")

        assert headline.source == "FXStreet"  # type: ignore[attr-defined]
        assert headline.symbols == ["USD_JPY"]  # type: ignore[attr-defined]

    def test_official_feed_default_tags_its_currency(self) -> None:
        headline = self._fetch("boe-news-rss", "Minutes of the latest meeting")

        assert headline.source == "Bank of England"  # type: ignore[attr-defined]
        assert headline.symbols == ["GBP_USD"]  # type: ignore[attr-defined]

    def test_currency_signal_beats_the_source_default(self) -> None:
        headline = self._fetch(
            "fed-press-rss", "Statement on international euro liquidity"
        )

        assert headline.symbols == ["EUR_USD"]  # type: ignore[attr-defined]
