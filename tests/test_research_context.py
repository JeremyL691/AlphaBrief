"""Tests for the research context builder."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from alphabrief_news import MacroIndicator, NewsHeadline
from alphabrief_research import UNTRUSTED_BANNER, ResearchContextBuilder

START = datetime(2026, 6, 14, 0, 0, tzinfo=UTC)
END = datetime(2026, 6, 15, 0, 0, tzinfo=UTC)


def _headline(
    headline_id: str,
    title: str,
    *,
    sentiment: str | None = None,
    symbols: list[str] | None = None,
) -> NewsHeadline:
    return NewsHeadline(
        headline_id=headline_id,
        published_at=START.replace(hour=9),
        symbols=symbols or ["AAPL"],
        category="earnings",
        source="test",
        title=title,
        sentiment=sentiment,  # type: ignore[arg-type]
    )


def _indicator(
    indicator_id: str,
    value: str,
    *,
    period: str = "2026-05",
) -> MacroIndicator:
    return MacroIndicator(
        indicator_id=indicator_id,
        name=indicator_id,
        country="US",
        released_at=START,
        period=period,
        value=Decimal(value),
        unit="index",
        source="test",
    )


def test_builder_without_loaders_returns_empty_blocks() -> None:
    builder = ResearchContextBuilder()

    news_text = builder.build_news_context(["AAPL"], START, END, limit=5)
    macro_text = builder.build_macro_context(["CPIAUCSL"], START, END)

    assert UNTRUSTED_BANNER in news_text
    assert "Headlines loaded: 0" in news_text
    assert "Sentiment: no sentiment information" in news_text
    assert UNTRUSTED_BANNER in macro_text
    assert "Indicators loaded: 0" in macro_text


def test_builder_renders_news_from_preloaded_list() -> None:
    builder = ResearchContextBuilder()
    headlines = [
        _headline("h1", "AAPL beats estimates", sentiment="positive"),
        _headline("h2", "AAPL faces lawsuit", sentiment="negative"),
        _headline("h3", "AAPL holds annual meeting", sentiment="neutral"),
        _headline("h4", "AAPL analyst day", sentiment=None),
    ]

    text = builder.render_news_from_headlines(headlines, symbols=["AAPL"])

    assert UNTRUSTED_BANNER in text
    assert "Headlines loaded: 4" in text
    assert "positive=1" in text
    assert "negative=1" in text
    assert "neutral=1" in text
    assert "unknown=1" in text
    assert "AAPL beats estimates" in text


def test_builder_renders_macro_from_preloaded_list() -> None:
    builder = ResearchContextBuilder()
    indicators = [
        _indicator("CPIAUCSL", "307.5"),
        _indicator("UNRATE", "3.7"),
    ]

    text = builder.render_macro_from_indicators(
        indicators, requested=["CPIAUCSL", "UNRATE"]
    )

    assert UNTRUSTED_BANNER in text
    assert "Indicators loaded: 2" in text
    assert "CPIAUCSL" in text
    assert "307.5" in text
    assert "UNRATE" in text
    assert "3.7" in text


def test_builder_uses_news_loader() -> None:
    captured: dict[str, object] = {}

    def loader(
        symbols: list[str],
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[NewsHeadline]:
        captured["symbols"] = symbols
        captured["start"] = start
        captured["end"] = end
        captured["limit"] = limit
        return [_headline("h1", "AAPL rises", sentiment="positive")]

    builder = ResearchContextBuilder(news_loader=loader)
    text = builder.build_news_context(["AAPL"], START, END, limit=3)

    assert captured == {
        "symbols": ["AAPL"],
        "start": START,
        "end": END,
        "limit": 3,
    }
    assert "Headlines loaded: 1" in text
    assert "AAPL rises" in text


def test_builder_uses_macro_loader() -> None:
    def loader(
        indicators: list[str],
        start: datetime,
        end: datetime,
    ) -> list[MacroIndicator]:
        return [_indicator(indicators[0], "100.0")]

    builder = ResearchContextBuilder(macro_loader=loader)
    text = builder.build_macro_context(["CPIAUCSL"], START, END)

    assert "Indicators loaded: 1" in text
    assert "CPIAUCSL" in text


def test_builder_for_symbol_combines_both() -> None:
    def news_loader(
        symbols: list[str], start: datetime, end: datetime, limit: int,
    ) -> list[NewsHeadline]:
        return [_headline("h1", "AAPL rises", sentiment="positive")]

    def macro_loader(
        indicators: list[str],
        start: datetime,
        end: datetime,
    ) -> list[MacroIndicator]:
        return [_indicator("CPIAUCSL", "307.0")]

    builder = ResearchContextBuilder(
        news_loader=news_loader,
        macro_loader=macro_loader,
    )

    out = builder.build_for_symbol("AAPL", START, END, macro_indicators=["CPIAUCSL"])

    assert "news_context" in out
    assert "macro_context" in out
    assert "Headlines loaded: 1" in out["news_context"]
    assert "Indicators loaded: 1" in out["macro_context"]


def test_builder_handles_empty_inputs() -> None:
    builder = ResearchContextBuilder()

    news_text = builder.render_news_from_headlines([], symbols=[])
    macro_text = builder.render_macro_from_indicators([], requested=[])

    assert "Headlines loaded: 0" in news_text
    assert "Indicators loaded: 0" in macro_text
    assert UNTRUSTED_BANNER in news_text
    assert UNTRUSTED_BANNER in macro_text


def test_builder_marks_untrusted_data() -> None:
    builder = ResearchContextBuilder()
    news_text = builder.build_news_context([], START, END)
    macro_text = builder.build_macro_context([], START, END)

    assert UNTRUSTED_BANNER in news_text
    assert UNTRUSTED_BANNER in macro_text
    assert "untrusted external data" in news_text
    assert "untrusted external data" in macro_text


def test_builder_truncates_long_headline_lists() -> None:
    builder = ResearchContextBuilder()
    headlines = [
        _headline(f"h{i}", f"Headline #{i}", sentiment="neutral")
        for i in range(50)
    ]

    text = builder.render_news_from_headlines(headlines, symbols=["AAPL"])

    assert "Headlines loaded: 50" in text
    listed = sum(1 for line in text.splitlines() if line.startswith("- ["))
    assert listed == 10
