"""Build AI trading market snapshots from local research stores.

This module is deliberately provider-neutral. It does not open DuckDB,
call HTTP providers, or place orders. Callers inject small loader
functions for market bars and headlines, and the builder turns those
auditable local records into the compact ``MarketSnapshot`` shape used
by the AI Trading Committee.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from alphabrief_core import Bar
from alphabrief_news import NewsHeadline
from alphabrief_news.sentiment import RuleBasedSentimentAnalyzer, sentiment_summary

from alphabrief_trader.schemas import MarketSnapshot

BarLoader = Callable[[str], Sequence[Bar]]
HeadlineLoader = Callable[[str, datetime, datetime, int], Sequence[NewsHeadline]]


class StoredMarketSnapshotBuilder:
    """Build ``MarketSnapshot`` objects from stored bars and headlines."""

    def __init__(
        self,
        *,
        bar_loader: BarLoader,
        headline_loader: HeadlineLoader,
        clock: Callable[[], datetime] | None = None,
        news_window: timedelta = timedelta(hours=24),
        max_headlines: int = 8,
        sentiment_analyzer: RuleBasedSentimentAnalyzer | None = None,
    ) -> None:
        if max_headlines < 1:
            raise ValueError("max_headlines must be positive")
        if news_window <= timedelta(0):
            raise ValueError("news_window must be positive")
        self._bar_loader = bar_loader
        self._headline_loader = headline_loader
        self._clock = clock or (lambda: datetime.now(UTC))
        self._news_window = news_window
        self._max_headlines = max_headlines
        self._sentiment = sentiment_analyzer or RuleBasedSentimentAnalyzer()

    def build(
        self,
        symbol: str,
        *,
        reference_price_override: Decimal | None = None,
    ) -> MarketSnapshot | None:
        """Return a snapshot for *symbol*, or ``None`` when price is unknown."""

        normalized = symbol.strip().upper()
        if not normalized:
            return None

        bars = sorted(self._bar_loader(normalized), key=lambda bar: bar.timestamp)
        latest_bar = bars[-1] if bars else None
        if reference_price_override is not None:
            reference_price = reference_price_override
        elif latest_bar is not None:
            reference_price = latest_bar.close
        else:
            return None

        if reference_price <= 0:
            return None

        captured_at = self._ensure_utc(self._clock())
        headlines = self._load_headlines(normalized, captured_at)

        return MarketSnapshot(
            symbol=normalized,
            reference_price=reference_price,
            recent_return_pct=self._recent_return_pct(bars),
            recent_volume=latest_bar.volume if latest_bar is not None else None,
            news_context=self._format_news_context(
                symbol=normalized,
                headlines=headlines,
            ),
            macro_context=None,
            data_version=self._data_version(bars=bars, headlines=headlines),
            captured_at=captured_at,
        )

    def _load_headlines(
        self,
        symbol: str,
        captured_at: datetime,
    ) -> list[NewsHeadline]:
        start = captured_at - self._news_window
        raw = list(
            self._headline_loader(
                symbol,
                start,
                captured_at,
                self._max_headlines,
            )
        )
        annotated: list[NewsHeadline] = []
        for headline in raw[: self._max_headlines]:
            if headline.sentiment is None:
                annotated.append(self._sentiment.annotate(headline))
            else:
                annotated.append(headline)
        return sorted(
            annotated,
            key=lambda headline: headline.published_at,
            reverse=True,
        )

    @staticmethod
    def _recent_return_pct(bars: Sequence[Bar]) -> Decimal | None:
        if len(bars) < 2:
            return None
        previous = bars[-2].close
        latest = bars[-1].close
        if previous <= 0:
            return None
        return ((latest - previous) / previous) * Decimal("100")

    def _format_news_context(
        self,
        *,
        symbol: str,
        headlines: Sequence[NewsHeadline],
    ) -> str:
        if not headlines:
            hours = int(self._news_window.total_seconds() // 3600)
            return f"No recent headlines found for {symbol} in last {hours}h."

        lines = [
            f"Recent {symbol} news sentiment: {sentiment_summary(headlines)}."
        ]
        for headline in headlines:
            label = headline.sentiment or "unknown"
            published = self._ensure_utc(headline.published_at).isoformat()
            lines.append(
                f"- {published} [{label}] {headline.source}: {headline.title}"
            )
        return "\n".join(lines)

    @staticmethod
    def _data_version(
        *,
        bars: Sequence[Bar],
        headlines: Sequence[NewsHeadline],
    ) -> str:
        bar_version = bars[-1].data_version if bars else "none"
        news_versions = sorted({headline.data_version for headline in headlines})
        news_version = ",".join(news_versions) if news_versions else "none"
        return f"stored-snapshot-v1;bars={bar_version};news={news_version}"

    @staticmethod
    def _ensure_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


__all__ = [
    "BarLoader",
    "HeadlineLoader",
    "StoredMarketSnapshotBuilder",
]
