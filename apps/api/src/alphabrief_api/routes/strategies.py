"""Strategy registry routes — CRUD over persisted StrategySpec objects.

This round (Phase 15 R15.2) wires the
:class:`alphabrief_api.db.strategies.StrategySpecStore` to a read-write
HTTP API. It is the entry point for the Strategy Lifecycle surface.

Endpoints:

- ``POST /api/v1/strategies/specs``         — create or replace a spec
- ``GET  /api/v1/strategies/specs``         — list summaries (?enabled=true)
- ``GET  /api/v1/strategies/specs/{id}``    — full spec record
- ``PATCH /api/v1/strategies/specs/{id}``   — flip the enabled flag
- ``DELETE /api/v1/strategies/specs/{id}``  — remove

The router never modifies RiskGate semantics, never enables live
trading, and never calls broker code. The activation flag is purely
advisory at this round.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_api.db import StrategySpecStore

# ---------------------------------------------------------------------------
# Persistent store (DuckDB-backed)
# ---------------------------------------------------------------------------

_strategy_store: StrategySpecStore | None = None


def _get_strategy_store() -> StrategySpecStore:
    """Return the singleton StrategySpecStore, creating it on first access."""
    global _strategy_store
    if _strategy_store is None:
        _strategy_store = StrategySpecStore()
    return _strategy_store


def _clear_strategy_store() -> None:
    """Clear the persistent store (for test isolation)."""
    global _strategy_store
    if _strategy_store is not None:
        _strategy_store.clear()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class StrategyCreateRequest(BaseModel):
    """Request body for POST /api/v1/strategies/specs.

    The ``spec`` field is a free-form object that must validate as a
    ``StrategySpec`` on the server. We accept arbitrary JSON to stay
    forward-compatible with future ``StrategySpec`` fields; server-side
    validation is the source of truth.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    spec: dict[str, Any] = Field(description="StrategySpec payload as JSON")
    enabled: bool = Field(
        default=False,
        description="Activation flag (advisory only at this round).",
    )


class StrategyActivationRequest(BaseModel):
    """Request body for PATCH /api/v1/strategies/specs/{strategy_id}."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class StrategySummary(BaseModel):
    """Lightweight summary of a stored strategy (for the list endpoint)."""

    model_config = ConfigDict(frozen=True)

    strategy_id: str
    name: str
    version: str
    enabled: bool
    created_at: str
    updated_at: str


class StrategySummaryList(BaseModel):
    """Response body for GET /api/v1/strategies/specs."""

    model_config = ConfigDict(frozen=True)

    strategies: list[StrategySummary]


class StrategyRecordResponse(BaseModel):
    """Response body for GET /api/v1/strategies/specs/{strategy_id}.

    Returns the stored record including the full ``spec`` payload.
    """

    model_config = ConfigDict(frozen=True)

    strategy_id: str
    name: str
    version: str
    enabled: bool
    spec: dict[str, Any]
    created_at: str
    updated_at: str


class StrategyCreateResponse(BaseModel):
    """Response body for POST /api/v1/strategies/specs."""

    model_config = ConfigDict(frozen=True)

    strategy_id: str
    name: str
    version: str
    enabled: bool


class StrategyActivationResponse(BaseModel):
    """Response body for PATCH /api/v1/strategies/specs/{strategy_id}."""

    model_config = ConfigDict(frozen=True)

    strategy_id: str
    enabled: bool


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------


def _validate_spec_payload(spec: dict[str, Any]) -> tuple[str, str, str]:
    """Validate a StrategySpec-shaped payload.

    Returns ``(strategy_id, name, version)`` if valid. Raises
    ``HTTPException`` (422) on the first validation failure.
    """
    from alphabrief_strategy import StrategySpec

    try:
        parsed = StrategySpec.model_validate(spec)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"invalid StrategySpec payload: {exc}",
        ) from exc
    return parsed.strategy_id, parsed.name, parsed.version


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/specs", response_model=StrategyCreateResponse, status_code=201)
def create_or_replace_spec(body: StrategyCreateRequest) -> StrategyCreateResponse:
    """Persist a StrategySpec. Replaces an existing row with the same id.

    The server validates the payload as a ``StrategySpec`` before
    writing. The activation flag defaults to ``False``.
    """
    strategy_id, name, version = _validate_spec_payload(body.spec)
    store = _get_strategy_store()
    store.save_spec(dict(body.spec), enabled=body.enabled)
    return StrategyCreateResponse(
        strategy_id=strategy_id,
        name=name,
        version=version,
        enabled=body.enabled,
    )


@router.get("/specs", response_model=StrategySummaryList)
def list_specs(
    enabled: bool | None = Query(
        None,
        description="If set, filter to enabled (true) or disabled (false).",
    ),
) -> StrategySummaryList:
    """Return lightweight summaries of all stored strategies."""
    store = _get_strategy_store()
    rows = store.list_specs(enabled_only=enabled)
    summaries = [
        StrategySummary(
            strategy_id=r["strategy_id"],
            name=r["name"],
            version=r["version"],
            enabled=bool(r["enabled"]),
            created_at=str(r["created_at"]),
            updated_at=str(r["updated_at"]),
        )
        for r in rows
    ]
    return StrategySummaryList(strategies=summaries)


@router.get("/specs/{strategy_id}", response_model=StrategyRecordResponse)
def get_spec(strategy_id: str) -> StrategyRecordResponse:
    """Return the full stored record (including the spec payload)."""
    store = _get_strategy_store()
    record = store.get_spec(strategy_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"strategy {strategy_id!r} not found",
        )
    return StrategyRecordResponse(
        strategy_id=record["strategy_id"],
        name=record["name"],
        version=record["version"],
        enabled=bool(record["enabled"]),
        spec=dict(record["spec"]),
        created_at=str(record["created_at"]),
        updated_at=str(record["updated_at"]),
    )


@router.patch(
    "/specs/{strategy_id}", response_model=StrategyActivationResponse
)
def set_enabled(
    strategy_id: str,
    body: StrategyActivationRequest,
) -> StrategyActivationResponse:
    """Flip the activation flag for a stored strategy.

    The flag is advisory at this round and does not affect RiskGate,
    PaperBroker, or live-trading state. Future rounds may wire it into
    the risk allowlist.
    """
    store = _get_strategy_store()
    if not store.set_enabled(strategy_id, body.enabled):
        raise HTTPException(
            status_code=404,
            detail=f"strategy {strategy_id!r} not found",
        )
    return StrategyActivationResponse(
        strategy_id=strategy_id, enabled=body.enabled
    )


@router.delete(
    "/specs/{strategy_id}", response_model=StrategyActivationResponse
)
def delete_spec(strategy_id: str) -> StrategyActivationResponse:
    """Remove a strategy from the registry.

    Returns the strategy_id and the final activation state (always
    ``False`` after deletion since the row no longer exists).
    """
    store = _get_strategy_store()
    if not store.delete_spec(strategy_id):
        raise HTTPException(
            status_code=404,
            detail=f"strategy {strategy_id!r} not found",
        )
    return StrategyActivationResponse(strategy_id=strategy_id, enabled=False)


__all__ = [
    "StrategyActivationRequest",
    "StrategyActivationResponse",
    "StrategyCreateRequest",
    "StrategyCreateResponse",
    "StrategyRecordResponse",
    "StrategySummary",
    "StrategySummaryList",
    "_clear_strategy_store",
    "_get_strategy_store",
    "router",
]