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
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from alphabrief_execution.broker.recon_store import BrokerReconStore
from alphabrief_execution.operations.scheduler import (
    HeartbeatStore,
    build_default_tasks,
)
from fastapi import APIRouter, Query

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/scheduler", tags=["scheduler"])


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------


def _heartbeat_store() -> HeartbeatStore:
    db_dir_str = os.environ.get("ALPHABRIEF_DATA_DIR")
    if db_dir_str:
        db_dir = Path(db_dir_str)
        db_dir.mkdir(parents=True, exist_ok=True)
        return HeartbeatStore(db_path=db_dir / "alphabrief.db")
    return HeartbeatStore()


def _recon_store() -> BrokerReconStore:
    db_dir_str = os.environ.get("ALPHABRIEF_DATA_DIR")
    if db_dir_str:
        db_dir = Path(db_dir_str)
        db_dir.mkdir(parents=True, exist_ok=True)
        return BrokerReconStore(db_path=db_dir / "alphabrief.db")
    return BrokerReconStore()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/status")
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
def scheduler_heartbeats() -> dict[str, Any]:
    """Return one row per registered task, newest-first by ``last_run_at``."""
    heartbeats = _heartbeat_store()
    try:
        rows = heartbeats.list_heartbeats()
    finally:
        heartbeats.close()
    return {"heartbeats": rows}


@router.get("/alerts")
def scheduler_alerts(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    """Return recent alerts (newest-first). ``limit`` is clamped to [1, 500]."""
    heartbeats = _heartbeat_store()
    try:
        rows = heartbeats.list_alerts(limit=limit)
    finally:
        heartbeats.close()
    return {"alerts": rows}


@router.get("/tasks")
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
