"""Tests for store-backed AI trading market snapshots."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

from alphabrief_core import Bar
from alphabrief_news import NewsHeadline, SentimentLabel
from alphabrief_trader import StoredMarketSnapshotBuilder


def _bar(
    *,
    symbol: str,
    timestamp: datetime,
    close: str,
    volume: str = "1000",
) -> Bar:
    price = Decimal(close)
    return Bar(
        symbol=symbol,
        timestamp=timestamp,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal(volume),
        source="test",
        data_version="bars-v1",
    )


def _headline(
    *,
    headline_id: str,
    published_at: datetime,
    title: str,
    sentiment: str | None = None,
) -> NewsHeadline:
    return NewsHeadline(
        headline_id=headline_id,
        published_at=published_at,
        symbols=["SPY"],
        category="macro",
        source="rss",
        title=title,
        summary="",
        sentiment=cast("SentimentLabel | None", sentiment),
        data_version="news-v1",
    )


class TestStoredMarketSnapshotBuilder:
    def test_builds_snapshot_from_latest_bars_and_recent_headlines(self) -> None:
        now = datetime(2026, 6, 30, 14, 0, tzinfo=UTC)
        bars = [
            _bar(symbol="SPY", timestamp=now - timedelta(days=1), close="100"),
            _bar(symbol="SPY", timestamp=now, close="105", volume="1234"),
        ]
        headlines = [
            _headline(
                headline_id="h1",
                published_at=now - timedelta(hours=1),
                title="SPY rallies on strong growth",
            )
        ]

        builder = StoredMarketSnapshotBuilder(
            bar_loader=lambda symbol: bars if symbol == "SPY" else [],
            headline_loader=lambda symbol, start, end, limit: headlines
            if symbol == "SPY"
            else [],
            clock=lambda: now,
        )

        snapshot = builder.build("spy")

        assert snapshot is not None
        assert snapshot.symbol == "SPY"
        assert snapshot.reference_price == Decimal("105")
        assert snapshot.recent_return_pct == Decimal("5.00")
        assert snapshot.recent_volume == Decimal("1234")
        assert snapshot.data_version == "stored-snapshot-v1;bars=bars-v1;news=news-v1"
        assert snapshot.news_context is not None
        assert "positive=1" in snapshot.news_context
        assert "[positive] rss: SPY rallies on strong growth" in snapshot.news_context

    def test_returns_none_without_price_source(self) -> None:
        now = datetime(2026, 6, 30, 14, 0, tzinfo=UTC)
        builder = StoredMarketSnapshotBuilder(
            bar_loader=lambda symbol: [],
            headline_loader=lambda symbol, start, end, limit: [],
            clock=lambda: now,
        )

        assert builder.build("SPY") is None

    def test_reference_price_override_allows_missing_bars(self) -> None:
        now = datetime(2026, 6, 30, 14, 0, tzinfo=UTC)
        builder = StoredMarketSnapshotBuilder(
            bar_loader=lambda symbol: [],
            headline_loader=lambda symbol, start, end, limit: [],
            clock=lambda: now,
        )

        snapshot = builder.build(
            "SPY",
            reference_price_override=Decimal("101.25"),
        )

        assert snapshot is not None
        assert snapshot.reference_price == Decimal("101.25")
        assert snapshot.recent_return_pct is None
        assert snapshot.recent_volume is None
        assert snapshot.news_context == "No recent headlines found for SPY in last 24h."
