"""M03-W02: content facts are append-only and UTC stamped.

News headlines are immutable content facts: re-ingesting the same
headline id is a no-op instead of an overwrite, and every stored row
keeps its UTC published timestamp and data version.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from alphabrief_news.types import NewsHeadline


def _headline(headline_id: str = "h-1", **overrides: object) -> NewsHeadline:
    payload: dict[str, object] = {
        "headline_id": headline_id,
        "published_at": datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        "symbols": ["EUR_USD"],
        "category": "other",
        "source": "test",
        "title": "headline title",
        "summary": "summary",
        "url": "https://example.com/news/1",
        "sentiment": None,
        "data_version": "v1",
    }
    payload.update(overrides)
    return NewsHeadline.model_validate(payload)


def test_headline_reingestion_is_append_only_noop(tmp_path: Path) -> None:
    """The same headline id is stored once; later versions never overwrite."""
    from alphabrief_api.db.news import NewsStore

    store = NewsStore(db_path=tmp_path / "news.db")
    try:
        store.insert_headlines([_headline()])
        store.insert_headlines([_headline(data_version="v2")])
        store.insert_headlines([_headline(data_version="v3")])

        stored = store.get_headline(headline_id="h-1")
        assert stored is not None
        # The first stored version wins; the content was never replaced.
        assert stored.data_version == "v1"
        assert stored.title == "headline title"
        assert stored.published_at.tzinfo is not None
    finally:
        store.close()


def test_distinct_headline_ids_append(tmp_path: Path) -> None:
    """Different content facts are appended, not merged."""
    from alphabrief_api.db.news import NewsStore

    store = NewsStore(db_path=tmp_path / "news.db")
    try:
        store.insert_headlines([_headline("h-1"), _headline("h-2")])
        stored = store.get_headline(headline_id="h-2")
        assert stored is not None
        assert stored.headline_id == "h-2"
    finally:
        store.close()
