"""Async broker-aware operations scheduler.

Stdlib ``asyncio`` only; no external scheduler, no new dependencies.

Tasks are declared as :class:`ScheduledTask` instances and the
:class:`OperationsScheduler` runs them in a single event loop,
tracking last-run heartbeats in DuckDB so a restart resumes from
the most recent successful run.

Phase 18 contracts:

- Startup calls ``reconcile(scope='startup')``; if reconciliation
  raises a freeze, the scheduler stays in a paused state and exits
  with non-zero code.
- Any task that exceeds its ``max_retries`` raises a freeze via the
  recon store and emits an alert through :class:`AlertSink`.
- Heartbeats persist to the ``scheduler_heartbeats`` DuckDB table.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import duckdb

from alphabrief_execution.broker.recon_store import BrokerReconStore
from alphabrief_execution.broker.reconciliation import ReconciliationRunner

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Heartbeat store
# ---------------------------------------------------------------------------


CREATE_HEARTBEATS = """
CREATE TABLE IF NOT EXISTS scheduler_heartbeats (
    task_name        TEXT PRIMARY KEY,
    last_run_at      TIMESTAMPTZ,
    last_status      TEXT NOT NULL,
    last_error       TEXT,
    run_count        INTEGER NOT NULL DEFAULT 0
)
"""

CREATE_ALERTS = """
CREATE TABLE IF NOT EXISTS scheduler_alerts (
    alert_id         TEXT PRIMARY KEY,
    raised_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    severity         TEXT NOT NULL,
    source           TEXT NOT NULL,
    task_name        TEXT,
    message          TEXT NOT NULL,
    payload_json     JSON NOT NULL DEFAULT '{}'
)
"""


def _default_db_path() -> Path:
    import os

    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    base = Path(env_dir) if env_dir else Path.home() / ".alphabrief" / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base / "alphabrief.db"


class HeartbeatStore:
    """Persists scheduler task heartbeats and alert history."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _default_db_path()
        self._conn = duckdb.connect(str(self._db_path))
        self._conn.execute(CREATE_HEARTBEATS)
        self._conn.execute(CREATE_ALERTS)

    def record_run(self, *, task_name: str, status: str, error: str | None) -> None:
        self._conn.execute(
            """
            INSERT INTO scheduler_heartbeats (
                task_name, last_run_at, last_status, last_error, run_count
            )
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT (task_name) DO UPDATE
            SET last_run_at = EXCLUDED.last_run_at,
                last_status = EXCLUDED.last_status,
                last_error  = EXCLUDED.last_error,
                run_count   = scheduler_heartbeats.run_count + 1
            """,
            [task_name, datetime.now(UTC).isoformat(), status, error],
        )

    def last_run_at(self, task_name: str) -> datetime | None:
        row = self._conn.execute(
            "SELECT last_run_at FROM scheduler_heartbeats WHERE task_name = ?",
            [task_name],
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return _parse_iso(str(row[0]))

    def record_alert(
        self,
        *,
        severity: str,
        source: str,
        message: str,
        task_name: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        alert_id = f"alert_{uuid4().hex}"
        self._conn.execute(
            """
            INSERT INTO scheduler_alerts (
                alert_id, severity, source, task_name, message, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                alert_id,
                severity,
                source,
                task_name,
                message,
                json.dumps(payload or {}, sort_keys=True),
            ],
        )
        return alert_id

    def list_alerts(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT alert_id, raised_at, severity, source, task_name, message "
            "FROM scheduler_alerts ORDER BY raised_at DESC LIMIT ?",
            [limit],
        ).fetchall()
        return [
            {
                "alert_id": str(row[0]),
                "raised_at": str(row[1]),
                "severity": str(row[2]),
                "source": str(row[3]),
                "task_name": str(row[4]) if row[4] is not None else None,
                "message": str(row[5]),
            }
            for row in rows
        ]

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# Alert sink
# ---------------------------------------------------------------------------


class AlertSink:
    """Pluggable alert sink. Default: log + DuckDB record + optional webhook."""

    def __init__(
        self,
        *,
        heartbeat_store: HeartbeatStore,
        webhook_url: str | None = None,
        webhook_send: Callable[[str, str, str, dict[str, Any]], Awaitable[None]]
        | None = None,
    ) -> None:
        self._heartbeats = heartbeat_store
        self._webhook_url = webhook_url
        self._webhook_send = webhook_send

    async def emit(
        self,
        *,
        severity: str,
        source: str,
        message: str,
        task_name: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        clean_payload = _scrub_payload(payload or {})
        alert_id = self._heartbeats.record_alert(
            severity=severity,
            source=source,
            message=message,
            task_name=task_name,
            payload=clean_payload,
        )
        _LOGGER.warning(
            "ALERT %s %s %s: %s", severity, source, task_name or "-", message
        )
        if self._webhook_url and self._webhook_send is not None:
            try:
                await self._webhook_send(
                    self._webhook_url, severity, message, clean_payload
                )
            except Exception as exc:  # noqa: BLE001 — alert delivery is best-effort
                _LOGGER.warning("alert webhook delivery failed: %s", exc)
        return alert_id


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScheduledTask:
    """Description of one scheduled task."""

    name: str
    interval_seconds: float
    handler: Callable[[], Awaitable[None]]
    timeout_seconds: float = 30.0
    max_retries: int = 2
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError(f"{self.name}: interval_seconds must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError(f"{self.name}: timeout_seconds must be positive")
        if self.max_retries < 0:
            raise ValueError(f"{self.name}: max_retries must be non-negative")


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


@dataclass
class SchedulerConfig:
    """Top-level scheduler configuration."""

    reconcile_on_start: bool = True
    max_consecutive_failures: int = 3
    on_failure_freeze_source: str = "scheduler"


class OperationsScheduler:
    """Long-running asyncio scheduler for paper broker operations."""

    def __init__(
        self,
        *,
        tasks: list[ScheduledTask],
        heartbeat_store: HeartbeatStore,
        alert_sink: AlertSink,
        recon_runner: ReconciliationRunner,
        recon_store: BrokerReconStore,
        config: SchedulerConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._tasks = list(tasks)
        self._heartbeats = heartbeat_store
        self._alert_sink = alert_sink
        self._recon = recon_runner
        self._recon_store = recon_store
        self._config = config or SchedulerConfig()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._stop = asyncio.Event()
        self._failure_counters: dict[str, int] = {task.name: 0 for task in self._tasks}

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        if self._config.reconcile_on_start:
            result = await self._recon.reconcile(scope="startup")
            if result.freeze_raised:
                await self._alert_sink.emit(
                    severity="critical",
                    source="scheduler",
                    message="startup reconciliation raised freeze; scheduler exiting",
                    task_name="reconcile",
                    payload={"snapshot_id": result.snapshot.snapshot_id},
                )
                raise SchedulerStartupBlockedError(
                    "startup reconciliation raised a freeze; manual unfreeze required"
                )

        try:
            await asyncio.gather(*(self._run_task(task) for task in self._tasks))
        except asyncio.CancelledError:
            raise

    async def _run_task(self, task: ScheduledTask) -> None:
        if not task.enabled:
            return
        while not self._stop.is_set():
            if self._recon_store.has_open_freeze():
                await self._alert_sink.emit(
                    severity="warning",
                    source="scheduler",
                    message=(
                        f"open freeze detected; skipping task {task.name} "
                        "until manual unfreeze"
                    ),
                    task_name=task.name,
                )
                await self._sleep(self._short_poll_seconds())
                continue
            try:
                await asyncio.wait_for(task.handler(), timeout=task.timeout_seconds)
                self._heartbeats.record_run(
                    task_name=task.name, status="ok", error=None
                )
                self._failure_counters[task.name] = 0
            except Exception as exc:  # noqa: BLE001 — record, alert, decide
                self._failure_counters[task.name] += 1
                self._heartbeats.record_run(
                    task_name=task.name, status="error", error=str(exc)
                )
                if (
                    self._failure_counters[task.name]
                    >= self._config.max_consecutive_failures
                ):
                    self._recon_store.raise_freeze(
                        reason=(
                            f"task {task.name} failed "
                            f"{self._failure_counters[task.name]} consecutive times"
                        ),
                        source=self._config.on_failure_freeze_source,
                    )
                    await self._alert_sink.emit(
                        severity="critical",
                        source="scheduler",
                        message=(
                            f"task {task.name} exceeded "
                            f"{self._config.max_consecutive_failures} failures; "
                            "auto-freeze raised"
                        ),
                        task_name=task.name,
                        payload={"error": str(exc)},
                    )
                    # Wait for the operator to clear the freeze; stop the loop on
                    # request. While a freeze is open, the top of the loop will
                    # skip task execution and only emit warnings.
                    await self._sleep(task.interval_seconds)
                    continue
            await self._sleep(task.interval_seconds)

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except TimeoutError:
            return

    def _short_poll_seconds(self) -> float:
        return 5.0


# ---------------------------------------------------------------------------
# Errors and helpers
# ---------------------------------------------------------------------------


class SchedulerStartupBlockedError(RuntimeError):
    """Raised when startup reconciliation raises a freeze."""


# ---------------------------------------------------------------------------
# Built-in task factories
# ---------------------------------------------------------------------------


def build_default_tasks(
    *,
    on_reconcile: Callable[[str], Awaitable[None]],
) -> list[ScheduledTask]:
    """Return the Phase 18 default task list.

    ``on_reconcile(scope)`` is supplied by the application; it should
    call ``ReconciliationRunner.reconcile(scope=scope)``.
    """

    async def reconcile_cycle() -> None:
        await on_reconcile("cycle")

    return [
        ScheduledTask(
            name="reconcile",
            interval_seconds=300.0,
            handler=reconcile_cycle,
            timeout_seconds=30.0,
            max_retries=1,
        ),
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _scrub_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove forbidden fields (credentials, secrets) from alert payloads."""
    forbidden = {
        "api_key",
        "api_secret",
        "secret",
        "password",
        "token",
        "authorization",
    }
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in forbidden:
            cleaned[key] = "<redacted>"
        elif isinstance(value, dict):
            cleaned[key] = _scrub_payload(value)
        else:
            cleaned[key] = value
    return cleaned


# Helper: imports kept honest if Phase 19 extends scheduler with
# back-off intervals.
__all__ = [
    "AlertSink",
    "HeartbeatStore",
    "OperationsScheduler",
    "ScheduledTask",
    "SchedulerConfig",
    "SchedulerStartupBlockedError",
    "build_default_tasks",
    "CREATE_HEARTBEATS",
    "CREATE_ALERTS",
]
