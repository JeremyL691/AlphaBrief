"""M14-W03: News & Sentiment workspace.

Covers AC-M14-W03-02: News & Sentiment exposes source provenance, age,
deduplication, entity mapping, disagreement, macro events, degradation,
and injection-scan status without reproducing unlicensed full text.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from alphabrief_api.dashboard.workspaces import build_news_sentiment_view

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


def _headlines() -> list[dict[str, object]]:
    return [
        {
            "headline_id": "h1",
            "source": "source-a",
            "published_at": (NOW - timedelta(hours=2)).isoformat(),
            "content_hash": "abc123",
            "summary": "Short bounded summary.",
            "symbols": ["EUR_USD"],
            "dedup_verdict": "canonical",
            "entity_links": ["EUR_USD:1.0"],
        },
        {
            "headline_id": "h2",
            "source": "source-b",
            "published_at": (NOW - timedelta(minutes=10)).isoformat(),
            "content_hash": "def456",
            "summary": "Another bounded summary.",
            "symbols": ["EUR_USD", "USD"],
            "dedup_verdict": "duplicate_of:h1",
            "entity_links": ["EUR_USD:1.0", "USD:0.8"],
        },
    ]


class TestNewsProvenanceAndMetadata:
    def test_exposes_provenance_age_and_dedup(self) -> None:
        view = build_news_sentiment_view(
            headlines=_headlines(), now=NOW
        )
        assert len(view.news) == 2
        by_id = {row.headline_id: row for row in view.news}
        assert by_id["h1"].source == "source-a"
        assert by_id["h1"].age_seconds == 2 * 3600
        assert by_id["h2"].age_seconds == 600
        assert by_id["h2"].dedup_verdict == "duplicate_of:h1"
        assert by_id["h1"].content_hash == "abc123"

    def test_entity_mapping_is_exposed(self) -> None:
        view = build_news_sentiment_view(headlines=_headlines(), now=NOW)
        by_id = {row.headline_id: row for row in view.news}
        assert by_id["h2"].entity_links == ("EUR_USD:1.0", "USD:0.8")

    def test_never_reproduces_full_text(self) -> None:
        view = build_news_sentiment_view(
            headlines=[{**_headlines()[0], "full_text": "UNLICENSED LONG BODY"}],
            now=NOW,
        )
        serialized = view.model_dump_json()
        assert "UNLICENSED LONG BODY" not in serialized
        assert "full_text" not in serialized
        # Only the bounded summary survives.
        assert "Short bounded summary." in serialized

    def test_age_is_clamped_and_deterministic(self) -> None:
        first = build_news_sentiment_view(headlines=_headlines(), now=NOW)
        second = build_news_sentiment_view(headlines=_headlines(), now=NOW)
        assert first.model_dump() == second.model_dump()
        assert all(
            row.age_seconds is not None and row.age_seconds >= 0
            for row in first.news
        )


class TestSentimentAndMacro:
    def test_disagreement_and_sample_counts_are_exposed(self) -> None:
        view = build_news_sentiment_view(
            headlines=_headlines(),
            sentiment_aggregates=[
                {
                    "scope": "EUR_USD",
                    "direction": "bullish",
                    "intensity": "0.6",
                    "disagreement": "0.4",
                    "sample_count": 12,
                }
            ],
            now=NOW,
        )
        assert view.sentiment[0].scope == "EUR_USD"
        assert view.sentiment[0].direction == "bullish"
        assert view.sentiment[0].disagreement == "0.4"
        assert view.sentiment[0].sample_count == 12

    def test_macro_events_carry_importance_fields(self) -> None:
        view = build_news_sentiment_view(
            headlines=_headlines(),
            macro_events=[
                {
                    "release_time": "2026-08-14T12:30:00+00:00",
                    "indicator": "CPI",
                    "importance": "high",
                    "actual": "3.1",
                    "forecast": "3.0",
                    "full_payload": "ignored",
                }
            ],
            now=NOW,
        )
        event = view.macro_events[0]
        assert event["importance"] == "high"
        assert "full_payload" not in event

    def test_degradation_and_injection_scan_status(self) -> None:
        view = build_news_sentiment_view(
            headlines=_headlines(),
            degradation="degraded: critical source stale",
            injection_scan="clean",
            now=NOW,
        )
        assert view.degradation == "degraded: critical source stale"
        assert view.injection_scan == "clean"
