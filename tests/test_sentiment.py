"""Tests for the rule-based sentiment analyzer."""

from __future__ import annotations

from datetime import UTC, datetime

from alphabrief_news import NewsHeadline, SentimentLabel
from alphabrief_news.sentiment import (
    RuleBasedSentimentAnalyzer,
    sentiment_summary,
)


def _headline(
    title: str,
    summary: str = "",
    sentiment: SentimentLabel | None = None,
) -> NewsHeadline:
    return NewsHeadline(
        headline_id="h1",
        published_at=datetime(2026, 6, 14, 9, 0, tzinfo=UTC),
        symbols=["AAPL"],
        category="earnings",
        source="test",
        title=title,
        summary=summary,
        sentiment=sentiment,
    )


def test_classify_text_positive() -> None:
    analyzer = RuleBasedSentimentAnalyzer()
    label = analyzer.classify_text("AAPL beats Q3 estimates, shares surge")
    assert label == "positive"


def test_classify_text_negative() -> None:
    analyzer = RuleBasedSentimentAnalyzer()
    label = analyzer.classify_text("AAPL misses estimates, shares drop on warning")
    assert label == "negative"


def test_classify_text_neutral() -> None:
    analyzer = RuleBasedSentimentAnalyzer()
    label = analyzer.classify_text("AAPL holds annual meeting")
    assert label == "neutral"


def test_classify_text_empty() -> None:
    analyzer = RuleBasedSentimentAnalyzer()
    assert analyzer.classify_text("") == "neutral"


def test_score_text_counts_positives_and_negatives() -> None:
    analyzer = RuleBasedSentimentAnalyzer()
    score = analyzer.score_text("surge drop")
    assert score == 0


def test_score_text_balanced_neutral() -> None:
    analyzer = RuleBasedSentimentAnalyzer()
    score = analyzer.score_text("surge drop")
    assert score == 0


def test_score_text_positive_only() -> None:
    analyzer = RuleBasedSentimentAnalyzer()
    score = analyzer.score_text("surge rally")
    assert score == 2


def test_classify_headline_uses_title_and_summary() -> None:
    analyzer = RuleBasedSentimentAnalyzer()
    headline = _headline(title="AAPL reports", summary="shares surge on beat")
    assert analyzer.classify_headline(headline) == "positive"


def test_classify_batch_returns_mapping() -> None:
    analyzer = RuleBasedSentimentAnalyzer()
    headlines = [
        _headline("AAPL beats", sentiment=None).model_copy(
            update={"headline_id": "h_pos"},
        ),
        _headline("AAPL misses", sentiment=None).model_copy(
            update={"headline_id": "h_neg"},
        ),
        _headline("AAPL meeting", sentiment=None).model_copy(
            update={"headline_id": "h_neu"},
        ),
    ]
    out = analyzer.classify_batch(headlines)
    assert out["h_pos"] == "positive"
    assert out["h_neg"] == "negative"
    assert out["h_neu"] == "neutral"


def test_annotate_does_not_mutate_input() -> None:
    analyzer = RuleBasedSentimentAnalyzer()
    original = _headline("AAPL beats")
    assert original.sentiment is None
    annotated = analyzer.annotate(original)
    assert annotated.sentiment == "positive"
    assert original.sentiment is None


def test_annotate_overrides_existing_label() -> None:
    analyzer = RuleBasedSentimentAnalyzer()
    original = _headline("AAPL beats", sentiment="negative")
    annotated = analyzer.annotate(original)
    assert annotated.sentiment == "positive"


def test_custom_keywords_take_effect() -> None:
    analyzer = RuleBasedSentimentAnalyzer(
        positive_keywords={"moon", "rocket"},
        negative_keywords={"fire", "smoke"},
    )
    assert analyzer.classify_text("rocket to the moon") == "positive"
    assert analyzer.classify_text("fire and smoke") == "negative"
    assert analyzer.classify_text("surge rally") == "neutral"


def test_sentiment_summary_handles_empty() -> None:
    assert sentiment_summary([]) == "no sentiment information"


def test_sentiment_summary_counts_labels() -> None:
    headlines = [
        _headline("beats", sentiment="positive"),
        _headline("surge", sentiment="positive"),
        _headline("misses", sentiment="negative"),
        _headline("meeting", sentiment="neutral"),
        _headline("unknown", sentiment=None),
    ]
    summary = sentiment_summary(headlines)
    assert "positive=2" in summary
    assert "negative=1" in summary
    assert "neutral=1" in summary
    assert "unknown=1" in summary


def test_score_text_handles_punctuation() -> None:
    analyzer = RuleBasedSentimentAnalyzer()
    assert analyzer.score_text("AAPL: surge! rally.") == 2


def test_classify_text_with_only_positive_or_negative_keywords() -> None:
    analyzer = RuleBasedSentimentAnalyzer()
    assert analyzer.classify_text("strong growth and profit") == "positive"
    assert analyzer.classify_text("losses and concern") == "negative"
