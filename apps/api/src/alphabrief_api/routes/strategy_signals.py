"""Strategy signal history routes — read-write access to recorded signals.

This module exposes the :class:`StrategySignalStore` to the HTTP API
as the **advisory signal history** surface for Phase 15 R15.5.

Endpoints:

- ``POST   /api/v1/strategies/signals``             — record a signal
- ``GET    /api/v1/strategies/signals``             — list summaries
- ``GET    /api/v1/strategies/signals/{signal_id}`` — full record
- ``DELETE /api/v1/strategies/signals/{signal_id}`` — remove a signal
- ``GET    /api/v1/strategies/{strategy_id}/signals/count``
                                                      — signal count

The router is **strictly advisory**. It never modifies RiskGate
semantics, never affects execution, and never enables live trading.
Backtests and the dashboard consume this surface; the execution
loop does not.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_api.db import StrategySignalStore

# ---------------------------------------------------------------------------
# Persistent store (DuckDB-backed)
# ---------------------------------------------------------------------------

_signal_store: StrategySignalStore | None = None


def _get_signal_store() -> StrategySignalStore:
    """Return the singleton StrategySignalStore, creating on first access."""
    global _signal_store
    if _signal_store is None:
        _signal_store = StrategySignalStore()
    return _signal_store


def _clear_signal_store() -> None:
    """Clear the persistent signal store (for test isolation)."""
    global _signal_store
    if _signal_store is not None:
        _signal_store.clear()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class SignalCreateRequest(BaseModel):
    """Request body for ``POST /api/v1/strategies/signals``.

    The ``signal`` field is a free-form object that must validate
    against the signal schema (``signal_id``, ``strategy_id``,
    ``symbol``, ``timestamp``, ``direction``, ``confidence``,
    ``horizon``). The full payload is preserved server-side.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal: dict[str, Any] = Field(description="Signal payload as JSON")
    source: str = Field(
        default="other",
        description=(
            "Source label for the call site: 'backtest', 'manual', "
            "or 'other'. Defaults to 'other'."
        ),
    )


class SignalSummary(BaseModel):
    """Lightweight summary of a stored signal (for the list endpoint)."""

    model_config = ConfigDict(frozen=True)

    signal_id: str
    strategy_id: str
    symbol: str
    timestamp: str
    direction: str
    confidence: float
    horizon: str
    source: str
    created_at: str


class SignalSummaryList(BaseModel):
    """Response body for ``GET /api/v1/strategies/signals``."""

    model_config = ConfigDict(frozen=True)

    signals: list[SignalSummary]


class SignalRecordResponse(BaseModel):
    """Response body for ``GET /api/v1/strategies/signals/{signal_id}``."""

    model_config = ConfigDict(frozen=True)

    signal_id: str
    strategy_id: str
    symbol: str
    timestamp: str
    direction: str
    confidence: float
    horizon: str
    source: str
    signal: dict[str, Any]
    created_at: str


class SignalCreateResponse(BaseModel):
    """Response body for ``POST /api/v1/strategies/signals``."""

    model_config = ConfigDict(frozen=True)

    signal_id: str
    strategy_id: str
    source: str


class SignalCountResponse(BaseModel):
    """Response body for the per-strategy signal-count endpoint."""

    model_config = ConfigDict(frozen=True)

    strategy_id: str
    count: int


class SignalDeleteResponse(BaseModel):
    """Response body for ``DELETE /api/v1/strategies/signals/{signal_id}``."""

    model_config = ConfigDict(frozen=True)

    signal_id: str
    deleted: bool


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_VALID_SOURCES: frozenset[str] = frozenset({"backtest", "manual", "other"})


def _validate_signal_payload(
    signal: dict[str, Any],
    source: str,
) -> None:
    """Validate a signal payload. Raises ``HTTPException(422)`` on error."""
    if source not in _VALID_SOURCES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"source must be one of {sorted(_VALID_SOURCES)}, got {source!r}"
            ),
        )
    sid = signal.get("signal_id")
    if not isinstance(sid, str) or sid.strip() == "":
        raise HTTPException(
            status_code=422, detail="signal.signal_id must be a non-empty string"
        )
    for field in ("strategy_id", "symbol", "timestamp", "direction", "horizon"):
        val = signal.get(field)
        if not isinstance(val, str) or val.strip() == "":
            raise HTTPException(
                status_code=422,
                detail=f"signal.{field} must be a non-empty string",
            )
    confidence = signal.get("confidence")
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
    ):
        raise HTTPException(
            status_code=422,
            detail="signal.confidence must be a number in [0, 1]",
        )
    if not 0.0 <= float(confidence) <= 1.0:
        raise HTTPException(
            status_code=422,
            detail="signal.confidence must be in [0, 1]",
        )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/signals", response_model=SignalCreateResponse, status_code=201)
def record_signal(body: SignalCreateRequest) -> SignalCreateResponse:
    """Persist a strategy signal. Replaces an existing row with the same id.

    The signal payload is validated server-side. The ``source`` field
    defaults to ``"other"``. The store is advisory: this endpoint
    never blocks orders or modifies risk decisions.
    """
    _validate_signal_payload(body.signal, body.source)
    store = _get_signal_store()
    signal_id = store.save_signal(dict(body.signal), source=body.source)
    strategy_id = str(body.signal.get("strategy_id", ""))
    return SignalCreateResponse(
        signal_id=signal_id,
        strategy_id=strategy_id,
        source=body.source,
    )


@router.get("/signals", response_model=SignalSummaryList)
def list_signals(
    strategy_id: str | None = Query(
        None,
        description="Filter to a single strategy id.",
    ),
    symbol: str | None = Query(
        None,
        description="Filter to a single symbol.",
    ),
    source: str | None = Query(
        None,
        description="Filter by source label (backtest / manual / other).",
    ),
    limit: int | None = Query(
        None,
        ge=1,
        le=1000,
        description="Hard cap on the number of returned rows.",
    ),
) -> SignalSummaryList:
    """Return signal summaries ordered by ``timestamp`` descending."""
    store = _get_signal_store()
    rows = store.list_signals(
        strategy_id=strategy_id,
        symbol=symbol,
        source=source,
        limit=limit,
    )
    summaries = [
        SignalSummary(
            signal_id=r["signal_id"],
            strategy_id=r["strategy_id"],
            symbol=r["symbol"],
            timestamp=str(r["timestamp"]),
            direction=r["direction"],
            confidence=float(r["confidence"]),
            horizon=r["horizon"],
            source=r["source"],
            created_at=str(r["created_at"]),
        )
        for r in rows
    ]
    return SignalSummaryList(signals=summaries)


@router.get("/signals/{signal_id}", response_model=SignalRecordResponse)
def get_signal(signal_id: str) -> SignalRecordResponse:
    """Return the full record for a single signal."""
    store = _get_signal_store()
    record = store.get_signal(signal_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"signal {signal_id!r} not found",
        )
    return SignalRecordResponse(
        signal_id=record["signal_id"],
        strategy_id=record["strategy_id"],
        symbol=record["symbol"],
        timestamp=str(record["timestamp"]),
        direction=record["direction"],
        confidence=float(record["confidence"]),
        horizon=record["horizon"],
        source=record["source"],
        signal=dict(record["signal"]),
        created_at=str(record["created_at"]),
    )


@router.delete("/signals/{signal_id}", response_model=SignalDeleteResponse)
def delete_signal(signal_id: str) -> SignalDeleteResponse:
    """Remove a single signal from the history. Advisory only."""
    store = _get_signal_store()
    deleted = store.delete_signal(signal_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"signal {signal_id!r} not found",
        )
    return SignalDeleteResponse(signal_id=signal_id, deleted=True)


@router.get(
    "/{strategy_id}/signals/count",
    response_model=SignalCountResponse,
)
def count_strategy_signals(strategy_id: str) -> SignalCountResponse:
    """Return the number of stored signals for *strategy_id*."""
    store = _get_signal_store()
    count = store.count_signals(strategy_id=strategy_id)
    return SignalCountResponse(strategy_id=strategy_id, count=count)


__all__ = [
    "SignalCountResponse",
    "SignalCreateRequest",
    "SignalCreateResponse",
    "SignalDeleteResponse",
    "SignalRecordResponse",
    "SignalSummary",
    "SignalSummaryList",
    "_clear_signal_store",
    "_get_signal_store",
    "router",
]
