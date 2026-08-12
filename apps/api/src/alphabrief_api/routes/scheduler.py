"""Scheduler API routes — read-only access to the operations scheduler.

Routes
------

- ``GET /api/v1/scheduler/status``     — aggregate heartbeat / freeze / alert counts
- ``GET /api/v1/scheduler/heartbeats`` — one row per task with last-run state
- ``GET /api/v1/scheduler/alerts``     — recent alerts (query: ``?limit=N``)
- ``GET /api/v1/scheduler/tasks``      — static description of registered tasks
- ``GET /api/v1/scheduler/freezes``    — currently-open broker freezes

The surface is strictly read-only. The scheduler process is launched
from the CLI (``alphabrief scheduler run``); these endpoints reflect
whatever state has been persisted to the local DuckDB file.

When the separate launchd-managed scheduler process holds the
DuckDB writer lock, the read-only store cannot open. Each endpoint
catches that failure and returns a structured ``{"error": ...,
"kind": "scheduler_writer_locked"}`` payload with HTTP 503 so the
dashboard can render a graceful "Scheduler writer active — data
unavailable" message instead of a 500 that breaks the page.
"""

from __future__ import annotations

import functools
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from alphabrief_execution.broker.recon_store import BrokerReconStore
from alphabrief_execution.operations.scheduler import (
    HeartbeatStore,
    build_default_tasks,
)
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from alphabrief_api.db.merged import scheduler_snapshot_path

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/scheduler", tags=["scheduler"])


# ---------------------------------------------------------------------------
# Scheduler DB snapshot
# ---------------------------------------------------------------------------
#
# Shared with every other dashboard route: see
# :mod:`alphabrief_api.db.merged`.

# ---------------------------------------------------------------------------
# Writer-lock detection
# ---------------------------------------------------------------------------


def _is_writer_lock_error(exc: BaseException) -> bool:
    """Return ``True`` when ``exc`` is a DuckDB writer-lock collision.

    DuckDB raises ``IOException`` with a message containing
    ``"Could not set lock"`` when another process already holds the
    write lock on the same file. We also match the R lock / database
    is locked variants to be safe across DuckDB versions.
    """
    msg = str(exc).lower()
    needles = (
        "could not set lock",
        "database is locked",
        "another process",
        "i/o error",
        "conflicting lock",
    )
    return any(needle in msg for needle in needles)


def _writer_locked_response() -> JSONResponse:
    """Return the standard 503 payload for writer-lock collisions.

    The dashboard reads ``kind == "scheduler_writer_locked"`` to
    render a graceful "Scheduler writer active — data unavailable"
    card instead of an error.
    """
    return JSONResponse(
        status_code=503,
        content={
            "error": "scheduler_writer_locked",
            "kind": "scheduler_writer_locked",
            "message": (
                "Scheduler DuckDB writer is held by another process; "
                "read-only data is temporarily unavailable."
            ),
        },
    )


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------


def _store_db_path() -> Path | None:
    """Resolve the DB file the read-only scheduler routes should read."""
    snapshot = scheduler_snapshot_path()
    if snapshot is not None:
        return snapshot
    db_dir_str = os.environ.get("ALPHABRIEF_DATA_DIR")
    if db_dir_str:
        db_dir = Path(db_dir_str)
        db_dir.mkdir(parents=True, exist_ok=True)
        return db_dir / "alphabrief.db"
    return None


def _heartbeat_store() -> HeartbeatStore:
    db_path = _store_db_path()
    if db_path is not None:
        return HeartbeatStore(db_path=db_path)
    return HeartbeatStore()


def _recon_store() -> BrokerReconStore:
    db_path = _store_db_path()
    if db_path is not None:
        return BrokerReconStore(db_path=db_path)
    return BrokerReconStore()


def _safe_reader(
    handler: Callable[..., dict[str, Any] | JSONResponse],
) -> Callable[..., dict[str, Any] | JSONResponse]:
    """Run a read-only scheduler handler, returning 503 on writer-lock.

    Decorator-free wrapper used by every route below. Any non-
    writer-lock exception propagates so it remains visible in tests
    and logs; writer-lock collisions return the structured
    ``scheduler_writer_locked`` 503 payload.
    """

    @functools.wraps(handler)
    def _wrapper(
        *args: Any, **kwargs: Any
    ) -> dict[str, Any] | JSONResponse:
        try:
            return handler(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — narrow re-raise below
            if _is_writer_lock_error(exc):
                _LOGGER.warning(
                    "scheduler: writer lock detected while reading store: %s", exc
                )
                return _writer_locked_response()
            raise

    return _wrapper


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/status")
@_safe_reader
def scheduler_status() -> dict[str, Any]:
    """Return aggregate scheduler state.

    ``running`` is always ``False`` in this phase: the scheduler is a
    separate CLI process, not an API worker. The field is reserved
    for a future round that probes a PID file.
    """
    heartbeats = _heartbeat_store()
    recon = _recon_store()
    try:
        heartbeats_rows = heartbeats.list_heartbeats()
        open_freezes = recon.list_freezes(only_open=True)
        recent_alerts = heartbeats.list_alerts(limit=500)
        return {
            "heartbeat_count": len(heartbeats_rows),
            "open_freeze_count": len(open_freezes),
            "alerts_total": len(recent_alerts),
            "running": False,
        }
    finally:
        heartbeats.close()
        recon.close()


@router.get("/heartbeats")
@_safe_reader
def scheduler_heartbeats() -> dict[str, Any]:
    """Return one row per registered task, newest-first by ``last_run_at``."""
    heartbeats = _heartbeat_store()
    try:
        rows = heartbeats.list_heartbeats()
    finally:
        heartbeats.close()
    return {"heartbeats": rows}


@router.get("/alerts")
@_safe_reader
def scheduler_alerts(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    """Return recent alerts (newest-first). ``limit`` is clamped to [1, 500]."""
    heartbeats = _heartbeat_store()
    try:
        rows = heartbeats.list_alerts(limit=limit)
    finally:
        heartbeats.close()
    return {"alerts": rows}


@router.get("/tasks")
@_safe_reader
def scheduler_tasks() -> dict[str, Any]:
    """Return the static description of the default registered tasks.

    The scheduler is not co-located with the API process, so the API
    cannot introspect live in-memory state. The static default-task
    set returned here mirrors what ``alphabrief scheduler run`` would
    actually run on startup.
    """

    async def _noop_handler(scope: str) -> None:
        return None

    tasks = build_default_tasks(on_reconcile=_noop_handler)
    return {
        "tasks": [
            {
                "name": task.name,
                "interval_seconds": task.interval_seconds,
                "timeout_seconds": task.timeout_seconds,
                "max_retries": task.max_retries,
                "enabled": task.enabled,
            }
            for task in tasks
        ]
    }


@router.get("/freezes")
@_safe_reader
def scheduler_freezes() -> dict[str, Any]:
    """Return currently-open broker freezes."""
    recon = _recon_store()
    try:
        rows = recon.list_freezes(only_open=True)
    finally:
        recon.close()
    return {
        "open_freezes": [
            {
                "event_id": f.event_id,
                "raised_at": f.raised_at,
                "scope": f.scope,
                "reason": f.reason,
                "source": f.source,
            }
            for f in rows
        ]
    }


__all__ = ["router"]
