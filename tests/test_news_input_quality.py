"""News quality uses frozen production facts, not configured feed counts."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_api.db import MarketDataStore, NewsStore
from alphabrief_cli.cycle_commands import _snapshot_loader
from alphabrief_core import Bar
from alphabrief_news.ingestion import NewsIngestionStore
from alphabrief_news.types import NewsHeadline
from alphabrief_trader.data_quality import evaluate_snapshot_quality
from alphabrief_trader.schemas import MarketSnapshot, NewsInputEvidence

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


def snapshot(evidence: NewsInputEvidence) -> MarketSnapshot:
    return MarketSnapshot(
        symbol="EUR_USD", reference_price=Decimal("1.1"), captured_at=NOW,
        news_evidence=evidence, news_context="Related news is untrusted input.",
    )


def good_news() -> NewsInputEvidence:
    return NewsInputEvidence(
        family_fetched_at={"marketwatch": NOW, "fxstreet": NOW},
        related_published_at={"news-1": NOW - timedelta(hours=1)},
    )


@pytest.mark.parametrize("kind,reason", [
    ("one_family", "news_successful_families_below_2"),
    ("expired_source", "news_successful_families_below_2"),
    ("future_source", "news_successful_families_below_2"),
    ("unknown_source", "news_successful_families_below_2"),
    ("missing_related", "related_news_missing"),
    ("stale_related", "related_news_stale_21601s"),
    ("future_related", "related_news_in_the_future"),
])
def test_bad_news_is_rejected(kind: str, reason: str) -> None:
    families = {"marketwatch": NOW, "fxstreet": NOW}
    related = {"news-1": NOW}
    if kind == "one_family":
        families.pop("fxstreet")
    elif kind == "expired_source":
        families["fxstreet"] = NOW - timedelta(hours=6, seconds=1)
    elif kind == "future_source":
        families["fxstreet"] = NOW + timedelta(seconds=1)
    elif kind == "unknown_source":
        families = {"marketwatch": NOW, "invented": NOW}
    elif kind == "missing_related":
        related = {}
    elif kind == "stale_related":
        related["news-1"] = NOW - timedelta(hours=6, seconds=1)
    elif kind == "future_related":
        related["news-1"] = NOW + timedelta(seconds=1)
    evidence = NewsInputEvidence(
        family_fetched_at=families, related_published_at=related
    )
    verdict = evaluate_snapshot_quality(snapshot(evidence), now=NOW)
    assert not verdict.passed
    assert verdict.reasons == (reason,)


def test_news_at_the_six_hour_limit_passes_but_expires_on_recheck() -> None:
    evidence = NewsInputEvidence(
        family_fetched_at={
            family: NOW - timedelta(hours=6) for family in ("marketwatch", "fxstreet")
        }, related_published_at={"news-1": NOW - timedelta(hours=6)},
    )
    assert evaluate_snapshot_quality(snapshot(evidence), now=NOW).passed
    later = evaluate_snapshot_quality(
        snapshot(evidence), now=NOW + timedelta(seconds=1)
    )
    assert later.reasons == (
        "news_successful_families_below_2", "related_news_stale_21601s"
    )


def test_production_loader_uses_only_related_24_hour_bounded_headlines(
    tmp_path: Path,
) -> None:
    from datetime import datetime as real_datetime

    now = real_datetime.now(UTC)
    database = tmp_path / "inputs.duckdb"
    market, news = MarketDataStore(database), NewsStore(database)
    health = NewsIngestionStore(database)
    try:
        market.insert_bars([Bar(
            symbol="EUR_USD", timestamp=now - timedelta(hours=1),
            open=Decimal("1.1"), high=Decimal("1.2"), low=Decimal("1.0"),
            close=Decimal("1.1"), volume=Decimal("100"),
            source="oanda_practice", data_version="test:M:H1",
        )], source="oanda_practice", data_version="test:M:H1")
        headlines = [NewsHeadline(
            headline_id=f"news-{i}", published_at=now - timedelta(minutes=i + 1),
            symbols=["EUR_USD"], category="macro", source="Test Publisher",
            title=f"Related currency outlook {i}", summary="", sentiment="neutral",
            data_version="test",
        ) for i in range(25)]
        headlines += [headlines[0].model_copy(update={
            "headline_id": "unrelated", "symbols": ["USD_JPY"],
        }), headlines[0].model_copy(update={
            "headline_id": "expired", "published_at": now - timedelta(hours=25),
        })]
        news.insert_headlines(headlines)
        loaded = _snapshot_loader(market, news, health)("EUR_USD")
        assert loaded is not None and loaded.news_evidence is not None
        assert list(loaded.news_evidence.related_published_at) == [
            f"news-{i}" for i in range(20)
        ]
        assert loaded.news_context is not None
        for i in range(20):
            assert f"Related currency outlook {i}" in loaded.news_context
        assert "outlook 24" not in loaded.news_context
        assert loaded.news_evidence.family_fetched_at == {}
        assert not evaluate_snapshot_quality(loaded, now=now).passed
    finally:
        health.close()
        news.close()
        market.close()


def test_news_evidence_rejects_naive_times_and_over_20_inputs() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        NewsInputEvidence(family_fetched_at={"fxstreet": NOW.replace(tzinfo=None)})
    with pytest.raises(ValueError):
        NewsInputEvidence(related_published_at={str(i): NOW for i in range(21)})


def test_source_health_times_are_part_of_the_input_fingerprint() -> None:
    from alphabrief_trader.daily_cycle import _snapshot_fingerprint

    original = snapshot(good_news())
    changed = snapshot(NewsInputEvidence(
        family_fetched_at={"marketwatch": NOW, "fxstreet": NOW - timedelta(seconds=1)},
        related_published_at=good_news().related_published_at,
    ))
    assert evaluate_snapshot_quality(original, now=NOW).passed
    assert _snapshot_fingerprint({"EUR_USD": original}) != _snapshot_fingerprint({
        "EUR_USD": changed
    })
