"""Async broker-aware operations scheduler.

Stdlib ``asyncio`` only; no external scheduler, no new dependencies.

Tasks are declared as :class:`ScheduledTask` instances and the
:class:`OperationsScheduler` runs them in a single event loop,
tracking last-run heartbeats in DuckDB so a restart resumes from
the most recent successful run.

Contracts:

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
from typing import Any, Protocol
from uuid import uuid4

import duckdb
from alphabrief_core import paths as _paths

from alphabrief_execution.broker.errors import BrokerTransientError
from alphabrief_execution.broker.oanda.live_reconciliation import (
    LiveReconcileResult,
)
from alphabrief_execution.broker.recon_store import BrokerReconStore

_LOGGER = logging.getLogger(__name__)

#: Default cadence of the opportunity check (PROJECT_GUIDE 5.1: every
#: 1-5 minutes). The reviewed configuration overrides it; the constant
#: exists so a bare scheduler call still honours the guide.
DEFAULT_OPPORTUNITY_SCAN_SECONDS = 180.0


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

#: One row per task execution. The heartbeat table only keeps the last
#: run; soak evidence (downtime and per-round completeness) needs every
#: run of the period, so each execution appends here. The shape matches
#: API migration 5, which owns the authoritative definition.
CREATE_TASK_RUNS = """
CREATE TABLE IF NOT EXISTS scheduler_task_runs (
    task_name        TEXT NOT NULL,
    started_at       TIMESTAMPTZ NOT NULL,
    finished_at      TIMESTAMPTZ,
    status           TEXT NOT NULL,
    error            TEXT
)
"""

CREATE_TASK_RUNS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_scheduler_task_runs_time
    ON scheduler_task_runs (started_at)
"""


class HeartbeatStore:
    """Persists scheduler task heartbeats and alert history."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _paths.db_path()
        self._conn = duckdb.connect(str(self._db_path))
        self._conn.execute(CREATE_HEARTBEATS)
        self._conn.execute(CREATE_ALERTS)
        self._conn.execute(CREATE_TASK_RUNS)
        self._conn.execute(CREATE_TASK_RUNS_INDEX)

    def record_run(
        self,
        *,
        task_name: str,
        status: str,
        error: str | None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        now = datetime.now(UTC)
        started = started_at or now
        finished = finished_at or now
        self._conn.execute(
            """
            INSERT INTO scheduler_task_runs (
                task_name, started_at, finished_at, status, error
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            [task_name, started, finished, status, error],
        )
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
            [task_name, finished.isoformat(), status, error],
        )

    def list_task_runs(
        self,
        *,
        task_name: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return recorded executions in time order, newest last.

        ``start``/``end`` bound the execution's start time. The soak
        evaluator uses this history to compute downtime and per-round
        completeness from real facts instead of the last-run heartbeat.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if task_name is not None:
            clauses.append("task_name = ?")
            params.append(task_name)
        if start is not None:
            clauses.append("started_at >= ?")
            params.append(start)
        if end is not None:
            clauses.append("started_at < ?")
            params.append(end)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"""
            SELECT task_name, started_at, finished_at, status, error
            FROM scheduler_task_runs
            {where}
            ORDER BY started_at ASC
            """,
            params,
        ).fetchall()
        return [
            {
                "task_name": str(row[0]),
                "started_at": _parse_iso(str(row[1])),
                "finished_at": (
                    _parse_iso(str(row[2])) if row[2] is not None else None
                ),
                "status": str(row[3]),
                "error": str(row[4]) if row[4] is not None else None,
            }
            for row in rows
        ]

    def last_run_at(self, task_name: str) -> datetime | None:
        row = self._conn.execute(
            "SELECT last_run_at FROM scheduler_heartbeats WHERE task_name = ?",
            [task_name],
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return _parse_iso(str(row[0]))

    def list_heartbeats(self) -> list[dict[str, Any]]:
        """Return one row per registered task, newest-first by ``last_run_at``.

        Mirrors :meth:`list_alerts`: ``last_run_at`` is an ISO string
        (or ``None`` if the task has never run), ``run_count`` is an
        int, and ``last_error`` is ``None`` for healthy runs. The
        query is read-only and does not require a transaction.
        """
        rows = self._conn.execute(
            "SELECT task_name, last_run_at, last_status, last_error, run_count "
            "FROM scheduler_heartbeats ORDER BY last_run_at DESC"
        ).fetchall()
        return [
            {
                "task_name": str(row[0]),
                "last_run_at": str(row[1]) if row[1] is not None else None,
                "last_status": str(row[2]),
                "last_error": str(row[3]) if row[3] is not None else None,
                "run_count": int(row[4]),
            }
            for row in rows
        ]

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
    run_when_frozen: bool = False

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
    # Task #4: emit a clear "broker unreachable" alert after
    # this many consecutive broker-probe failures, so the operator
    # sees the actual cause instead of N generic "transient error"
    # log lines. Defaults to 3 — same ceiling as the per-task
    # consecutive-failure count.
    broker_unavailable_alert_threshold: int = 3


# ---------------------------------------------------------------------------
# Broker-unavailability tracker
# ---------------------------------------------------------------------------


def _looks_like_broker_unavailable(exc: BaseException) -> bool:
    """Return ``True`` when ``exc`` looks like the broker is unreachable.

    Task #4: after N consecutive failures with this shape
    the scheduler should emit a clear alert. Transient broker errors
    and SSLError / URLError are all candidates.
    """
    if isinstance(exc, BrokerTransientError):
        return True
    name = exc.__class__.__name__
    return name in {
        "SSLError",
        "URLError",
        "TimeoutError",
        "ConnectionError",
        "OSError",
        "BrokerAuthError",
    }


class BrokerAvailabilityTracker:
    """Tracks consecutive broker-probe failures and emits one alert per outage.

    Task #4: a single transient ``BrokerTransientError`` is
    noise; a *pattern* of them is a real outage. This tracker counts
    consecutive failures with :func:`_looks_like_broker_unavailable`
    shape, raises one ``alert_sink.emit(severity="critical")`` when
    the count crosses the configured threshold, and resets on the
    first successful probe.

    The alert is emitted at most once per outage — not once per cycle.
    A second outage starts a new count and emits a new alert when the
    threshold is crossed again.
    """

    def __init__(
        self,
        *,
        threshold: int,
        alert_sink: AlertSink,
        source: str = "scheduler",
        task_name: str = "reconcile",
    ) -> None:
        if threshold <= 0:
            raise ValueError("threshold must be positive")
        self._threshold = threshold
        self._alert_sink = alert_sink
        self._source = source
        self._task_name = task_name
        self._consecutive_failures = 0
        self._alert_emitted_for_outage = False

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    async def record_failure(self, *, error: BaseException) -> None:
        """Record one broker-probe failure and emit an alert if needed."""
        if not _looks_like_broker_unavailable(error):
            # Non-broker-shaped exception — let the existing scheduler
            # failure path handle it (auto-freeze, etc.).
            return
        self._consecutive_failures += 1
        if (
            self._consecutive_failures >= self._threshold
            and not self._alert_emitted_for_outage
        ):
            await self._alert_sink.emit(
                severity="critical",
                source=self._source,
                message=(
                    f"broker unreachable for {self._consecutive_failures} "
                    "consecutive attempts; auto-ordering will stay paused "
                    "until the broker recovers"
                ),
                task_name=self._task_name,
                payload={
                    "consecutive_failures": self._consecutive_failures,
                    "threshold": self._threshold,
                    "last_error": str(error),
                },
            )
            self._alert_emitted_for_outage = True

    def record_success(self) -> None:
        """Record one successful broker probe and reset the outage tracker."""
        if (
            self._consecutive_failures > 0
            and self._alert_emitted_for_outage
        ):
            _LOGGER.info(
                "broker recovered after %d consecutive failures",
                self._consecutive_failures,
            )
        self._consecutive_failures = 0
        self._alert_emitted_for_outage = False


class ReconcilerLike(Protocol):
    """The slice of the reconciler the scheduler depends on."""

    def reconcile(self, *, scope: str = "cycle") -> LiveReconcileResult: ...


class OperationsScheduler:
    """Long-running asyncio scheduler for paper broker operations."""

    def __init__(
        self,
        *,
        tasks: list[ScheduledTask],
        heartbeat_store: HeartbeatStore,
        alert_sink: AlertSink,
        recon_store: BrokerReconStore,
        recon_runner: ReconcilerLike | None = None,
        config: SchedulerConfig | None = None,
        clock: Callable[[], datetime] | None = None,
        broker_tracker: BrokerAvailabilityTracker | None = None,
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
        # Task #4: optional broker-availability tracker. When
        # not supplied we build a no-op tracker so the existing call
        # sites that do not pass one keep working unchanged.
        self._broker_tracker = broker_tracker or BrokerAvailabilityTracker(
            threshold=self._config.broker_unavailable_alert_threshold,
            alert_sink=alert_sink,
        )

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        if self._config.reconcile_on_start and self._recon is not None:
            # The live reconciler is synchronous (urllib); run it off the
            # event loop so a slow broker probe cannot stall the scheduler.
            result = await asyncio.to_thread(self._recon.reconcile, scope="startup")
            if result.freeze_raised:
                await self._alert_sink.emit(
                    severity="critical",
                    source="scheduler",
                    message="startup reconciliation raised freeze; scheduler exiting",
                    task_name="reconcile",
                    payload={"cursor": result.cursor},
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
        is_broker_task = task.name == "reconcile"
        # Emit at most one "freeze detected" alert per open freeze event
        # per task. Once the alert for the current freeze is out, poll
        # silently until the freeze clears or a new freeze event opens.
        alerted_freeze_id: str | None = None
        while not self._stop.is_set():
            if not task.run_when_frozen and self._recon_store.has_open_freeze():
                open_freezes = self._recon_store.list_freezes(only_open=True)
                current_freeze_id = (
                    open_freezes[0].event_id if open_freezes else None
                )
                if (
                    current_freeze_id is not None
                    and current_freeze_id != alerted_freeze_id
                ):
                    await self._alert_sink.emit(
                        severity="warning",
                        source="scheduler",
                        message=(
                            f"open freeze detected ({current_freeze_id}); "
                            f"skipping task {task.name} until manual unfreeze"
                        ),
                        task_name=task.name,
                        payload={"freeze_event_id": current_freeze_id},
                    )
                    alerted_freeze_id = current_freeze_id
                await self._sleep(self._short_poll_seconds())
                continue
            alerted_freeze_id = None
            run_started = datetime.now(UTC)
            try:
                await asyncio.wait_for(task.handler(), timeout=task.timeout_seconds)
                self._heartbeats.record_run(
                    task_name=task.name,
                    status="ok",
                    error=None,
                    started_at=run_started,
                    finished_at=datetime.now(UTC),
                )
                self._failure_counters[task.name] = 0
                if is_broker_task:
                    self._broker_tracker.record_success()
                    self._maybe_auto_unfreeze()
            except Exception as exc:  # noqa: BLE001 — record, alert, decide
                self._failure_counters[task.name] += 1
                self._heartbeats.record_run(
                    task_name=task.name,
                    status="error",
                    error=str(exc),
                    started_at=run_started,
                    finished_at=datetime.now(UTC),
                )
                if is_broker_task:
                    await self._broker_tracker.record_failure(error=exc)
                if (
                    self._failure_counters[task.name]
                    >= self._config.max_consecutive_failures
                ):
                    # One durable freeze per failure episode: repeated
                    # failures while the episode's freeze is still open
                    # must not append indistinguishable events. A manual
                    # clear during continued failure still re-freezes,
                    # because no open event matches then.
                    if not self._task_freeze_open(task.name):
                        self._recon_store.raise_freeze(
                            reason=(
                                f"task {task.name} failed "
                                f"{self._failure_counters[task.name]} "
                                "consecutive times"
                            ),
                            source=self._config.on_failure_freeze_source,
                        )
                        await self._alert_sink.emit(
                            severity="critical",
                            source="scheduler",
                            message=(
                                f"task {task.name} exceeded "
                                f"{self._config.max_consecutive_failures} "
                                "failures; auto-freeze raised"
                            ),
                            task_name=task.name,
                            payload={"error": str(exc)},
                        )
                    # Wait for the freeze to clear; stop the loop on
                    # request. While a freeze is open, the top of the loop
                    # will skip task execution and only emit warnings.
                    await self._sleep(task.interval_seconds)
                    continue
            await self._sleep(task.interval_seconds)

    def _task_freeze_open(self, task_name: str) -> bool:
        """True when an open freeze already covers this task's failures.

        The prefix match covers both the current wording and historical
        events, so one outage is never recorded as many freezes.
        """
        prefix = f"task {task_name} failed "
        return any(
            freeze.reason.startswith(prefix)
            for freeze in self._recon_store.list_freezes(only_open=True)
        )

    def _maybe_auto_unfreeze(self) -> None:
        """Lift scheduler failure freezes once their cause is gone.

        PROJECT_GUIDE 5.9: a freeze clears automatically when the cause has
        disappeared and three consecutive reconciliations are clean. Only
        scheduler task-failure freezes qualify here; reconciliation
        differences and foreign-order freezes stay manual forever.
        """
        if not self._three_consecutive_clean_reconciliations():
            return
        for freeze in self._recon_store.list_freezes(only_open=True):
            if freeze.source != self._config.on_failure_freeze_source:
                continue
            if not freeze.reason.startswith("task "):
                continue
            failing_task = freeze.reason.split(" ", 2)[1]
            if self._failure_counters.get(failing_task, 0) != 0:
                continue
            self._recon_store.clear_freeze(
                event_id=freeze.event_id,
                reason=(
                    "auto-unfreeze 5.9: cause cleared and three consecutive "
                    f"clean reconciliations (task {failing_task})"
                ),
                source="auto_unfreeze",
            )

    def _three_consecutive_clean_reconciliations(self) -> bool:
        """True when the three most recent reconciliations all matched."""
        try:
            snapshots = self._recon_store.list_snapshots(limit=3)
        except Exception:  # noqa: BLE001 - a store failure must clear nothing
            return False
        if len(snapshots) < 3:
            return False
        return all(snapshot.all_match for snapshot in snapshots)

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
    on_ai_cycle: Callable[[], Awaitable[None]] | None = None,
    ai_cycle_interval_seconds: float = DEFAULT_OPPORTUNITY_SCAN_SECONDS,
) -> list[ScheduledTask]:
    """Return the default task list (reconcile + opportunity check).

    ``on_reconcile(scope)`` is supplied by the application; it should
    call ``LiveReconciler.reconcile(scope=scope)``.

    ``on_ai_cycle`` is the opportunity check (PROJECT_GUIDE 5.1). When
    supplied, the scheduler registers it under the durable name
    ``ai_daily_cycle`` - the name the soak evaluator counts - at
    ``ai_cycle_interval_seconds``, which the reviewed configuration
    bounds to the guide's 1-5 minute window.

    The task is registered disabled so a bare scheduler stays read-only;
    the runtime enables it when ``ALPHABRIEF_AI_TRADING_ENABLED`` is set.
    """

    async def reconcile_cycle() -> None:
        await on_reconcile("cycle")

    tasks: list[ScheduledTask] = [
        ScheduledTask(
            name="reconcile",
            interval_seconds=300.0,
            handler=reconcile_cycle,
            timeout_seconds=30.0,
            max_retries=1,
            run_when_frozen=True,
        ),
    ]
    if on_ai_cycle is not None:
        tasks.append(
            ScheduledTask(
                name="ai_daily_cycle",
                interval_seconds=ai_cycle_interval_seconds,
                handler=on_ai_cycle,
                # A scan alone is cheap, but an escalating scan runs the
                # whole committee (pre-cycle ingestion plus one run per
                # symbol). Keep the timeout above that worst case so a
                # slow provider never trips the auto-freeze.
                timeout_seconds=900.0,
                # The scan only reads stored facts and the next tick is
                # 1-5 minutes away, so a retry buys nothing. An escalated
                # round is idempotent through its cycle key regardless.
                max_retries=0,
                # GUIDE 5.9: a freeze stops new exposure, not evidence
                # collection; the RiskGate turns an entry into a FROZEN
                # no-trade. Without this the task's own failure episode
                # could never clear.
                run_when_frozen=True,
                enabled=False,  # enabled by the runtime when AI trading is on
            )
        )
    return tasks


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


# Helper: imports kept honest if extends scheduler with
# back-off intervals.
__all__ = [
    "AlertSink",
    "BrokerAvailabilityTracker",
    "HeartbeatStore",
    "OperationsScheduler",
    "ScheduledTask",
    "SchedulerConfig",
    "SchedulerStartupBlockedError",
    "build_default_tasks",
    "CREATE_HEARTBEATS",
    "CREATE_ALERTS",
]
