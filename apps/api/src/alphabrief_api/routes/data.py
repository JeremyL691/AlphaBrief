"""Market data routes for the AlphaBrief API — data directory status,
data loading, bar querying, and provider-driven fetching.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from alphabrief_core.config import AppSettings, load_settings
from alphabrief_core.domain import Bar  # noqa: F401
from alphabrief_data import (
    AlphaVantageProvider,
    BinanceProvider,
    MarketDataLoadError,
    MarketDataProvider,
    MarketDataProviderError,
    YahooFinanceProvider,
    load_ohlcv_csv,
    load_ohlcv_parquet,
)
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_api.db.market_data import MarketDataStore

# ---------------------------------------------------------------------------
# Persistent data store (DuckDB-backed)
# ---------------------------------------------------------------------------


_store: MarketDataStore | None = None
"""Module-level singleton for the DuckDB-backed market data store."""


def _get_store() -> MarketDataStore:
    """Return the singleton MarketDataStore, creating it on first access."""
    global _store
    if _store is None:
        _store = MarketDataStore()
    return _store


def _clear_store() -> None:
    """Clear the persistent data store (drop + recreate tables).

    Used for test isolation.  Does not close the connection — callers
    that want a fresh connection should also call ``_close_store()``.
    """
    global _store
    if _store is not None:
        _store.clear()


def _close_store() -> None:
    """Close and nullify the singleton store.

    Used alongside ``_clear_store`` in test fixtures that change the
    database path via ``ALPHABRIEF_DATA_DIR``.
    """
    global _store
    if _store is not None:
        _store.close()
        _store = None


def _get_stored_bars(symbol: str) -> list[Bar]:
    """Retrieve stored ``Bar`` objects for *symbol*, raising 404 when absent.

    Used by backtest and other routes that need domain-model objects rather
    than JSON-serializable dicts.
    """

    store = _get_store()
    if not store.symbol_exists(symbol):
        raise HTTPException(
            status_code=404, detail=f"symbol {symbol!r} not loaded"
        )
    return store.get_bar_models(symbol)


# ---------------------------------------------------------------------------
# Response / request models
# ---------------------------------------------------------------------------


class DataStatus(BaseModel):
    """Data directory status response body."""

    model_config = ConfigDict(frozen=True)

    data_dir: str
    data_dir_exists: bool
    data_dir_has_files: bool
    files_summary: str


class DataLoadRequest(BaseModel):
    """Request body for POST /api/v1/data/load."""

    model_config = ConfigDict(frozen=True)

    file_path: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    source: str = "local"
    data_version: str = "0.0.0"
    file_type: Literal["csv", "parquet"] = "csv"


class DataLoadResponse(BaseModel):
    """Response body for successful data load."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    bar_count: int
    source: str
    data_version: str


class SymbolSummary(BaseModel):
    """Summary of a loaded symbol."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    bar_count: int
    source: str
    data_version: str


class SymbolsResponse(BaseModel):
    """Response body for GET /api/v1/data/symbols."""

    model_config = ConfigDict(frozen=True)

    symbols: list[SymbolSummary]


class SymbolInfo(BaseModel):
    """Response body for GET /api/v1/data/{symbol}/info."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    bar_count: int
    source: str
    data_version: str
    time_start: str | None
    time_end: str | None


class BarsResponse(BaseModel):
    """Response body for GET /api/v1/data/{symbol}/bars."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    total_count: int
    offset: int
    limit: int
    bars: list[dict[str, object]]


class DataFetchRequest(BaseModel):
    """Request body for POST /api/v1/data/fetch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: Literal["yahoo", "binance", "alphavantage"]
    symbol: str = Field(min_length=1)
    start: str = Field(min_length=1, description="ISO-8601 date or datetime")
    end: str = Field(min_length=1, description="ISO-8601 date or datetime")
    interval: Literal[
        "1m", "3m", "5m", "15m", "30m", "1h", "1d", "1wk", "1mo", "1w", "1M"
    ] = "1d"
    data_version: str = Field(default="fetch-v1", min_length=1)


class DataFetchResponse(BaseModel):
    """Response body for POST /api/v1/data/fetch."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    source: str
    interval: str
    data_version: str
    bar_count: int
    time_start: str | None
    time_end: str | None


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/data", tags=["data"])


# ---------------------------------------------------------------------------
# Helpers for existing data-status endpoint
# ---------------------------------------------------------------------------


def _summarize_data_files(data_dir: Path) -> tuple[bool, str]:
    """Summarize CSV and Parquet files under the configured data directory."""

    files = [path for path in data_dir.iterdir() if path.is_file()]
    csv_count = sum(1 for path in files if path.suffix.lower() == ".csv")
    parquet_count = sum(1 for path in files if path.suffix.lower() == ".parquet")
    if not files:
        return False, "no files found"
    return True, f"{len(files)} files found; csv={csv_count}; parquet={parquet_count}"


def _data_status_from_settings(settings: AppSettings) -> DataStatus:
    """Build a data status response from application settings."""

    data_dir = settings.data_dir
    data_dir_exists = data_dir.exists() and data_dir.is_dir()
    data_dir_has_files = False
    files_summary = "data directory does not exist"
    if data_dir_exists:
        data_dir_has_files, files_summary = _summarize_data_files(data_dir)

    return DataStatus(
        data_dir=str(data_dir),
        data_dir_exists=data_dir_exists,
        data_dir_has_files=data_dir_has_files,
        files_summary=files_summary,
    )


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


# ---------------------------------------------------------------------------
# Existing endpoint (prefix updated to /api/v1/data)
# ---------------------------------------------------------------------------


@router.get("/status", response_model=DataStatus)
def get_data_status() -> DataStatus:
    """Return read-only status for the configured data directory."""

    return _data_status_from_settings(load_settings())


# ---------------------------------------------------------------------------
# New Phase 6 Round 2 endpoints
# ---------------------------------------------------------------------------


@router.post("/load", response_model=DataLoadResponse, status_code=201)
def load_market_data(body: DataLoadRequest) -> DataLoadResponse:
    """Load OHLCV market data from a local CSV or Parquet file.

    The loaded bars are persisted in DuckDB keyed by symbol.
    Re-loading the same symbol overwrites existing data.
    """
    file_path = Path(body.file_path)
    if not file_path.is_file():
        raise HTTPException(
            status_code=404, detail=f"file not found: {body.file_path}"
        )

    try:
        if body.file_type == "parquet":
            bars = load_ohlcv_parquet(
                file_path,
                symbol=body.symbol,
                source=body.source,
                data_version=body.data_version,
            )
        else:
            bars = load_ohlcv_csv(
                file_path,
                symbol=body.symbol,
                source=body.source,
                data_version=body.data_version,
            )
    except MarketDataLoadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    store = _get_store()
    bar_count = store.insert_bars(
        bars, source=body.source, data_version=body.data_version
    )

    return DataLoadResponse(
        symbol=body.symbol,
        bar_count=bar_count,
        source=body.source,
        data_version=body.data_version,
    )


@router.get("/symbols", response_model=SymbolsResponse)
def list_symbols() -> SymbolsResponse:
    """List all symbols currently loaded in the persistent data store."""

    store = _get_store()
    rows = store.get_symbols()
    summaries: list[SymbolSummary] = [
        SymbolSummary(
            symbol=str(row["symbol"]),
            bar_count=int(str(row["bar_count"])),
            source=str(row["source"]),
            data_version=str(row["data_version"]),
        )
        for row in rows
    ]
    return SymbolsResponse(symbols=summaries)


@router.get("/{symbol}/bars", response_model=BarsResponse)
def get_bars(
    symbol: str,
    limit: int = 100,
    offset: int = 0,
) -> BarsResponse:
    """Return OHLCV bars for *symbol* with pagination."""
    if limit < 1 or limit > 10_000:
        raise HTTPException(
            status_code=422, detail="limit must be between 1 and 10000"
        )
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be >= 0")

    store = _get_store()
    if not store.symbol_exists(symbol):
        raise HTTPException(
            status_code=404, detail=f"symbol {symbol!r} not loaded"
        )

    total = store.get_bar_count(symbol)

    if offset >= total and total > 0:
        raise HTTPException(
            status_code=416, detail="offset exceeds total bar count"
        )

    json_bars = store.get_bars(symbol, limit=limit, offset=offset)

    return BarsResponse(
        symbol=symbol,
        total_count=total,
        offset=offset,
        limit=limit,
        bars=json_bars,
    )


@router.get("/{symbol}/info", response_model=SymbolInfo)
def get_symbol_info(symbol: str) -> SymbolInfo:
    """Return metadata for *symbol* loaded in the persistent data store."""

    store = _get_store()
    info = store.get_symbol_info(symbol)
    if info is None:
        raise HTTPException(
            status_code=404, detail=f"symbol {symbol!r} not loaded"
        )

    return SymbolInfo(
        symbol=str(info["symbol"]),
        bar_count=int(str(info["bar_count"])),
        source=str(info["source"]),
        data_version=str(info["data_version"]),
        time_start=_optional_string(info["time_start"]),
        time_end=_optional_string(info["time_end"]),
    )


# ---------------------------------------------------------------------------
# Phase 9: provider-driven fetch endpoint
# ---------------------------------------------------------------------------


def _build_provider(source: str) -> MarketDataProvider:
    """Build a market data provider for the given *source* name."""
    if source == "yahoo":
        return YahooFinanceProvider()
    if source == "binance":
        return BinanceProvider()
    if source == "alphavantage":
        return AlphaVantageProvider()
    raise MarketDataProviderError(
        f"data fetch: unknown source {source!r}; "
        "expected 'yahoo', 'binance', or 'alphavantage'",
        code="invalid_source",
    )


def _parse_iso_to_utc(value: str, *, field_name: str) -> datetime:
    """Parse an ISO-8601 string into a UTC datetime.

    Naive inputs are anchored to UTC; aware inputs are converted to UTC.
    Raises :class:`MarketDataProviderError` on parse failure.
    """
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise MarketDataProviderError(
            f"data fetch: invalid {field_name} {value!r}: {exc}",
            code="invalid_date_range",
        ) from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@router.post("/fetch", response_model=DataFetchResponse, status_code=201)
def fetch_market_data(body: DataFetchRequest) -> DataFetchResponse:
    """Download OHLCV bars from a free public provider and persist them.

    The provider is selected by *body.source*. Bars are written to
    the AlphaBrief DuckDB store; re-fetching the same symbol replaces
    the existing ``(symbol, timestamp)`` rows in place.
    """
    try:
        provider = _build_provider(body.source)
        start_dt = _parse_iso_to_utc(body.start, field_name="start")
        end_dt = _parse_iso_to_utc(body.end, field_name="end")
        bars = provider.fetch_ohlcv(
            symbol=body.symbol,
            start=start_dt,
            end=end_dt,
            interval=body.interval,
        )
    except MarketDataProviderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not bars:
        raise HTTPException(
            status_code=404,
            detail=(
                f"provider {body.source!r} returned 0 bars for "
                f"{body.symbol!r} in [{body.start}, {body.end}) at "
                f"interval {body.interval!r}"
            ),
        )

    store = _get_store()
    bar_count = store.insert_bars(
        bars, source=body.source, data_version=body.data_version
    )

    time_start = bars[0].timestamp.isoformat()
    time_end = bars[-1].timestamp.isoformat()

    return DataFetchResponse(
        symbol=body.symbol,
        source=body.source,
        interval=body.interval,
        data_version=body.data_version,
        bar_count=bar_count,
        time_start=time_start,
        time_end=time_end,
    )


__all__ = [
    "BarsResponse",
    "DataFetchRequest",
    "DataFetchResponse",
    "DataLoadRequest",
    "DataLoadResponse",
    "DataStatus",
    "SymbolInfo",
    "SymbolSummary",
    "SymbolsResponse",
    "_clear_store",
    "_close_store",
    "_get_stored_bars",
    "router",
]
