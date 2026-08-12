"""Operations scheduler tests.

Exercises:
- startup reconciliation that raises a freeze blocks the main loop
- a single failing task auto-freezes after ``max_consecutive_failures``
- heartbeats are recorded per task
- an existing freeze prevents subsequent task execution
- alert payloads scrub forbidden credential fields
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alphabrief_execution.broker.port import (
    AccountSnapshot,
    BrokerAdapter,
    BrokerHealth,
    BrokerOrderSide,
    BrokerOrderStatus,
    BrokerOrderType,
    CancelResult,
    Fill,
    OrderState,
    Position,
    SubmitRequest,
    SubmitResult,
)
from alphabrief_execution.broker.recon_store import BrokerReconStore
from alphabrief_execution.broker.reconciliation import (
    ReconcilerConfig,
    ReconciliationRunner,
)
from alphabrief_execution.operations.scheduler import (
    AlertSink,
    HeartbeatStore,
    OperationsScheduler,
    ScheduledTask,
    SchedulerConfig,
    SchedulerStartupBlockedError,
    build_default_tasks,
)


class _StubAdapter(BrokerAdapter):
    async def health(self) -> BrokerHealth:
        return BrokerHealth(
            healthy=True, detail="ok", checked_at=datetime(2026, 6, 20, tzinfo=UTC)
        )

    async def submit(
        self, request: SubmitRequest, *, client_order_id: str
    ) -> SubmitResult:
        return SubmitResult(
            broker_order_id="b",
            client_order_id=client_order_id,
            status=BrokerOrderStatus.NEW,
            accepted_at=datetime(2026, 6, 20, tzinfo=UTC),
        )

    async def cancel(self, broker_order_id: str) -> CancelResult:
        return CancelResult(
            broker_order_id=broker_order_id,
            status=BrokerOrderStatus.CANCELLED,
            cancelled_at=datetime(2026, 6, 20, tzinfo=UTC),
        )

    async def get_order(self, broker_order_id: str) -> OrderState:
        raise ValueError("nope")

    async def list_orders(
        self, status: BrokerOrderStatus | None = None
    ) -> list[OrderState]:
        return []

    async def list_fills(self, since: datetime | None = None) -> list[Fill]:
        return []

    async def get_positions(self) -> list[Position]:
        return []

    async def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(
            account_id="a",
            cash="0",  # type: ignore[arg-type]
            equity="0",  # type: ignore[arg-type]
            buying_power="0",  # type: ignore[arg-type]
            currency="USD",
            captured_at=datetime(2026, 6, 20, tzinfo=UTC),
        )


def _ok_task() -> ScheduledTask:
    async def handler() -> None:
        return None

    return ScheduledTask(
        name="noop",
        interval_seconds=0.05,
        handler=handler,
        timeout_seconds=0.5,
        max_retries=2,
    )


def _failing_task(failures: int) -> ScheduledTask:
    state = {"calls": 0}

    async def handler() -> None:
        state["calls"] += 1
        if state["calls"] <= failures:
            raise RuntimeError("boom")

    return ScheduledTask(
        name="flaky",
        interval_seconds=0.05,
        handler=handler,
        timeout_seconds=0.5,
        max_retries=2,
    )


def _build_scheduler(
    tmp_path: Path,
    *,
    tasks: list[ScheduledTask],
    config: SchedulerConfig | None = None,
    reconciler_config: ReconcilerConfig | None = None,
) -> tuple[OperationsScheduler, HeartbeatStore, BrokerReconStore, AlertSink]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    heartbeats = HeartbeatStore(db_path=tmp_path / "sched.db")
    recon_store = BrokerReconStore(db_path=tmp_path / "recon.db")
    adapter = _StubAdapter()
    runner = ReconciliationRunner(
        adapter=adapter, store=recon_store, config=reconciler_config
    )
    alert_sink = AlertSink(heartbeat_store=heartbeats)
    scheduler = OperationsScheduler(
        tasks=tasks,
        heartbeat_store=heartbeats,
        alert_sink=alert_sink,
        recon_runner=runner,
        recon_store=recon_store,
        config=config or SchedulerConfig(max_consecutive_failures=2),
    )
    return scheduler, heartbeats, recon_store, alert_sink


def _run(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_startup_reconciliation_freeze_blocks_scheduler(tmp_path: Path) -> None:
    # Pre-populate the recon store at the path the scheduler will use.
    tmp_path.mkdir(parents=True, exist_ok=True)
    recon_store = BrokerReconStore(db_path=tmp_path / "recon.db")
    recon_store.close()

    scheduler, heartbeats, recon_store, _ = _build_scheduler(
        tmp_path,
        tasks=[_ok_task()],
    )
    # Replace the runner's adapter with one that has an orphan order
    # so startup reconciliation raises a freeze.
    orphan_adapter = _OrphanAdapter()
    scheduler._recon = ReconciliationRunner(
        adapter=orphan_adapter,
        store=scheduler._recon_store,
    )
    try:
        with pytest.raises(SchedulerStartupBlockedError):
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(scheduler.run())
            finally:
                loop.close()
    finally:
        heartbeats.close()
        recon_store.close()


class _OrphanAdapter(BrokerAdapter):
    """Adapter that reports one orphan order — recon flags it as diff."""

    async def health(self) -> BrokerHealth:
        return BrokerHealth(
            healthy=True, detail="ok", checked_at=datetime(2026, 6, 20, tzinfo=UTC)
        )

    async def submit(
        self, request: SubmitRequest, *, client_order_id: str
    ) -> SubmitResult:
        raise NotImplementedError

    async def cancel(self, broker_order_id: str) -> CancelResult:
        raise NotImplementedError

    async def get_order(self, broker_order_id: str) -> OrderState:
        raise NotImplementedError

    async def list_orders(
        self, status: BrokerOrderStatus | None = None
    ) -> list[OrderState]:
        return [
            OrderState(
                broker_order_id="orphan",
                client_order_id="orphan-cli",
                symbol="SPY",
                side=BrokerOrderSide.BUY,
                order_type=BrokerOrderType.MARKET,
                quantity=Decimal("1"),
                filled_quantity=Decimal("0"),
                status=BrokerOrderStatus.NEW,
                submitted_at=datetime(2026, 6, 20, tzinfo=UTC),
                updated_at=datetime(2026, 6, 20, tzinfo=UTC),
            )
        ]

    async def list_fills(self, since: datetime | None = None) -> list[Fill]:
        return []

    async def get_positions(self) -> list[Position]:
        return []

    async def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(
            account_id="orphan",
            cash=Decimal("1000"),
            equity=Decimal("1000"),
            buying_power=Decimal("2000"),
            currency="USD",
            captured_at=datetime(2026, 6, 20, tzinfo=UTC),
        )


def test_failing_task_auto_freezes_after_max_consecutive_failures(
    tmp_path: Path,
) -> None:
    task = _failing_task(failures=10)
    scheduler, heartbeats, recon_store, _ = _build_scheduler(
        tmp_path,
        tasks=[task],
        config=SchedulerConfig(max_consecutive_failures=2),
    )

    async def drive() -> None:
        await asyncio.sleep(0.3)
        scheduler.request_stop()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_drive_and_run(scheduler, drive))
    finally:
        loop.close()
    try:
        assert recon_store.has_open_freeze() is True
        assert heartbeats.last_run_at("flaky") is not None
    finally:
        heartbeats.close()
        recon_store.close()


def test_ok_task_records_heartbeat(tmp_path: Path) -> None:
    scheduler, heartbeats, recon_store, _ = _build_scheduler(
        tmp_path, tasks=[_ok_task()]
    )

    async def drive() -> None:
        await asyncio.sleep(0.2)
        scheduler.request_stop()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_drive_and_run(scheduler, drive))
    finally:
        loop.close()
    try:
        assert heartbeats.last_run_at("noop") is not None
    finally:
        heartbeats.close()
        recon_store.close()


def test_existing_freeze_blocks_task_execution(tmp_path: Path) -> None:
    # First raise a freeze so the scheduler sees it during the first tick.
    recon_store = BrokerReconStore(db_path=tmp_path / "recon.db")
    recon_store.raise_freeze(reason="external", source="test")
    recon_store.close()

    scheduler, heartbeats, recon_store, _ = _build_scheduler(
        tmp_path,
        tasks=[_ok_task()],
        config=SchedulerConfig(reconcile_on_start=False, max_consecutive_failures=99),
    )

    async def drive() -> None:
        await asyncio.sleep(0.2)
        scheduler.request_stop()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_drive_and_run(scheduler, drive))
    finally:
        loop.close()
    try:
        # Heartbeat is None because the task was skipped while a freeze was open.
        assert heartbeats.last_run_at("noop") is None
    finally:
        heartbeats.close()
        recon_store.close()


async def _drive_and_run(scheduler: OperationsScheduler, drive: Any) -> None:
    """Run the scheduler and a co-driver on a single event loop."""
    run_task = asyncio.create_task(scheduler.run())
    await drive()
    scheduler.request_stop()
    try:
        await run_task
    except SchedulerStartupBlockedError:
        pass


def test_alert_sink_scrubs_forbidden_credentials(tmp_path: Path) -> None:
    heartbeats = HeartbeatStore(db_path=tmp_path / "sched.db")
    sink = AlertSink(heartbeat_store=heartbeats)
    try:
        alert_id = _run(
            sink.emit(
                severity="warning",
                source="scheduler",
                message="leaked",
                payload={
                    "api_key": "AKIA...",
                    "secret": "shhh",
                    "token": "t",
                    "ok": "kept",
                },
            )
        )
        alerts = heartbeats.list_alerts()
        assert alerts[0]["alert_id"] == alert_id
        assert alerts[0]["message"] == "leaked"
    finally:
        heartbeats.close()


def test_build_default_tasks_returns_reconcile_task() -> None:
    async def reconcile_cycle(scope: str) -> None:
        return None

    tasks = build_default_tasks(on_reconcile=reconcile_cycle)
    assert [t.name for t in tasks] == ["reconcile"]
    assert tasks[0].interval_seconds == 300.0


def test_build_default_tasks_ai_cycle_timeout_covers_committee_runtime() -> None:
    async def reconcile_cycle(scope: str) -> None:
        return None

    async def ai_cycle() -> None:
        return None

    tasks = build_default_tasks(on_reconcile=reconcile_cycle, on_ai_cycle=ai_cycle)
    by_name = {t.name: t for t in tasks}
    assert "ai_daily_cycle" in by_name
    ai = by_name["ai_daily_cycle"]
    assert ai.enabled is False
    assert ai.interval_seconds == 86_400.0
    # Must comfortably exceed pre-cycle ingestion plus one committee run
    # per symbol (4 role calls, up to 30s model timeout each); a too-short
    # timeout would auto-freeze the scheduler on a slow provider.
    assert ai.timeout_seconds >= 600.0


def test_freeze_warning_alert_emitted_once_per_freeze_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An open freeze blocks task execution. The scheduler must alert once
    # per freeze event per task, then poll silently — not write a new
    # alert on every short-poll tick (previous behavior flooded the
    # alerts table with ~1.3M rows during a 6-week freeze).
    recon_store = BrokerReconStore(db_path=tmp_path / "recon.db")
    first = recon_store.raise_freeze(reason="external", source="test")
    recon_store.close()

    scheduler, heartbeats, recon_store, _ = _build_scheduler(
        tmp_path,
        tasks=[_ok_task()],
        config=SchedulerConfig(
            reconcile_on_start=False, max_consecutive_failures=99
        ),
    )
    monkeypatch.setattr(scheduler, "_short_poll_seconds", lambda: 0.02)

    async def drive() -> None:
        # Several short-poll iterations while frozen, then unfreeze and
        # raise a second freeze to confirm a new event alerts again.
        await asyncio.sleep(0.12)
        recon_store.clear_freeze(
            event_id=first.event_id, reason="test unfreeze"
        )
        recon_store.raise_freeze(reason="second", source="test")
        await asyncio.sleep(0.12)
        scheduler.request_stop()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_drive_and_run(scheduler, drive))
    finally:
        loop.close()
    try:
        alerts = heartbeats.list_alerts(limit=100)
        freeze_alerts = [a for a in alerts if "open freeze detected" in a["message"]]
        # One alert for the first freeze event, one for the second —
        # despite ~12 short-poll iterations in between.
        assert len(freeze_alerts) == 2
        messages = " | ".join(a["message"] for a in freeze_alerts)
        assert first.event_id in messages
        assert "freeze_" in messages
        # The task never ran while frozen.
        assert heartbeats.last_run_at("noop") is None
    finally:
        heartbeats.close()
        recon_store.close()


def test_scheduled_task_rejects_invalid_interval() -> None:
    async def handler() -> None:
        return None

    with pytest.raises(ValueError, match="interval_seconds must be positive"):
        ScheduledTask(name="bad", interval_seconds=0, handler=handler)


def test_scheduled_task_rejects_negative_max_retries() -> None:
    async def handler() -> None:
        return None

    with pytest.raises(ValueError, match="max_retries must be non-negative"):
        ScheduledTask(name="bad", interval_seconds=1, handler=handler, max_retries=-1)


def test_heartbeat_store_list_heartbeats_empty(tmp_path: Path) -> None:
    heartbeats = HeartbeatStore(db_path=tmp_path / "sched.db")
    try:
        assert heartbeats.list_heartbeats() == []
    finally:
        heartbeats.close()


def test_heartbeat_store_list_heartbeats_after_record_run(tmp_path: Path) -> None:
    heartbeats = HeartbeatStore(db_path=tmp_path / "sched.db")
    try:
        heartbeats.record_run(task_name="reconcile", status="ok", error=None)
        heartbeats.record_run(task_name="other", status="error", error="boom")
        rows = heartbeats.list_heartbeats()
        assert len(rows) == 2
        names = {row["task_name"] for row in rows}
        assert names == {"reconcile", "other"}
        by_name = {row["task_name"]: row for row in rows}
        assert by_name["reconcile"]["last_status"] == "ok"
        assert by_name["reconcile"]["last_error"] is None
        assert by_name["reconcile"]["run_count"] == 1
        assert by_name["other"]["last_status"] == "error"
        assert by_name["other"]["last_error"] == "boom"
    finally:
        heartbeats.close()


def test_heartbeat_store_list_heartbeats_orders_by_last_run_desc(
    tmp_path: Path,
) -> None:
    heartbeats = HeartbeatStore(db_path=tmp_path / "sched.db")
    try:
        heartbeats.record_run(task_name="first", status="ok", error=None)
        # Force a later last_run_at for the second task so the DESC
        # ordering is observable. record_run uses datetime.now(UTC);
        # a tiny sleep is enough to make the timestamps distinct.
        import time as _time

        _time.sleep(0.01)
        heartbeats.record_run(task_name="second", status="ok", error=None)
        rows = heartbeats.list_heartbeats()
        assert [row["task_name"] for row in rows] == ["second", "first"]
    finally:
        heartbeats.close()


# ---------------------------------------------------------------------------
# Phase 30 task #4: BrokerAvailabilityTracker emits a clear
# "broker unreachable" alert after N consecutive failures, and only
# once per outage. A success resets the counter.
# ---------------------------------------------------------------------------


def test_broker_tracker_emits_alert_after_threshold(
    tmp_path: Path,
) -> None:
    from alphabrief_execution.broker.errors import BrokerTransientError
    from alphabrief_execution.operations.scheduler import BrokerAvailabilityTracker

    heartbeats = HeartbeatStore(db_path=tmp_path / "sched.db")
    try:
        sink = AlertSink(heartbeat_store=heartbeats)
        tracker = BrokerAvailabilityTracker(
            threshold=3, alert_sink=sink, task_name="reconcile"
        )

        # Two failures — below threshold, no alert yet.
        _run(tracker.record_failure(error=BrokerTransientError("ssl 1")))
        _run(tracker.record_failure(error=BrokerTransientError("ssl 2")))
        assert heartbeats.list_alerts(limit=10) == []
        assert tracker.consecutive_failures == 2

        # Third failure crosses the threshold → one alert.
        _run(tracker.record_failure(error=BrokerTransientError("ssl 3")))
        alerts_after = heartbeats.list_alerts(limit=10)
        assert len(alerts_after) == 1
        msg = alerts_after[0]["message"]
        assert "broker unreachable" in msg
        assert "3 consecutive attempts" in msg

        # A fourth failure must NOT re-alert (one alert per outage).
        _run(tracker.record_failure(error=BrokerTransientError("ssl 4")))
        alerts_extra = heartbeats.list_alerts(limit=10)
        assert len(alerts_extra) == 1
    finally:
        heartbeats.close()


def test_broker_tracker_success_resets_counter(
    tmp_path: Path,
) -> None:
    from alphabrief_execution.broker.errors import BrokerTransientError
    from alphabrief_execution.operations.scheduler import BrokerAvailabilityTracker

    heartbeats = HeartbeatStore(db_path=tmp_path / "sched.db")
    try:
        sink = AlertSink(heartbeat_store=heartbeats)
        tracker = BrokerAvailabilityTracker(
            threshold=2, alert_sink=sink, task_name="reconcile"
        )
        _run(tracker.record_failure(error=BrokerTransientError("ssl 1")))
        _run(tracker.record_failure(error=BrokerTransientError("ssl 2")))
        assert tracker.consecutive_failures == 2
        alerts_first = heartbeats.list_alerts(limit=10)
        assert len(alerts_first) == 1

        # First success resets the outage tracker.
        tracker.record_success()
        assert tracker.consecutive_failures == 0

        # Two more failures re-arm and emit a second alert.
        _run(tracker.record_failure(error=BrokerTransientError("ssl again 1")))
        _run(tracker.record_failure(error=BrokerTransientError("ssl again 2")))
        alerts_second = heartbeats.list_alerts(limit=10)
        assert len(alerts_second) == 2
    finally:
        heartbeats.close()


def test_broker_tracker_ignores_unrelated_exceptions(
    tmp_path: Path,
) -> None:
    from alphabrief_execution.operations.scheduler import BrokerAvailabilityTracker

    heartbeats = HeartbeatStore(db_path=tmp_path / "sched.db")
    try:
        sink = AlertSink(heartbeat_store=heartbeats)
        tracker = BrokerAvailabilityTracker(threshold=2, alert_sink=sink)
        # ValueError is not a broker-shaped exception — should not
        # count toward the outage threshold.
        _run(tracker.record_failure(error=ValueError("not a broker problem")))
        _run(tracker.record_failure(error=ValueError("still not")))
        assert tracker.consecutive_failures == 0
        assert heartbeats.list_alerts(limit=10) == []
    finally:
        heartbeats.close()


def test_broker_tracker_rejects_non_positive_threshold(
    tmp_path: Path,
) -> None:
    from alphabrief_execution.operations.scheduler import BrokerAvailabilityTracker

    heartbeats = HeartbeatStore(db_path=tmp_path / "sched.db")
    try:
        sink = AlertSink(heartbeat_store=heartbeats)
        with pytest.raises(ValueError):
            BrokerAvailabilityTracker(threshold=0, alert_sink=sink)
    finally:
        heartbeats.close()


def test_scheduler_uses_default_broker_tracker_when_omitted(
    tmp_path: Path,
) -> None:
    """The scheduler must wire a default BrokerAvailabilityTracker so
    task-level broker failures feed the outage counter without callers
    having to construct one.
    """
    scheduler, heartbeats, recon_store, _ = _build_scheduler(
        tmp_path,
        tasks=[_ok_task()],
    )
    try:
        assert scheduler._broker_tracker is not None
        assert scheduler._broker_tracker._threshold == (
            SchedulerConfig().broker_unavailable_alert_threshold
        )
    finally:
        heartbeats.close()
        recon_store.close()
