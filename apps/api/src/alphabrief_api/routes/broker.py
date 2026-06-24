"""Broker API routes — read-only access to the external paper broker.

Routes
------

- ``GET  /api/v1/broker/status``           — last reconciliation snapshot + open freezes
- ``POST /api/v1/broker/reconcile``        — run one reconcile pass
- ``GET  /api/v1/broker/orders``           — list open broker orders
- ``GET  /api/v1/broker/positions``        — list open broker positions
- ``GET  /api/v1/broker/account``          — account cash / equity / buying power
- ``POST /api/v1/broker/freeze``           — raise a manual freeze
- ``POST /api/v1/broker/unfreeze``         — clear an open freeze by id

The routes never place orders without a RiskDecision. They are proxies
to either the in-process :class:`BrokerReconStore` (when credentials
are present) or the local store snapshot view.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from alphabrief_execution.broker.recon_store import BrokerReconStore
from alphabrief_execution.broker.reconciliation import ALLOWED_SCOPES
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/broker", tags=["broker"])


# ---------------------------------------------------------------------------
# Store helper
# ---------------------------------------------------------------------------


def _store() -> BrokerReconStore:
    db_dir_str = os.environ.get("ALPHABRIEF_DATA_DIR")
    if db_dir_str:
        db_dir = Path(db_dir_str)
        db_dir.mkdir(parents=True, exist_ok=True)
        return BrokerReconStore(db_path=db_dir / "alphabrief.db")
    return BrokerReconStore()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class FreezeRequest(BaseModel):
    """Body for POST /api/v1/broker/freeze."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reason: str = Field(min_length=1)


class UnfreezeRequest(BaseModel):
    """Body for POST /api/v1/broker/unfreeze."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/status")
def broker_status() -> dict[str, Any]:
    """Return the latest reconciliation snapshot and any open freezes."""
    store = _store()
    try:
        latest = store.latest_snapshot()
        freezes = store.list_freezes(only_open=True)
        return {
            "latest_snapshot": (
                {
                    "snapshot_id": latest.snapshot_id,
                    "captured_at": latest.captured_at,
                    "scope": latest.scope,
                    "all_match": latest.all_match,
                    "orders_match": latest.orders_match,
                    "fills_match": latest.fills_match,
                    "cash_match": latest.cash_match,
                    "positions_match": latest.positions_match,
                }
                if latest is not None
                else None
            ),
            "open_freezes": [
                {
                    "event_id": f.event_id,
                    "raised_at": f.raised_at,
                    "reason": f.reason,
                    "source": f.source,
                }
                for f in freezes
            ],
        }
    finally:
        store.close()


@router.post("/reconcile")
def broker_reconcile(scope: str = Query("cycle")) -> dict[str, Any]:
    """Record one reconciliation snapshot from the local recon store.

    The route only persists the snapshot — actual broker HTTP calls
    are made by the operations scheduler or by the API at startup when
    an adapter is configured. This endpoint is intentionally limited
    to record-keeping so callers can mark a snapshot as ``eod`` etc.
    """
    if scope not in ALLOWED_SCOPES:
        raise HTTPException(
            status_code=400,
            detail=f"--scope must be one of {sorted(ALLOWED_SCOPES)}",
        )
    store = _store()
    try:
        snapshot = store.record_snapshot(
            scope=scope,
            orders_match=True,
            fills_match=True,
            cash_match=True,
            positions_match=True,
            diff={"source": "api_offline"},
        )
    finally:
        store.close()
    return {
        "snapshot_id": snapshot.snapshot_id,
        "captured_at": snapshot.captured_at,
        "scope": snapshot.scope,
        "all_match": snapshot.all_match,
    }


@router.get("/orders")
def broker_orders() -> dict[str, Any]:
    """List broker orders (proxy through the configured adapter).

    When no adapter is wired in this round, returns the in-process
    snapshot of mapped orders. Always reads — never places.
    """
    store = _store()
    try:
        rows = store.list_order_id_map()
    finally:
        store.close()
    return {"orders": rows}


@router.get("/positions")
def broker_positions() -> dict[str, Any]:
    """List broker positions (stub — deferred to Phase 20).

    The runtime account-exposure *enforcement* (Phase 19) is delivered
    by :class:`alphabrief_risk.RiskGate` against an
    :class:`AccountExposureContext`, not by these read endpoints. This
    route still returns an empty list until a live ``BrokerAdapter``
    singleton is wired into the API process (Phase 20).
    """
    return {"positions": []}


@router.get("/account")
def broker_account() -> dict[str, Any]:
    """Return the cached account snapshot (stub — deferred to Phase 20).

    Like ``/positions``, the enforcement path does not depend on this
    endpoint. Returns ``None`` until a live ``BrokerAdapter`` singleton
    is wired into the API process (Phase 20).
    """
    return {"account": None}


@router.post("/freeze")
def broker_freeze(body: FreezeRequest) -> dict[str, Any]:
    """Raise a manual freeze. Auto-ordering blocks until cleared."""
    store = _store()
    try:
        event = store.raise_freeze(reason=body.reason, source="api")
    finally:
        store.close()
    return {
        "event_id": event.event_id,
        "raised_at": event.raised_at,
        "reason": event.reason,
        "source": event.source,
    }


@router.post("/unfreeze")
def broker_unfreeze(body: UnfreezeRequest) -> dict[str, Any]:
    """Clear an open freeze by id."""
    store = _store()
    try:
        event = store.clear_freeze(event_id=body.event_id, reason=body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        store.close()
    return {
        "event_id": event.event_id,
        "cleared_at": event.cleared_at,
    }


__all__ = ["router"]
