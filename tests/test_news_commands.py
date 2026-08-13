"""M09-W07: news CLI fixture queries (deterministic, no network)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alphabrief_api.routes.news import _clear_store
from alphabrief_news.types import NewsHeadline
from typer.testing import CliRunner

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


def test_cli_news_list_returns_stored_headlines(tmp_path: Path) -> None:
    from alphabrief_api.db import NewsStore
    from alphabrief_cli.news_commands import news_app

    store = NewsStore()
    try:
        store.insert_headlines([_headline()])
    finally:
        store.close()

    runner = CliRunner()
    result = runner.invoke(news_app, ["list"])
    assert result.exit_code == 0, result.output
    assert "fixture-news" in result.stdout
    assert "ECB holds rates steady" in result.stdout
    assert "EUR_USD" in result.stdout
