"""Durable fetch health is independent of whether a source returned items."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest
from alphabrief_news.ingestion import (
    NewsFetchOutcome,
    NewsIngestionResult,
    NewsIngestionStore,
)
from alphabrief_news.pipeline import prepare_headlines
from alphabrief_news.providers import rss
from alphabrief_news.types import NewsHeadline

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


def result(
    source: str = "marketwatch-rss", *, at: datetime = NOW, key: str = "attempt-1"
) -> NewsIngestionResult:
    batch = prepare_headlines([
        NewsHeadline(
            headline_id=f"{source}-{key}", published_at=at,
            symbols=["EUR_USD"], category="macro", source="Test Publisher",
            title="Currency markets assess policy outlook", summary="",
            url=f"https://example.test/{source}/{key}", sentiment="neutral",
            data_version="test",
        )
    ], source=source, correlation_id=key, clock=lambda: at)
    assert batch.ingestion is not None
    return batch.ingestion


@pytest.fixture
def store(tmp_path: Path) -> Iterator[NewsIngestionStore]:
    value = NewsIngestionStore(tmp_path / "health.duckdb")
    try:
        yield value
    finally:
        value.close()


@pytest.mark.parametrize(
    "outcome", ["empty", "timeout", "rate_limit", "malformed", "source_failure"]
)
def test_empty_and_failed_fetches_are_persisted_without_items(
    store: NewsIngestionStore, outcome: NewsFetchOutcome
) -> None:
    evidence = NewsIngestionResult(
        source="marketwatch-rss", correlation_id="failed-fetch",
        fetched_at=NOW, fetch_outcome=outcome,
    )
    assert store.persist(evidence) == 0
    assert store.records() == []
    records = store.fetch_records()
    assert len(records) == 1
    assert records[0]["fetch_outcome"] == outcome
    assert records[0]["fetched_at"] == NOW
    assert records[0]["item_count"] == 0
    assert len(records[0]["result_hash"]) == 64
    assert store.successful_source_families(now=NOW) == frozenset()


def test_replay_is_idempotent_and_conflicting_identity_cannot_rewrite_health(
    store: NewsIngestionStore,
) -> None:
    evidence = result()
    assert store.persist(evidence) == 1
    assert store.persist(evidence) == 0
    with pytest.raises(ValueError, match="different evidence"):
        store.persist(evidence.model_copy(update={"fetch_outcome": "timeout"}))
    assert len(store.fetch_records()) == 1
    assert len(store.records()) == 1
    assert store.successful_source_families(now=NOW) == frozenset({"marketwatch"})


def test_item_failure_rolls_back_fetch_health_and_items_together(
    store: NewsIngestionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = store._persist_items

    def fail_after_items(evidence: NewsIngestionResult) -> int:
        original(evidence)
        raise RuntimeError("injected persistence interruption")

    monkeypatch.setattr(store, "_persist_items", fail_after_items)
    with pytest.raises(RuntimeError, match="interruption"):
        store.persist(result())
    assert store.fetch_records() == []
    assert store.records() == []


def test_latest_failure_supersedes_success_and_later_success_recovers(
    store: NewsIngestionStore,
) -> None:
    store.persist(result())
    store.persist(NewsIngestionResult(
        source="marketwatch-rss", correlation_id="attempt-2",
        fetched_at=NOW, fetch_outcome="timeout",
    ))
    assert store.successful_source_families(now=NOW) == frozenset()
    store.persist(result(key="attempt-3"))
    assert store.successful_source_families(now=NOW) == frozenset({"marketwatch"})


def test_stale_future_and_unregistered_sources_do_not_count(
    store: NewsIngestionStore,
) -> None:
    store.persist(result(at=NOW - timedelta(hours=6, seconds=1)))
    store.persist(result("fxstreet-rss", at=NOW + timedelta(seconds=1)))
    store.persist(result("unregistered-feed"))
    assert store.successful_source_families(now=NOW) == frozenset()


def test_multiple_feeds_in_one_family_count_once(
    store: NewsIngestionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(rss._FEED_SOURCES, "marketwatch-alt", replace(
        rss.feed_source("marketwatch-rss"), key="marketwatch-alt"
    ))
    store.persist(result())
    store.persist(result("marketwatch-alt"))
    assert store.successful_source_families(now=NOW) == frozenset({"marketwatch"})
    store.persist(result("fxstreet-rss"))
    assert store.successful_source_families(now=NOW) == frozenset({
        "marketwatch", "fxstreet"
    })


def test_old_item_records_are_preserved_without_fabricating_fetch_health(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy.duckdb"
    old = NewsIngestionStore(database)
    old.persist(result())
    old.close()
    with duckdb.connect(str(database)) as connection:
        connection.execute("DROP TABLE news_fetch_records")
    upgraded = NewsIngestionStore(database)
    try:
        assert len(upgraded.records()) == 1
        assert upgraded.fetch_records() == []
        assert upgraded.successful_source_families(now=NOW) == frozenset()
    finally:
        upgraded.close()


def test_naive_fetch_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        NewsIngestionResult(
            source="marketwatch-rss", correlation_id="bad-time",
            fetched_at=NOW.replace(tzinfo=None), fetch_outcome="empty",
        )
