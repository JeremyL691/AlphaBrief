"""Social sentiment news provider (Phase 11 stub).

This provider currently returns a small deterministic mock set of
sentiment-tagged :class:`NewsHeadline` objects. The class implements
the :class:`NewsProvider` protocol and is wired into the CLI/API
``source=sentiment`` branch.

The provider is intentionally a stub: AlphaBrief does not have a free
real-time social-sentiment feed that can be safely used at scale. A
future round may swap the body of :meth:`fetch_headlines` for a real
HTTP call to a stable public endpoint.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

from alphabrief_news.types import (
    NewsFetchQuery,
    NewsHeadline,
    SentimentLabel,
)


class SocialSentimentNewsProvider:
    """Stub provider that emits a small deterministic sentiment feed."""

    provider_name = "social-sentiment"

    def __init__(self) -> None:
        pass

    def fetch_headlines(self, query: NewsFetchQuery) -> list[NewsHeadline]:
        """Return a deterministic set of sentiment-tagged headlines."""
        if not query.symbols:
            return []

        now = datetime.now(UTC).replace(microsecond=0)
        base_id = "social"
        headlines: list[NewsHeadline] = []
        for index, symbol in enumerate(query.symbols):
            label: SentimentLabel = (
                "positive" if index % 3 == 0
                else "negative" if index % 3 == 1
                else "neutral"
            )
            sentiment = cast(str, label)
            timestamp = now - timedelta(hours=index)
            headlines.append(
                NewsHeadline(
                    headline_id=f"{base_id}:{symbol}:{index}",
                    published_at=timestamp,
                    symbols=[symbol],
                    category="other",
                    source="social-sentiment-stub",
                    title=f"Social sentiment for {symbol} is {sentiment}",
                    summary=(
                        f"Stub social sentiment provider: "
                        f"{sentiment} on {symbol}."
                    ),
                    url=None,
                    sentiment=label,
                    data_version="social-v1",
                )
            )
        return headlines[: query.limit]


__all__ = ["SocialSentimentNewsProvider"]
