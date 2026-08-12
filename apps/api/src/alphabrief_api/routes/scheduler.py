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
import shutil
import tempfile
import threading
import time
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

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/scheduler", tags=["scheduler"])


# ---------------------------------------------------------------------------
# Scheduler DB snapshot
# ---------------------------------------------------------------------------
#
# The launchd-managed scheduler holds the DuckDB writer lock on its own
# database for its lifetime, so the API cannot open that file directly
# (DuckDB is single-writer). When ``ALPHABRIEF_SCHEDULER_DB_DIR`` is set,
# the read-only scheduler endpoints serve a periodically-refreshed copy
# of that database instead of the API's own (separate) DB.

_SNAPSHOT_TTL_SECONDS = 10.0
_snapshot_state: tuple[float, Path] | None = None
_snapshot_lock = threading.Lock()


def _scheduler_db_snapshot() -> Path | None:
    """Return a path to a fresh copy of the scheduler DB, or ``None``.

    The copy (DB + WAL) is refreshed at most once per
    ``_SNAPSHOT_TTL_SECONDS``. Stale WAL files from a previous refresh
    are removed first so the copied DB always matches its WAL. A lock
    serializes concurrent dashboard polls during the first refresh.
    """
    global _snapshot_state
    src_dir = os.environ.get("ALPHABRIEF_SCHEDULER_DB_DIR", "").strip()
    if not src_dir:
        return None
    src = Path(src_dir) / "alphabrief.db"
    if not src.is_file():
        return None
    now = time.monotonic()
    if (
        _snapshot_state is not None
        and now - _snapshot_state[0] < _SNAPSHOT_TTL_SECONDS
    ):
        return _snapshot_state[1]
    with _snapshot_lock:
        # Re-check under the lock: another thread may have refreshed.
        if (
            _snapshot_state is not None
            and time.monotonic() - _snapshot_state[0] < _SNAPSHOT_TTL_SECONDS
        ):
            return _snapshot_state[1]
        dst_dir = Path(tempfile.gettempdir()) / "alphabrief_scheduler_snapshot"
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / "alphabrief.db"
        dst_wal = dst.with_name("alphabrief.db.wal")
        if dst_wal.exists():
            dst_wal.unlink()
        shutil.copy2(src, dst)
        src_wal = src.with_name("alphabrief.db.wal")
        if src_wal.is_file():
            shutil.copy2(src_wal, dst_wal)
        _snapshot_state = (time.monotonic(), dst)
        return dst


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
    snapshot = _scheduler_db_snapshot()
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
