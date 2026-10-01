"""``alphabrief run``: the single-process runtime (PROJECT_GUIDE 4.1 / 5.1).

One process, one lock, three cooperating loops:

* the FastAPI application (uvicorn) so the dashboard and the CLI can read
  live state over HTTP;
* the operations scheduler (reconciliation, quote polling, shadow scoring,
  backup) with a timeout on every task;
* the clock planner, which decides from the wall clock which scheduled
  events are due — decision rounds, the Friday close-out, the daily report
  and the backup — with the guide's 90-minute catch-up window and
  ``MISSED_WINDOW`` for anything older.

Restart safety comes from durable artifacts, not from memory: a decision
round is "already ran" when the cycle store holds today's cycle for that
round's cycle key, a report when today's report file exists, a backup when
today's backup directory exists. Killing the process therefore cannot
repeat a completed round.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import typer
from alphabrief_core import (
    DEFAULT_CATCH_UP_MINUTES,
    DEFAULT_SCHEDULE,
    PlannedEvent,
    RuntimeLock,
    RuntimeLockError,
    due_events,
)
from alphabrief_core import paths as _paths

run_app = typer.Typer(help="Run the single-process backend (API + scheduler).")

_LOGGER = logging.getLogger("alphabrief.run")

#: How often the clock planner re-evaluates the schedule.
PLANNER_TICK_SECONDS = 60.0

#: Task cadences.
QUOTE_POLL_SECONDS = 60.0
SHADOW_SCORE_SECONDS = 900.0
RECONCILE_SECONDS = 60.0

#: Task timeouts (every task has one, per the guide).
QUOTE_POLL_TIMEOUT = 60.0
SHADOW_SCORE_TIMEOUT = 300.0
REPORT_TIMEOUT = 300.0
BACKUP_TIMEOUT = 600.0
CLOSE_OUT_TIMEOUT = 600.0


def _dump(payload: object, *, pretty: bool = True) -> None:
    import json

    json.dump(payload, sys.stdout, indent=2 if pretty else None, default=str)
    sys.stdout.write("\n")


# ---------------------------------------------------------------------------
# Durable "last run" lookup
# ---------------------------------------------------------------------------


def last_run_instants(
    *, now: datetime, cycle_keys: Sequence[str] = ()
) -> dict[str, datetime]:
    """When each scheduled event last produced its durable artifact.

    Only real artifacts count: a cycle row for the round's key, today's
    report file, today's backup directory, and the recon snapshot for the
    close-out. A missing artifact means "not run".
    """
    from alphabrief_api.db import AiTradingStore

    observed = now.astimezone(UTC)
    runs: dict[str, datetime] = {}

    store = AiTradingStore(db_path=_paths.db_path())
    try:
        for event in DEFAULT_SCHEDULE:
            if event.kind != "decision_round":
                continue
            key = cycle_key_for(event, observed)
            record = store.get_cycle_by_key(key)
            if record is None:
                continue
            created = record.get("created_at")
            if isinstance(created, str):
                runs[event.name] = datetime.fromisoformat(created)
            elif isinstance(created, datetime):
                runs[event.name] = created
    finally:
        store.close()

    report_dir = _paths.daily_reports_dir()
    report_path = report_dir / f"{observed.date().isoformat()}.json"
    if report_path.is_file():
        runs["daily_report"] = datetime.fromtimestamp(
            report_path.stat().st_mtime, tz=UTC
        )
    backup_dir = _paths.backups_dir()
    if backup_dir.is_dir():
        newest = max(
            (p.stat().st_mtime for p in backup_dir.glob("*.manifest.json")),
            default=None,
        )
        if newest is not None:
            runs["backup"] = datetime.fromtimestamp(newest, tz=UTC)
    return runs


def cycle_key_for(event: PlannedEvent, now: datetime) -> str:
    """The idempotency key of one decision round on one UTC day."""
    return f"{event.name}:{now.astimezone(UTC).date().isoformat()}"


# ---------------------------------------------------------------------------
# Task handlers
# ---------------------------------------------------------------------------


def quote_poll_once(*, symbols: Sequence[str]) -> int:
    """Record one live spread sample per symbol (rule 4's history)."""
    from alphabrief_data.quote_samples import QuoteSample, QuoteSampleStore
    from alphabrief_execution.broker.oanda.pricing import (
        PricingRequest,
        fetch_pricing,
    )
    from alphabrief_execution.broker.runtime import (
        build_oanda_paper_client,
        oanda_is_configured,
    )

    if not oanda_is_configured():
        return 0
    client = build_oanda_paper_client()
    batch = fetch_pricing(
        client,
        request=PricingRequest(symbols=tuple(symbols)),
        request_id="runtime-quote-poll",
    )
    now = datetime.now(UTC)
    store = QuoteSampleStore(db_path=_paths.db_path())
    recorded = 0
    try:
        for price in batch.prices:
            if not price.bids or not price.asks:
                continue
            bid = price.bids[0].price
            ask = price.asks[0].price
            if store.record(
                QuoteSample(
                    symbol=price.symbol,
                    captured_at=now,
                    bid=bid,
                    ask=ask,
                    spread=ask - bid,
                    mid=(bid + ask) / Decimal(2),
                )
            ):
                recorded += 1
    finally:
        store.close()
    return recorded


def score_shadow_once(*, now: datetime | None = None) -> int:
    """Score shadow decisions whose 4h/24h horizon has passed.

    Prices come from the live OANDA mid and spread at scoring time, which
    is exactly what PROJECT_GUIDE 5.11 asks for. A symbol without a live
    quote is skipped (the decision stays unscored) rather than scored
    against a guessed price.
    """
    from alphabrief_execution.broker.oanda.pricing import (
        PricingRequest,
        fetch_pricing,
    )
    from alphabrief_execution.broker.runtime import (
        build_oanda_paper_client,
        oanda_is_configured,
    )
    from alphabrief_trader.shadow import directional_return_pct
    from alphabrief_trader.shadow_store import ShadowStore

    observed = now or datetime.now(UTC)
    store = ShadowStore(db_path=_paths.db_path())
    try:
        due = store.due_for_scoring(now=observed)
        if not due:
            return 0
        if not oanda_is_configured():
            return 0
        symbols = sorted({str(row["symbol"]) for row in due})
        client = build_oanda_paper_client()
        batch = fetch_pricing(
            client,
            request=PricingRequest(symbols=tuple(symbols)),
            request_id="runtime-shadow-score",
        )
        prices = {price.symbol: price for price in batch.prices}
        scored = 0
        for row in due:
            price = prices.get(str(row["symbol"]))
            if price is None or not price.bids or not price.asks:
                continue
            exit_mid = (price.bids[0].price + price.asks[0].price) / Decimal(2)
            spread = price.asks[0].price - price.bids[0].price
            entry_mid = row.get("entry_mid")
            if entry_mid is None:
                continue
            from alphabrief_trader.shadow import ShadowScore

            horizon = int(row["horizon_hours"])
            scored += int(
                store.save_score(
                    ShadowScore(
                        cycle_id=str(row["cycle_id"]),
                        symbol=str(row["symbol"]),
                        benchmark=str(row["benchmark"]),
                        horizon_hours=horizon,
                        return_pct=directional_return_pct(
                            side=str(row["side"]),  # type: ignore[arg-type]
                            entry_mid=Decimal(str(entry_mid)),
                            exit_mid=exit_mid,
                            spread_at_exit=spread,
                        ),
                        exit_mid=exit_mid,
                        spread_at_exit=spread,
                        scored_at=observed,
                    )
                )
            )
        return scored
    finally:
        store.close()


def write_report_once(*, trading_day: str | None = None) -> tuple[Path, Path]:
    """Generate today's daily report in-process (no CLI round trip)."""
    from alphabrief_api.db import AiTradingStore
    from alphabrief_api.db.model_call import ModelCallStore
    from alphabrief_trader.daily_report import DailyReportData, write_daily_report

    from alphabrief_cli.report_commands import (
        _attempts_for_day,
        _cycles_for_day,
        _doctor_summary,
        _equity_snapshot,
        _market_freshness,
        _model_calls_for_day,
        _reconciliation,
    )
    from alphabrief_cli.scheduler_commands import _ai_scheduler_universe

    day = trading_day or datetime.now(UTC).date().isoformat()
    store = AiTradingStore(db_path=_paths.db_path())
    model_calls = ModelCallStore(db_path=_paths.db_path())
    from alphabrief_trader.shadow_store import ShadowStore

    shadow = ShadowStore(db_path=_paths.db_path())
    try:
        reconciliation, freezes = _reconciliation(day)
        data = DailyReportData(
            trading_day=day,
            generated_at=datetime.now(UTC),
            cycles=_cycles_for_day(store, day),
            attempts=_attempts_for_day(store, day),
            model_calls=_model_calls_for_day(model_calls, day),
            shadow_decisions=shadow.list_decisions(limit=10000),
            shadow_stats=shadow.scoreboard(),
            reconciliation=reconciliation,
            freezes=freezes,
            equity=_equity_snapshot(day),
            market_freshness=_market_freshness(_ai_scheduler_universe()),
            doctor_summary=_doctor_summary(),
        )
        return write_daily_report(data)
    finally:
        shadow.close()
        model_calls.close()
        store.close()


def backup_once() -> str:
    """Create one backup and apply retention (PROJECT_GUIDE 5.1)."""
    from alphabrief_api.db.backup import apply_retention, create_backup

    manifest = create_backup(
        db_path=_paths.db_path(),
        backup_dir=_paths.backups_dir(),
        blueprint_version="v1.0.0",
    )
    apply_retention(_paths.backups_dir())
    return str(getattr(manifest, "backup_id", "backup"))


def close_out_once(*, reason: str) -> int:
    """Close every open position (Friday close-out / kill switch)."""
    from alphabrief_execution.broker.oanda.position_ops import PositionOpsClient
    from alphabrief_execution.broker.runtime import (
        build_oanda_paper_client,
        oanda_is_configured,
    )

    from alphabrief_cli.cycle_commands import (
        _close_through_the_cycle,
        _risk_sources,
    )

    if not oanda_is_configured():
        return 0
    client = build_oanda_paper_client()
    positions = PositionOpsClient(client).list_positions().positions
    closed = 0
    for position in positions:
        units = position.long_units - position.short_units
        if units == 0:
            continue
        mark = _risk_sources((position.instrument,)).mid_price(position.instrument)
        if mark is None:
            continue
        result = _close_through_the_cycle(
            instrument=position.instrument,
            position_units=units,
            reference_price=mark,
            reason=reason,
            trading="on",
        )
        if result.get("closed"):
            closed += 1
    return closed


# ---------------------------------------------------------------------------
# Runtime composition
# ---------------------------------------------------------------------------


class Runtime:
    """The composed single-process runtime."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        universe: Sequence[str],
        catch_up_minutes: int = DEFAULT_CATCH_UP_MINUTES,
        clock: Callable[[], datetime] | None = None,
        decision_round: Callable[[str], Any] | None = None,
        report_writer: Callable[[], Any] | None = None,
        backup_runner: Callable[[], Any] | None = None,
        close_out: Callable[[str], Any] | None = None,
        quote_poller: Callable[[], Any] | None = None,
        shadow_scorer: Callable[[], Any] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._universe = tuple(universe)
        self._catch_up_minutes = catch_up_minutes
        self._clock = clock or (lambda: datetime.now(UTC))
        self._decision_round = decision_round or self._default_decision_round
        self._report_writer = report_writer or (lambda: write_report_once())
        self._backup_runner = backup_runner or (lambda: backup_once())
        self._close_out = close_out or (lambda reason: close_out_once(reason=reason))
        self._quote_poller = quote_poller or (
            lambda: quote_poll_once(symbols=self._universe)
        )
        self._shadow_scorer = shadow_scorer or (lambda: score_shadow_once())
        self._stop = asyncio.Event()
        self._server: Any | None = None
        self._scheduler: Any | None = None
        self._planner_log: list[dict[str, Any]] = []

    # -- handlers ---------------------------------------------------------

    def _default_decision_round(self, cycle_key: str) -> Any:
        from alphabrief_cli.scheduler_commands import _ai_cycle_factory

        handler = _ai_cycle_factory(db_path=_paths.data_dir())
        return handler(cycle_key=cycle_key)

    async def _run_decision_round(self, event: PlannedEvent) -> None:
        key = cycle_key_for(event, self._clock())
        _LOGGER.info("runtime: decision round %s (cycle key %s)", event.name, key)
        result = self._decision_round(key)
        if asyncio.iscoroutine(result):
            await result

    async def _run_report(self) -> None:
        _LOGGER.info("runtime: daily report")
        result = await asyncio.to_thread(self._report_writer)
        _LOGGER.info("runtime: report written %s", result)

    async def _run_backup(self) -> None:
        _LOGGER.info("runtime: backup")
        result = await asyncio.to_thread(self._backup_runner)
        _LOGGER.info("runtime: backup %s", result)

    async def _run_close_out(self) -> None:
        _LOGGER.info("runtime: Friday close-out")
        result = await asyncio.to_thread(
            self._close_out, "Friday 19:00 UTC weekend close-out"
        )
        _LOGGER.info("runtime: closed %s position(s)", result)

    async def _run_quote_poll(self) -> None:
        recorded = await asyncio.to_thread(self._quote_poller)
        if recorded:
            _LOGGER.info("runtime: recorded %s spread sample(s)", recorded)

    async def _run_shadow_score(self) -> None:
        scored = await asyncio.to_thread(self._shadow_scorer)
        if scored:
            _LOGGER.info("runtime: scored %s shadow decision(s)", scored)

    # -- planner ----------------------------------------------------------

    async def planner_tick(self) -> None:
        """Dispatch whatever the clock says is due right now."""
        now = self._clock()
        runs = await asyncio.to_thread(last_run_instants, now=now)
        for verdict in due_events(
            now=now, last_runs=runs, catch_up_minutes=self._catch_up_minutes
        ):
            self._planner_log.append(verdict.to_dict())
            event = next(
                item for item in DEFAULT_SCHEDULE if item.name == verdict.name
            )
            if verdict.kind == "decision_round":
                await self._run_decision_round(event)
            elif verdict.kind == "report":
                await self._run_report()
            elif verdict.kind == "backup":
                await self._run_backup()
            elif verdict.kind == "close_out":
                await self._run_close_out()
        missed = [
            verdict.to_dict()
            for verdict in _missed(
                now=now, runs=runs, catch_up_minutes=self._catch_up_minutes
            )
        ]
        if missed:
            _LOGGER.warning("runtime: missed windows: %s", missed)

    async def planner_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.planner_tick()
            except Exception:  # noqa: BLE001 - one bad tick must not stop the loop
                _LOGGER.exception("runtime: planner tick failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=PLANNER_TICK_SECONDS
                )
            except TimeoutError:
                continue

    # -- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        import uvicorn
        from alphabrief_api.main import create_app

        app = create_app()
        config = uvicorn.Config(
            app, host=self._host, port=self._port, log_level="info"
        )
        self._server = uvicorn.Server(config)
        self._scheduler = await self._build_scheduler()

    async def _build_scheduler(self) -> Any:
        from alphabrief_execution.operations.scheduler import (
            OperationsScheduler,
            ScheduledTask,
            SchedulerConfig,
            build_default_tasks,
        )

        from alphabrief_cli.scheduler_commands import (
            _open_heartbeat_store,
            _open_recon_store,
            _reconcile_runner,
        )

        heartbeats = _open_heartbeat_store()
        recon_store = _open_recon_store()
        from alphabrief_execution.operations.scheduler import AlertSink

        alert_sink = AlertSink(heartbeat_store=heartbeats)

        async def _on_reconcile(scope: str) -> None:
            await asyncio.to_thread(_reconcile_runner(recon_store), scope)

        tasks = build_default_tasks(on_reconcile=_on_reconcile, on_ai_cycle=None)
        tasks = [
            replace(task, interval_seconds=RECONCILE_SECONDS)
            if task.name == "reconcile"
            else task
            for task in tasks
        ]
        tasks.extend(
            [
                ScheduledTask(
                    name="quote_poll",
                    interval_seconds=QUOTE_POLL_SECONDS,
                    handler=self._run_quote_poll,
                    timeout_seconds=QUOTE_POLL_TIMEOUT,
                    max_retries=0,
                ),
                ScheduledTask(
                    name="shadow_score",
                    interval_seconds=SHADOW_SCORE_SECONDS,
                    handler=self._run_shadow_score,
                    timeout_seconds=SHADOW_SCORE_TIMEOUT,
                    max_retries=0,
                ),
            ]
        )
        return OperationsScheduler(
            tasks=tasks,
            heartbeat_store=heartbeats,
            alert_sink=alert_sink,
            recon_store=recon_store,
            config=SchedulerConfig(reconcile_on_start=False),
            clock=self._clock,
        )

    async def serve(self) -> None:
        assert self._server is not None
        await self._server.serve()

    def request_stop(self) -> None:
        self._stop.set()
        if self._scheduler is not None:
            self._scheduler.request_stop()
        if self._server is not None:
            self._server.should_exit = True

    async def run_forever(self) -> None:
        assert self._scheduler is not None
        await asyncio.gather(
            self.serve(),
            self._scheduler.run(),
            self.planner_loop(),
        )


def _missed(
    *, now: datetime, runs: dict[str, datetime], catch_up_minutes: int
) -> list[Any]:
    from alphabrief_core import evaluate_schedule

    return [
        verdict
        for verdict in evaluate_schedule(
            now=now, last_runs=runs, catch_up_minutes=catch_up_minutes
        )
        if verdict.reason == "missed_window"
    ]


@run_app.command("run")
def run_cmd(
    host: str = typer.Option("127.0.0.1", "--host", help="API bind address."),
    port: int = typer.Option(8000, "--port", help="API port."),
    catch_up_minutes: int = typer.Option(  # noqa: B008
        DEFAULT_CATCH_UP_MINUTES,
        "--catch-up-minutes",
        help="How late a missed round may still run (PROJECT_GUIDE 5.1).",
    ),
    pretty: bool = typer.Option(True, "--pretty/--compact"),  # noqa: B008
) -> None:
    """Start the API and the scheduler in one locked process."""
    from alphabrief_cli.scheduler_commands import (
        _ai_scheduler_universe,
        _configure_logging,
        _refuse_if_live_trading_unlocked,
        trading_mode,
    )

    _refuse_if_live_trading_unlocked()
    _configure_logging()
    universe = _ai_scheduler_universe()
    lock = RuntimeLock()
    try:
        lock.acquire()
    except RuntimeLockError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)

    runtime = Runtime(
        host=host,
        port=port,
        universe=universe,
        catch_up_minutes=catch_up_minutes,
    )
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(runtime.start())

        def _on_signal(signum: int, frame: object) -> None:
            _LOGGER.info("runtime: stop requested (signal %s)", signum)
            runtime.request_stop()

        signal.signal(signal.SIGINT, _on_signal)
        signal.signal(signal.SIGTERM, _on_signal)
        _dump(
            {
                "status": "running",
                "api": f"http://{host}:{port}",
                "lock": str(lock.path),
                "trading_mode": trading_mode(),
                "universe": list(universe),
                "catch_up_minutes": catch_up_minutes,
                "pid": os.getpid(),
            },
            pretty=pretty,
        )
        loop.run_until_complete(runtime.run_forever())
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        lock.release()
        _dump({"status": "stopped"}, pretty=pretty)


__all__ = [
    "Runtime",
    "backup_once",
    "close_out_once",
    "cycle_key_for",
    "last_run_instants",
    "quote_poll_once",
    "run_app",
    "score_shadow_once",
    "write_report_once",
]
