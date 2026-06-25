"""Macro data routes for the AlphaBrief API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from alphabrief_news.providers import (
    FredMacroProvider,
    MockMacroProvider,
    NewsProviderError,
    build_default_mock_macro,
)
from alphabrief_news.types import MacroFetchQuery, MacroIndicator
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from alphabrief_api.db import MacroStore

# ---------------------------------------------------------------------------
# Persistent store
# ---------------------------------------------------------------------------

_store: MacroStore | None = None


def _get_store() -> MacroStore:
    if _store is None:
        return MacroStore()
    return _store


def _clear_store() -> None:
    global _store
    if _store is None:
        _store = MacroStore()
    _store.clear()


def _close_store() -> None:
    global _store
    if _store is not None:
        _store.close()
        _store = None


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

MacroSource = Literal["mock", "fred"]


class MacroFetchRequest(BaseModel):
    """Request body for POST /api/v1/macro/fetch."""

    source: MacroSource
    indicators: list[str] = Field(min_length=1)
    start: str = Field(min_length=1)
    end: str = Field(min_length=1)
    data_version: str = Field(default="macro-v1", min_length=1)


class MacroFetchResponse(BaseModel):
    """Response body for a successful macro fetch."""

    indicator_count: int
    time_start: str | None
    time_end: str | None


class MacroIndicatorSummary(BaseModel):
    """Summary of a stored macro indicator observation."""

    indicator_id: str
    name: str
    released_at: str
    value: str
    unit: str | None


class MacroIndicatorsResponse(BaseModel):
    """Response body for GET /api/v1/macro/indicators."""

    indicators: list[MacroIndicatorSummary]


class MacroIndicatorResponse(BaseModel):
    """Response body for GET /api/v1/macro/indicators/{indicator_id}."""

    indicator: MacroIndicator


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
    source: MacroSource, indicators: list[str]
) -> MockMacroProvider | FredMacroProvider:
    if source == "mock":
        return MockMacroProvider(seed_indicators=build_default_mock_macro(indicators))
    if source == "fred":
        return FredMacroProvider()
    raise HTTPException(
        status_code=422,
        detail=f"unknown macro source: {source}",
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/macro", tags=["macro"])


@router.post("/fetch", response_model=MacroFetchResponse, status_code=201)
def fetch_macro(body: MacroFetchRequest) -> MacroFetchResponse:
    """Fetch macro indicators from a provider and persist them."""
    start = _parse_iso_to_utc(body.start, field_name="start")
    end = _parse_iso_to_utc(body.end, field_name="end")

    if end <= start:
        raise HTTPException(
            status_code=422,
            detail="end must be after start",
        )

    provider = _build_provider(body.source, body.indicators)
    query = MacroFetchQuery(
        indicators=body.indicators,
        start=start,
        end=end,
        data_version=body.data_version,
    )

    try:
        indicators = provider.fetch_indicators(query)
    except NewsProviderError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc

    if not indicators:
        raise HTTPException(
            status_code=404,
            detail="provider returned no indicators for the requested window",
        )

    store = _get_store()
    store.insert_indicators(indicators)

    timestamps = sorted(i.released_at for i in indicators)
    return MacroFetchResponse(
        indicator_count=len(indicators),
        time_start=timestamps[0].astimezone(UTC).isoformat(),
        time_end=timestamps[-1].astimezone(UTC).isoformat(),
    )


@router.get("/indicators", response_model=MacroIndicatorsResponse)
def list_indicators(
    indicator_id: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> MacroIndicatorsResponse:
    """List stored macro indicators with optional filters."""
    start_dt = _parse_iso_to_utc(start, field_name="start") if start else None
    end_dt = _parse_iso_to_utc(end, field_name="end") if end else None

    store = _get_store()
    indicators = store.list_indicators(
        indicator_id=indicator_id,
        start=start_dt,
        end=end_dt,
        limit=limit,
        offset=offset,
    )

    summaries = [
        MacroIndicatorSummary(
            indicator_id=indicator.indicator_id,
            name=indicator.name,
            released_at=indicator.released_at.astimezone(UTC).isoformat(),
            value=str(indicator.value),
            unit=indicator.unit,
        )
        for indicator in indicators
    ]
    return MacroIndicatorsResponse(indicators=summaries)


@router.get("/indicators/{indicator_id}", response_model=MacroIndicatorResponse)
def get_indicator(indicator_id: str) -> MacroIndicatorResponse:
    """Return the most recent stored observation for an indicator."""
    store = _get_store()
    indicator = store.get_indicator(indicator_id)
    if indicator is None:
        raise HTTPException(
            status_code=404,
            detail=f"indicator not found: {indicator_id}",
        )
    return MacroIndicatorResponse(indicator=indicator)


__all__ = [
    "router",
    "_clear_store",
    "_close_store",
]
