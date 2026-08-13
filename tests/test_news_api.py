"""M09-W07: news API fixture queries (deterministic, no network).

The news API surfaces stored headlines from the fixture store; the
fetch endpoint uses the deterministic mock provider.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alphabrief_api.main import create_app
from alphabrief_api.routes.news import _clear_store
from alphabrief_news.types import NewsHeadline
from fastapi.testclient import TestClient

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _headline() -> NewsHeadline:
    return NewsHeadline(
        headline_id="h-1",
        published_at=NOW,
        symbols=["EUR_USD"],
        category="macro",
        source="fixture-news",
        title="ECB holds rates steady",
        summary="The European Central Bank left rates unchanged.",
        url="https://news.example.com/ecb",
        sentiment="neutral",
        data_version="news-v1",
    )


@pytest.fixture(autouse=True)
def _isolated_news(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    _clear_store()
    yield
    _clear_store()


def test_headlines_list_returns_stored_headlines() -> None:
    from alphabrief_api.routes.news import _get_store

    store = _get_store()
    store.insert_headlines([_headline()])

    client = TestClient(create_app())
    response = client.get("/api/v1/news/headlines")
    assert response.status_code == 200
    body = response.json()
    assert len(body["headlines"]) == 1
    headline = body["headlines"][0]
    assert headline["headline_id"] == "h-1"
    assert headline["title"] == "ECB holds rates steady"


def test_headline_get_returns_unknown_as_404() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/news/headlines/missing")
    assert response.status_code == 404
