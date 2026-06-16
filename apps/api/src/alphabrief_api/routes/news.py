"""News data routes for the AlphaBrief API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from alphabrief_news.providers import (
    MockNewsProvider,
    NewsProviderError,
    RssNewsProvider,
    build_default_mock_news,
)
from alphabrief_news.types import NewsFetchQuery, NewsHeadline
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from alphabrief_api.db import NewsStore

# ---------------------------------------------------------------------------
# Persistent store
# ---------------------------------------------------------------------------

_store: NewsStore | None = None


def _get_store() -> NewsStore:
    if _store is None:
        return NewsStore()
    return _store


def _clear_store() -> None:
    global _store
    if _store is None:
        _store = NewsStore()
    _store.clear()


def _close_store() -> None:
    global _store
    if _store is not None:
        _store.close()
        _store = None


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

NewsSource = Literal["mock", "rss"]


class NewsFetchRequest(BaseModel):
    """Request body for POST /api/v1/news/fetch."""

    source: NewsSource
    symbols: list[str] = Field(min_length=1)
    start: str = Field(min_length=1)
    end: str = Field(min_length=1)
    limit: int = Field(default=100, ge=1, le=1000)
    data_version: str = Field(default="news-v1", min_length=1)


class NewsFetchResponse(BaseModel):
    """Response body for a successful news fetch."""

    headline_count: int
    time_start: str | None
    time_end: str | None


class NewsHeadlineSummary(BaseModel):
    """Summary of a stored headline."""

    headline_id: str
    published_at: str
    symbols: list[str]
    source: str
    title: str
    category: str


class NewsHeadlinesResponse(BaseModel):
    """Response body for GET /api/v1/news/headlines."""

    headlines: list[NewsHeadlineSummary]


class NewsHeadlineResponse(BaseModel):
    """Response body for GET /api/v1/news/headlines/{headline_id}."""

    headline: NewsHeadline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_iso_to_utc(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must be a valid ISO-8601 datetime: {exc}",
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _build_provider(
    source: NewsSource, symbols: list[str]
) -> MockNewsProvider | RssNewsProvider:
    if source == "mock":
        return MockNewsProvider(seed_headlines=build_default_mock_news(symbols))
    if source == "rss":
        return RssNewsProvider()
    raise HTTPException(
        status_code=422,
        detail=f"unknown news source: {source}",
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/news", tags=["news"])


@router.post("/fetch", response_model=NewsFetchResponse, status_code=201)
def fetch_news(body: NewsFetchRequest) -> NewsFetchResponse:
    """Fetch news headlines from a provider and persist them."""
    start = _parse_iso_to_utc(body.start, field_name="start")
    end = _parse_iso_to_utc(body.end, field_name="end")

    if end <= start:
        raise HTTPException(
            status_code=422,
            detail="end must be after start",
        )

    provider = _build_provider(body.source, body.symbols)
    query = NewsFetchQuery(
        symbols=body.symbols,
        start=start,
        end=end,
        limit=body.limit,
        data_version=body.data_version,
    )

    try:
        headlines = provider.fetch_headlines(query)
    except NewsProviderError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc

    if not headlines:
        raise HTTPException(
            status_code=404,
            detail="provider returned no headlines for the requested window",
        )

    store = _get_store()
    store.insert_headlines(headlines)

    timestamps = sorted(h.published_at for h in headlines)
    return NewsFetchResponse(
        headline_count=len(headlines),
        time_start=timestamps[0].astimezone(UTC).isoformat(),
        time_end=timestamps[-1].astimezone(UTC).isoformat(),
    )


@router.get("/headlines", response_model=NewsHeadlinesResponse)
def list_headlines(
    symbol: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> NewsHeadlinesResponse:
    """List stored news headlines with optional filters."""
    start_dt = _parse_iso_to_utc(start, field_name="start") if start else None
    end_dt = _parse_iso_to_utc(end, field_name="end") if end else None

    store = _get_store()
    headlines = store.list_headlines(
        symbol=symbol,
        start=start_dt,
        end=end_dt,
        limit=limit,
        offset=offset,
    )

    summaries = [
        NewsHeadlineSummary(
            headline_id=headline.headline_id,
            published_at=headline.published_at.astimezone(UTC).isoformat(),
            symbols=headline.symbols,
            source=headline.source,
            title=headline.title,
            category=headline.category,
        )
        for headline in headlines
    ]
    return NewsHeadlinesResponse(headlines=summaries)


@router.get("/headlines/{headline_id}", response_model=NewsHeadlineResponse)
def get_headline(headline_id: str) -> NewsHeadlineResponse:
    """Return a single stored headline by id."""
    store = _get_store()
    headline = store.get_headline(headline_id)
    if headline is None:
        raise HTTPException(
            status_code=404,
            detail=f"headline not found: {headline_id}",
        )
    return NewsHeadlineResponse(headline=headline)


__all__ = [
    "router",
    "_clear_store",
    "_close_store",
]
