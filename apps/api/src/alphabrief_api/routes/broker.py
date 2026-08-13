"""Broker API routes — read-only access to the external paper broker.

Routes
------

- ``GET  /api/v1/broker/status``           — last reconciliation snapshot + open freezes
- ``POST /api/v1/broker/reconcile``        — run one reconcile pass
- ``GET  /api/v1/broker/orders``           — list open broker orders
- ``GET  /api/v1/broker/positions``        — open broker positions (live read)
- ``GET  /api/v1/broker/account``          — account cash/equity/buying power (live)
- ``POST /api/v1/broker/freeze``           — raise a manual freeze
- ``POST /api/v1/broker/unfreeze``         — clear an open freeze by id

The routes never place orders without a RiskDecision. ``/positions`` and
``/account`` perform live **read-only** probes against the API-side
``BrokerAdapter`` singleton (Phase 20); the account-level exposure
*enforcement* lives in :class:`alphabrief_risk.RiskGate`, not in these
endpoints. The remaining routes proxy the in-process
:class:`BrokerReconStore`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from alphabrief_execution.broker.errors import BrokerAdapterError
from alphabrief_execution.broker.recon_store import BrokerReconStore
from alphabrief_execution.broker.reconciliation import (
    ALLOWED_SCOPES,
    ReconciliationRunner,
)
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_api.broker_adapter import get_broker_adapter, has_live_broker

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
# Live-read response models (stringified so Decimal/datetime never hit
# FastAPI float coercion — mirrors the routes/paper.py precedent).
# ---------------------------------------------------------------------------


class BrokerPositionResponse(BaseModel):
    """One open position reported by the broker adapter."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    quantity: str
    average_price: str


class BrokerAccountResponse(BaseModel):
    """Account cash / equity / buying-power snapshot from the adapter."""

    model_config = ConfigDict(frozen=True)

    account_id: str
    cash: str
    equity: str
    buying_power: str
    currency: str
    captured_at: str


# ---------------------------------------------------------------------------
# async -> sync bridge + error mapping for live reads
# ---------------------------------------------------------------------------


def _run_live_read(coro: Any) -> Any:
    """Await an adapter coroutine from a sync route handler.

    The adapter methods are ``async def`` but their bodies are synchronous
    (the Alpaca client is a sync urllib client). Mirrors the scheduler's
    ``asyncio.run(scheduler.run())`` bridge idiom. Maps broker errors to
    HTTP 503 (upstream broker unreachable / refused) with a structured
    ``{"error","kind"}`` detail; never returns a 500 and never silently
    falls back to the stub on a live failure.
    """
    try:
        return asyncio.run(coro)
    except BrokerAdapterError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "broker_adapter_unavailable",
                "kind": type(exc).__name__,
                "message": str(exc),
            },
        ) from exc
    except (OSError, TimeoutError) as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "broker_adapter_unavailable",
                "kind": "transport",
                "message": str(exc),
            },
        ) from exc


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
    """Run one real reconciliation pass through the shared durable service.

    Uses the same :class:`ReconciliationRunner` as the CLI and the
    scheduler startup (AC-M07-W06-03). With no OANDA practice
    credentials the runner records a fail-closed non-matching snapshot —
    never an unconditional all-match placeholder. Upstream broker
    failures map to HTTP 503.
    """
    if scope not in ALLOWED_SCOPES:
        raise HTTPException(
            status_code=400,
            detail=f"--scope must be one of {sorted(ALLOWED_SCOPES)}",
        )
    store = _store()
    try:
        runner = ReconciliationRunner(adapter=get_broker_adapter(), store=store)
        try:
            result = asyncio.run(runner.reconcile(scope=scope))
        except BrokerAdapterError as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "broker_adapter_unavailable",
                    "kind": type(exc).__name__,
                    "message": str(exc),
                },
            ) from exc
    finally:
        store.close()
    return {
        "snapshot_id": result.snapshot.snapshot_id,
        "captured_at": result.snapshot.captured_at,
        "scope": result.snapshot.scope,
        "all_match": result.snapshot.all_match,
        "freeze_raised": result.freeze_raised,
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


@router.get("/positions", response_model=None)
def broker_positions() -> dict[str, Any]:
    """List broker positions via the API-side adapter singleton (live read).

    Phase 20: when a live ``BrokerAdapter`` is wired (Alpaca Paper
    credentials present) this performs a read-only ``get_positions()``
    probe and returns the parsed positions. When no credentials are
    configured the null adapter returns an empty list, preserving the
    pre-Phase-20 stub shape so the API still boots in dev / CI.

    The runtime account-exposure *enforcement* (Phase 19) is delivered
    by :class:`alphabrief_risk.RiskGate` against an
    :class:`AccountExposureContext`, not by this read endpoint. This
    route never places orders.
    """
    adapter = get_broker_adapter()
    if not has_live_broker():
        return {"positions": []}
    positions = _run_live_read(adapter.get_positions())
    return {
        "positions": [
            BrokerPositionResponse(
                symbol=p.symbol,
                quantity=str(p.quantity),
                average_price=str(p.average_price),
            )
            for p in positions
        ]
    }


@router.get("/account", response_model=None)
def broker_account() -> dict[str, Any]:
    """Return the account snapshot via the adapter singleton (live read).

    Phase 20: when a live ``BrokerAdapter`` is wired this performs a
    read-only ``get_account()`` probe. When no credentials are
    configured the null adapter returns a zero snapshot
    (``account_id="null-adapter"``, zero Decimals) — a real value object
    rather than the pre-Phase-20 ``{"account": None}`` stub.

    Like ``/positions``, the enforcement path does not depend on this
    endpoint. This route never places orders.
    """
    adapter = get_broker_adapter()
    account = _run_live_read(adapter.get_account())
    response = BrokerAccountResponse(
        account_id=account.account_id,
        cash=str(account.cash),
        equity=str(account.equity),
        buying_power=str(account.buying_power),
        currency=account.currency,
        captured_at=account.captured_at.isoformat(),
    )
    return {"account": response}


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
