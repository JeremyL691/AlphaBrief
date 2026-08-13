"""M09-W01: news ingestion contracts and distinct durable outcomes.

- fixture ingestion persists source, canonical URL, published and
  fetched UTC times, language, content hash, summary, fetch outcome, and
  correlation ID for every attempted item (AC-M09-W01-01);
- success, empty response, timeout, rate-limit, malformed response, and
  source failure produce distinct durable outcomes without fabricated
  headlines (AC-M09-W01-02);
- metadata-only sources never persist licensed full text and retain
  only permitted metadata and bounded summaries (AC-M09-W01-03).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alphabrief_news.ingestion import (
    NewsIngestionService,
    NewsIngestionStore,
    SourceLicensePolicy,
)
from alphabrief_news.providers.base import (
    NewsProvider,
    NewsProviderError,
)
from alphabrief_news.providers.mock import MockNewsProvider
from alphabrief_news.types import NewsFetchQuery, NewsHeadline

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
SOURCE = "fixture-news"


def _headline(**overrides: object) -> NewsHeadline:
    payload: dict[str, object] = {
        "headline_id": "h-1",
        "published_at": NOW,
        "symbols": ["EUR_USD"],
        "category": "macro",
        "source": SOURCE,
        "title": "ECB holds rates steady",
        "summary": "The European Central Bank left its key rate unchanged.",
        "url": "https://news.example.com/ecb-holds?utm_source=rss",
        "sentiment": "neutral",
        "data_version": "news-v1",
    }
    payload.update(overrides)
    return NewsHeadline.model_validate(payload)


def _query() -> NewsFetchQuery:
    return NewsFetchQuery(
        symbols=["EUR_USD"],
        start=NOW,
        end=NOW + __import__("datetime").timedelta(days=1),
        limit=10,
    )


class _FailingProvider(NewsProvider):
    """A provider that raises one classified error code."""

    def __init__(self, code: str) -> None:
        self._code = code

    def fetch_headlines(self, query: NewsFetchQuery) -> list[NewsHeadline]:
        raise NewsProviderError(code=self._code, message=f"boom {self._code}")


def test_success_ingestion_persists_every_required_field(
    tmp_path: Path,
) -> None:
    service = NewsIngestionService(clock=lambda: NOW)
    result = service.fetch_and_ingest(
        MockNewsProvider(seed_headlines=[_headline()]),
        _query(),
        source=SOURCE,
        correlation_id="corr-1",
    )
    assert result.fetch_outcome == "success"
    assert len(result.items) == 1
    item = result.items[0]
    assert item.source == SOURCE
    assert item.canonical_url == "https://news.example.com/ecb-holds?utm_source=rss"
    assert item.published_at == NOW
    assert item.fetched_at == NOW
    assert item.language == "en"
    assert len(item.content_hash) == 64  # sha256 hexdigest
    assert item.summary == "The European Central Bank left its key rate unchanged."
    assert item.fetch_outcome == "success"
    assert item.correlation_id == "corr-1"
    assert item.metadata_only is False

    store = NewsIngestionStore(db_path=tmp_path / "news.db")
    try:
        assert store.persist(result) == 1
        records = store.records(source=SOURCE)
        assert len(records) == 1
        record = records[0]
        assert record["item_id"] == f"{SOURCE}:h-1"
        assert record["canonical_url"] == item.canonical_url
        # TIMESTAMPTZ round-trips the same instant (offset may render
        # in the session timezone).
        assert (
            datetime.fromisoformat(record["published_at"])
            == item.published_at
        )
        assert (
            datetime.fromisoformat(record["fetched_at"])
            == item.fetched_at
        )
        assert record["language"] == "en"
        assert record["content_hash"] == item.content_hash
        assert record["summary"] == item.summary
        assert record["fetch_outcome"] == "success"
        assert record["correlation_id"] == "corr-1"
    finally:
        store.close()


@pytest.mark.parametrize(
    ("provider", "expected_outcome"),
    [
        (MockNewsProvider(seed_headlines=[]), "empty"),
        (_FailingProvider("network_error"), "timeout"),
        (_FailingProvider("http_error"), "timeout"),
        (_FailingProvider("rate_limited"), "rate_limit"),
        (_FailingProvider("parse_error"), "malformed"),
        (_FailingProvider("invalid_config"), "malformed"),
        (_FailingProvider("no_api_key"), "source_failure"),
    ],
    ids=[
        "empty",
        "timeout-network",
        "timeout-http",
        "rate-limit",
        "malformed-parse",
        "malformed-config",
        "source-failure",
    ],
)
def test_distinct_outcomes_without_fabricated_headlines(
    tmp_path: Path, provider: NewsProvider, expected_outcome: str
) -> None:
    service = NewsIngestionService(clock=lambda: NOW)
    result = service.fetch_and_ingest(
        provider,
        _query(),
        source=SOURCE,
        correlation_id="corr-2",
    )
    assert result.fetch_outcome == expected_outcome
    # A failure never fabricates headlines: zero items.
    assert result.items == ()
    store = NewsIngestionStore(db_path=tmp_path / "news.db")
    try:
        store.persist(result)
        assert store.records(source=SOURCE) == []
    finally:
        store.close()


def test_unexpected_provider_failure_is_classified_timeout() -> None:
    class _BoomProvider(NewsProvider):
        def fetch_headlines(self, query: NewsFetchQuery) -> list[NewsHeadline]:
            raise TimeoutError("provider blew up")

    service = NewsIngestionService(clock=lambda: NOW)
    result = service.fetch_and_ingest(
        _BoomProvider(),
        _query(),
        source=SOURCE,
        correlation_id="corr-3",
    )
    assert result.fetch_outcome == "timeout"
    assert result.items == ()


def test_metadata_only_source_never_persists_full_text(tmp_path: Path) -> None:
    """REQ-NEWS-008: metadata-only sources retain metadata + a bounded
    summary; licensed full text is never stored."""
    service = NewsIngestionService(clock=lambda: NOW)
    policy = SourceLicensePolicy(
        metadata_only=True, max_summary_chars=20
    )
    result = service.fetch_and_ingest(
        MockNewsProvider(seed_headlines=[_headline()]),
        _query(),
        source="licensed-news",
        correlation_id="corr-4",
        license_policy=policy,
    )
    item = result.items[0]
    assert item.metadata_only is True
    # The summary is bounded to 20 characters.
    assert len(item.summary) <= 20
    assert item.summary == "The European Central"
    # No full-text field exists anywhere on the persisted record.
    assert "full_text" not in item.model_fields
    assert "body" not in item.model_fields
    store = NewsIngestionStore(db_path=tmp_path / "news.db")
    try:
        store.persist(result)
        records = store.records(source="licensed-news")
        assert len(records) == 1
        assert "full_text" not in records[0]
        assert records[0]["metadata_only"] is True
        assert len(records[0]["summary"]) <= 20
    finally:
        store.close()


def test_content_hash_is_deterministic() -> None:
    service = NewsIngestionService(clock=lambda: NOW)
    first = service.fetch_and_ingest(
        MockNewsProvider(seed_headlines=[_headline()]),
        _query(),
        source=SOURCE,
        correlation_id="corr-5",
    )
    second = service.fetch_and_ingest(
        MockNewsProvider(seed_headlines=[_headline()]),
        _query(),
        source=SOURCE,
        correlation_id="corr-6",
    )
    assert first.items[0].content_hash == second.items[0].content_hash
    different = _headline(title="ECB cuts rates")
    third = service.fetch_and_ingest(
        MockNewsProvider(seed_headlines=[different]),
        _query(),
        source=SOURCE,
        correlation_id="corr-7",
    )
    assert third.items[0].content_hash != first.items[0].content_hash


def test_duplicate_persist_is_idempotent(tmp_path: Path) -> None:
    service = NewsIngestionService(clock=lambda: NOW)
    result = service.fetch_and_ingest(
        MockNewsProvider(seed_headlines=[_headline()]),
        _query(),
        source=SOURCE,
        correlation_id="corr-8",
    )
    store = NewsIngestionStore(db_path=tmp_path / "news.db")
    try:
        assert store.persist(result) == 1
        assert store.persist(result) == 0  # idempotent replay
        assert len(store.records(source=SOURCE)) == 1
    finally:
        store.close()
