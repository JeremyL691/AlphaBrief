"""Market data routes for the AlphaBrief API — data directory status,
data loading, and bar querying.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from alphabrief_core.config import AppSettings, load_settings
from alphabrief_core.domain import Bar
from alphabrief_data import MarketDataLoadError, load_ohlcv_csv, load_ohlcv_parquet
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# In-memory data store
# ---------------------------------------------------------------------------

_DataStoreValue = dict[str, object]


_data_store: dict[str, _DataStoreValue] = {}
"""Module-level in-memory store for loaded symbols.

Each entry maps symbol → { "bars": list[Bar], "source": str, "data_version": str }
"""


def _store_bars(symbol: str, bars: list[Bar], source: str, data_version: str) -> int:
    """Store loaded bars for a symbol.  Returns the bar count."""
    _data_store[symbol] = {
        "bars": bars,
        "source": source,
        "data_version": data_version,
    }
    return len(bars)


def _get_stored_bars(symbol: str) -> list[Bar]:
    """Retrieve stored bars for *symbol*, raising 404 when absent."""
    entry = _data_store.get(symbol)
    if entry is None:
        raise HTTPException(
            status_code=404, detail=f"symbol {symbol!r} not loaded"
        )
    bars: list[Bar] = entry["bars"]  # type: ignore[assignment]
    return bars


def _clear_store() -> None:
    """Clear the in-memory data store (for test isolation)."""
    _data_store.clear()


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

    The loaded bars are stored in memory keyed by symbol.
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

    bar_count = _store_bars(
        body.symbol, bars, source=body.source, data_version=body.data_version
    )

    return DataLoadResponse(
        symbol=body.symbol,
        bar_count=bar_count,
        source=body.source,
        data_version=body.data_version,
    )


@router.get("/symbols", response_model=SymbolsResponse)
def list_symbols() -> SymbolsResponse:
    """List all symbols currently loaded in the in-memory data store."""

    summaries: list[SymbolSummary] = []
    for symbol, entry in _data_store.items():
        bars: list[Bar] = entry["bars"]  # type: ignore[assignment]
        summaries.append(
            SymbolSummary(
                symbol=symbol,
                bar_count=len(bars),
                source=str(entry["source"]),
                data_version=str(entry["data_version"]),
            )
        )
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

    bars = _get_stored_bars(symbol)
    total = len(bars)

    if offset >= total and total > 0:
        raise HTTPException(
            status_code=416, detail="offset exceeds total bar count"
        )

    page = bars[offset : offset + limit]
    json_bars = [bar.model_dump(mode="json") for bar in page]

    return BarsResponse(
        symbol=symbol,
        total_count=total,
        offset=offset,
        limit=limit,
        bars=json_bars,
    )


@router.get("/{symbol}/info", response_model=SymbolInfo)
def get_symbol_info(symbol: str) -> SymbolInfo:
    """Return metadata for *symbol* loaded in the data store."""

    bars = _get_stored_bars(symbol)
    entry = _data_store[symbol]

    timestamps = sorted(bar.timestamp for bar in bars)

    time_start: str | None = None
    time_end: str | None = None
    if timestamps:
        time_start = timestamps[0].isoformat()
        time_end = timestamps[-1].isoformat()

    return SymbolInfo(
        symbol=symbol,
        bar_count=len(bars),
        source=str(entry["source"]),
        data_version=str(entry["data_version"]),
        time_start=time_start,
        time_end=time_end,
    )


__all__ = [
    "BarsResponse",
    "DataLoadRequest",
    "DataLoadResponse",
    "DataStatus",
    "SymbolInfo",
    "SymbolSummary",
    "SymbolsResponse",
    "router",
]
