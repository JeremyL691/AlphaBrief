"""CLI subcommands for the operations scheduler.

Commands
--------

- ``scheduler status``     — aggregate heartbeat / freeze / alert counts.
- ``scheduler heartbeats`` — list per-task heartbeat rows.
- ``scheduler alerts``     — list recent alerts (--limit N).
- ``scheduler tasks``      — list the static default task set.
- ``scheduler freezes``    — list currently-open broker freezes.
- ``scheduler run``        — start the scheduler as a foreground process.

The read-only commands proxy through the API when the server is
running and fall back to the local ``HeartbeatStore`` /
``BrokerReconStore`` otherwise. ``scheduler run`` is CLI-only and
launches the long-running async event loop in-process; it never
proxies through the API because that would block an API worker.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import typer
from alphabrief_execution import (
    FillSimulator,
    OrderRouter,
    PaperBroker,
    PortfolioState,
)
from alphabrief_execution.broker.port import (
    AccountSnapshot,
    BrokerAdapter,
    BrokerHealth,
    BrokerOrderStatus,
    CancelResult,
    Fill,
    OrderState,
    Position,
    SubmitRequest,
    SubmitResult,
)
from alphabrief_execution.broker.recon_store import BrokerReconStore
from alphabrief_execution.broker.reconciliation import ReconciliationRunner
from alphabrief_execution.operations.scheduler import (
    AlertSink,
    HeartbeatStore,
    OperationsScheduler,
    SchedulerConfig,
    SchedulerStartupBlockedError,
    build_default_tasks,
)
from alphabrief_models import FakeProviderAdapter, ModelGateway
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_trader import (
    DailyTradingCycle,
    DisciplineConfig,
    MarketSnapshot,
    TradingCommittee,
    is_ai_trading_enabled,
)

from alphabrief_cli.api_client import is_api_running

scheduler_app = typer.Typer(help="Inspect and run the operations scheduler.")


# ---------------------------------------------------------------------------
# Local store helpers (used when the API is not running)
# ---------------------------------------------------------------------------


def _open_heartbeat_store() -> HeartbeatStore:
    db_dir_str = os.environ.get("ALPHABRIEF_DATA_DIR")
    if db_dir_str:
        db_dir = Path(db_dir_str)
        db_dir.mkdir(parents=True, exist_ok=True)
        return HeartbeatStore(db_path=db_dir / "alphabrief.db")
    return HeartbeatStore()


def _open_recon_store() -> BrokerReconStore:
    db_dir_str = os.environ.get("ALPHABRIEF_DATA_DIR")
    if db_dir_str:
        db_dir = Path(db_dir_str)
        db_dir.mkdir(parents=True, exist_ok=True)
        return BrokerReconStore(db_path=db_dir / "alphabrief.db")
    return BrokerReconStore()


def _dump(payload: object, *, pretty: bool, default: bool = False) -> None:
    """Write JSON to stdout, formatting Decimal/datetime as strings when needed."""
    json.dump(
        payload,
        sys.stdout,
        indent=2 if pretty else None,
        sort_keys=True,
        default=str if default else None,
    )
    sys.stdout.write("\n")


def _api_url(path: str) -> str:
    base = os.environ.get("ALPHABRIEF_API_URL", "http://127.0.0.1:8000")
    return f"{base}{path}"


def _read_api_json(path: str) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(_api_url(path), timeout=5) as response:
            return cast(dict[str, Any], json.loads(response.read().decode("utf-8")))
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print(f"error: failed to reach {_api_url(path)}: {exc}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@scheduler_app.command("status")
def status_cmd(
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
    ),
) -> None:
    """Print aggregate scheduler state (heartbeats / freezes / alerts)."""
    if is_api_running():
        _dump(_read_api_json("/api/v1/scheduler/status"), pretty=pretty)
        return

    heartbeats = _open_heartbeat_store()
    recon = _open_recon_store()
    try:
        heartbeats_rows = heartbeats.list_heartbeats()
        open_freezes = recon.list_freezes(only_open=True)
        recent_alerts = heartbeats.list_alerts(limit=500)
        payload = {
            "heartbeat_count": len(heartbeats_rows),
            "open_freeze_count": len(open_freezes),
            "alerts_total": len(recent_alerts),
            "running": False,
        }
    finally:
        heartbeats.close()
        recon.close()
    _dump(payload, pretty=pretty)


# ---------------------------------------------------------------------------
# heartbeats
# ---------------------------------------------------------------------------


@scheduler_app.command("heartbeats")
def heartbeats_cmd(
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
    ),
) -> None:
    """List one row per registered task with last-run state."""
    if is_api_running():
        _dump(_read_api_json("/api/v1/scheduler/heartbeats"), pretty=pretty)
        return
    heartbeats = _open_heartbeat_store()
    try:
        rows = heartbeats.list_heartbeats()
    finally:
        heartbeats.close()
    _dump({"heartbeats": rows}, pretty=pretty)


# ---------------------------------------------------------------------------
# alerts
# ---------------------------------------------------------------------------


@scheduler_app.command("alerts")
def alerts_cmd(
    limit: int = typer.Option(  # noqa: B008
        50,
        "--limit",
        min=1,
        max=500,
        help="Maximum number of alerts to return (clamped to [1, 500]).",
    ),
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
    ),
) -> None:
    """List recent alerts (newest-first)."""
    if is_api_running():
        _dump(
            _read_api_json(f"/api/v1/scheduler/alerts?limit={limit}"),
            pretty=pretty,
        )
        return
    heartbeats = _open_heartbeat_store()
    try:
        rows = heartbeats.list_alerts(limit=limit)
    finally:
        heartbeats.close()
    _dump({"alerts": rows}, pretty=pretty)


# ---------------------------------------------------------------------------
# tasks
# ---------------------------------------------------------------------------


@scheduler_app.command("tasks")
def tasks_cmd(
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
    ),
) -> None:
    """List the static default task set the scheduler would run."""
    if is_api_running():
        _dump(_read_api_json("/api/v1/scheduler/tasks"), pretty=pretty)
        return

    async def _noop_handler(scope: str) -> None:
        return None

    tasks = build_default_tasks(on_reconcile=_noop_handler)
    _dump(
        {
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
        },
        pretty=pretty,
    )


# ---------------------------------------------------------------------------
# freezes
# ---------------------------------------------------------------------------


@scheduler_app.command("freezes")
def freezes_cmd(
    pretty: bool = typer.Option(  # noqa: B008
        True,
        "--pretty/--compact",
    ),
) -> None:
    """List currently-open broker freezes."""
    if is_api_running():
        _dump(_read_api_json("/api/v1/scheduler/freezes"), pretty=pretty)
        return
    recon = _open_recon_store()
    try:
        rows = recon.list_freezes(only_open=True)
    finally:
        recon.close()
    _dump(
        {
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
        },
        pretty=pretty,
    )


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


class _NullBrokerAdapter(BrokerAdapter):
    """Phase 18 dev-mode adapter used when no broker credentials are set.

    Every probe returns an empty result so the reconcile task succeeds
    and the scheduler stays running. The scheduler never places orders
    through this adapter — ``ReconciliationRunner`` only calls
    ``list_orders`` / ``get_positions`` / ``get_account``.
    """

    async def health(self) -> BrokerHealth:
        return BrokerHealth(
            healthy=True,
            detail="null adapter (no broker credentials configured)",
            checked_at=datetime.now(UTC),
        )

    async def submit(
        self, request: SubmitRequest, *, client_order_id: str
    ) -> SubmitResult:
        raise NotImplementedError("null adapter does not accept orders")

    async def cancel(self, broker_order_id: str) -> CancelResult:
        raise NotImplementedError("null adapter does not cancel orders")

    async def get_order(self, broker_order_id: str) -> OrderState:
        raise NotImplementedError("null adapter has no order state")

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
            account_id="null-adapter",
            cash=Decimal("0"),
            equity=Decimal("0"),
            buying_power=Decimal("0"),
            currency="USD",
            captured_at=datetime.now(UTC),
        )


def _oanda_is_configured() -> bool:
    """Return True when both OANDA credentials are present in the environment."""
    return bool(
        os.environ.get("ALPHABRIEF_OANDA_TOKEN")
        and os.environ.get("ALPHABRIEF_OANDA_ACCOUNT_ID")
    )


def _alpaca_is_configured() -> bool:
    """Return True when both Alpaca credentials are present in the environment."""
    return bool(
        os.environ.get("ALPHABRIEF_ALPACA_KEY")
        and os.environ.get("ALPHABRIEF_ALPACA_SECRET")
    )


def _build_adapter() -> BrokerAdapter:
    """Pick the appropriate broker adapter for the runtime environment.

    OANDA credentials win over Alpaca credentials so non-US operators can
    use the OANDA demo account without unsetting Alpaca keys. If neither
    credential set is present, fall back to :class:`_NullBrokerAdapter`,
    which lets the scheduler run in dev / CI without a live broker
    connection.
    """
    if _oanda_is_configured():
        from pathlib import Path as _Path

        from alphabrief_execution.broker.oanda.adapter import OandaPaperAdapter
        from alphabrief_execution.broker.oanda.client import OandaHttpClient
        from alphabrief_execution.broker.oanda.config import (
            DEFAULT_BASE_URL,
            DEFAULT_MAX_RETRIES,
            DEFAULT_RETRY_BACKOFF_SECONDS,
            DEFAULT_TIMEOUT_SECONDS,
            OandaPaperConfig,
            load_oanda_paper_config,
        )

        config_path = _Path("config/oanda_paper.yaml")
        if config_path.exists():
            oanda_config = load_oanda_paper_config(config_path)
        else:
            oanda_config = OandaPaperConfig(
                base_url=DEFAULT_BASE_URL,
                timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
                max_retries=DEFAULT_MAX_RETRIES,
                retry_backoff_seconds=DEFAULT_RETRY_BACKOFF_SECONDS,
            )
        client = OandaHttpClient(config=oanda_config)
        return OandaPaperAdapter(client=client)

    if _alpaca_is_configured():
        # Local import so the CLI doesn't require Alpaca config to be
        # present at module import time. The config file is loaded
        # from the default path; tests that exercise the live path
        # should set the env vars and the config file location.
        from pathlib import Path as _Path

        from alphabrief_execution.broker.alpaca.adapter import (
            AlpacaPaperAdapter,
        )
        from alphabrief_execution.broker.alpaca.client import (
            AlpacaHttpClient,
        )
        from alphabrief_execution.broker.alpaca.config import (
            DEFAULT_BASE_URL,
            DEFAULT_MAX_RETRIES,
            DEFAULT_RETRY_BACKOFF_SECONDS,
            DEFAULT_TIMEOUT_SECONDS,
            AlpacaPaperConfig,
            load_alpaca_paper_config,
        )

        config_path = _Path("config/alpaca_paper.yaml")
        if config_path.exists():
            alpaca_config = load_alpaca_paper_config(config_path)
        else:
            # Dev fallback: explicit defaults rather than a default
            # constructor because AlpacaPaperConfig fields are
            # required (no default values).
            alpaca_config = AlpacaPaperConfig(
                base_url=DEFAULT_BASE_URL,
                timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
                max_retries=DEFAULT_MAX_RETRIES,
                retry_backoff_seconds=DEFAULT_RETRY_BACKOFF_SECONDS,
            )
        alpaca_client = AlpacaHttpClient(config=alpaca_config)
        return AlpacaPaperAdapter(client=alpaca_client)
    return _NullBrokerAdapter()


def _refuse_if_live_trading_unlocked() -> None:
    """Refuse to run the scheduler if the risk layer would unlock live trading.

    The scheduler process itself never places orders, but the system
    rule remains: live trading must remain independently locked. We
    inspect :class:`alphabrief_risk.gate.RiskLimitConfig` and bail out
    if any caller-supplied env var has flipped the default to
    ``live_trading_enabled=True``.
    """
    if os.environ.get("ALPHABRIEF_LIVE_TRADING_ENABLED", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        print(
            "scheduler: refused — ALPHABRIEF_LIVE_TRADING_ENABLED is set; "
            "the scheduler is paper-only and refuses to run with live "
            "trading unlocked",
            file=sys.stderr,
        )
        sys.exit(3)


def _build_ai_committee() -> TradingCommittee:
    """Build a deterministic AI committee for the scheduler."""
    sample_response = {
        "analysis": (
            "Trend remains constructive on improving breadth; downside risks "
            "centered on macro headlines and crowded positioning."
        ),
        "view": "bullish",
        "confidence": 0.62,
        "evidence": [
            "EMA20 above EMA50 with rising volume",
            "News tone modestly positive",
        ],
        "risks": ["Macro headline tail-risk", "Crowded long positioning"],
        "suggested_action": "watch",
        "target_position_pct": 0.10,
        "veto": False,
        "needs_human_review": True,
    }
    provider = FakeProviderAdapter(
        provider_name="fake",
        model_name="fake-ai-committee",
        capabilities=["structured_output"],
        structured_output=sample_response,
    )
    gateway = ModelGateway(providers=[provider])
    return TradingCommittee(gateway=gateway, discipline=DisciplineConfig())


_AI_SCHEDULER_UNIVERSE = ("SPY", "QQQ", "IVV")


def _ai_cycle_factory(
    *, db_path: Path
) -> Callable[[], Awaitable[None]]:
    """Build an ``on_ai_cycle`` coroutine bound to ``db_path``.

    The cycle runs the AI Trading Committee for the operator-curated
    paper universe. The handler is registered but disabled by default;
    ``scheduler run`` enables the task only when
    ``ALPHABRIEF_AI_TRADING_ENABLED`` is truthy.
    """
    from alphabrief_api.db import AiTradingStore as _Store

    def _loader(symbol: str) -> MarketSnapshot | None:
        if symbol not in _AI_SCHEDULER_UNIVERSE:
            return None
        return MarketSnapshot(
            symbol=symbol,
            reference_price=Decimal("100"),
            recent_return_pct=Decimal("0"),
            recent_volume=Decimal("1000"),
            data_version="scheduler-runner-v1",
            captured_at=datetime.now(UTC),
        )

    async def _handler() -> None:
        # The store is opened and closed per-call so a long-running
        # scheduler can survive a DuckDB single-writer lock between
        # cycles (the AI store is currently the same DB as the broker
        # recon store). ponytail:scheduler_ai_duckdb_lock — see
        # upgrade path note in
        # docs/development_plans/0057-phase-26-ai-trader-closeout.md.
        store = _Store(db_path=db_path / "alphabrief.db")
        try:
            committee = _build_ai_committee()
            broker = PaperBroker(
                portfolio=PortfolioState(cash=Decimal("100000")),
                router=OrderRouter(),
                fill_simulator=FillSimulator(),
            )
            risk_gate = RiskGate(
                limits=RiskLimitConfig(
                    trading_enabled=True,
                    symbol_allowlist=frozenset(_AI_SCHEDULER_UNIVERSE),
                )
            )
            cycle = DailyTradingCycle(
                committee=committee,
                risk_gate=risk_gate,
                broker=broker,
                store=store,
                snapshot_loader=_loader,
                enabled=is_ai_trading_enabled(),
            )
            cycle.run(list(_AI_SCHEDULER_UNIVERSE))
        finally:
            store.close()

    return _handler


@scheduler_app.command("run")
def run_cmd(
    reconcile_interval_seconds: float = typer.Option(  # noqa: B008
        300.0,
        "--reconcile-interval",
        min=1.0,
        help="Interval between reconcile cycles (default: 300s).",
    ),
    max_consecutive_failures: int = typer.Option(  # noqa: B008
        3,
        "--max-failures",
        min=1,
        help="Freeze after this many consecutive task failures.",
    ),
) -> None:
    """Start the scheduler as a foreground process (Ctrl-C to stop)."""
    _refuse_if_live_trading_unlocked()

    heartbeats = _open_heartbeat_store()
    recon_store = _open_recon_store()
    try:
        adapter = _build_adapter()
        runner = ReconciliationRunner(adapter=adapter, store=recon_store)
        alert_sink = AlertSink(heartbeat_store=heartbeats)

        async def _on_reconcile(scope: str) -> None:
            await runner.reconcile(scope=scope)

        db_dir_env = os.environ.get("ALPHABRIEF_DATA_DIR")
        db_path = (
            Path(db_dir_env)
            if db_dir_env
            else Path.home() / ".alphabrief" / "data"
        )
        ai_handler = _ai_cycle_factory(db_path=db_path)

        tasks = build_default_tasks(
            on_reconcile=_on_reconcile,
            on_ai_cycle=ai_handler,
        )
        # Override the reconcile task interval if the user asked for a
        # different value. This rebuilds the list so the rest of the
        # default tasks (ai_daily_cycle) stay intact.
        tasks = [
            (
                replace(task, interval_seconds=reconcile_interval_seconds)
                if task.name == "reconcile"
                else task
            )
            for task in tasks
        ]
        # Activate the AI cycle task only when the feature flag is on;
        # otherwise it stays a registered-but-disabled entry so the
        # operator can see the task in `scheduler tasks`.
        if is_ai_trading_enabled():
            tasks = [
                replace(task, enabled=True) if task.name == "ai_daily_cycle" else task
                for task in tasks
            ]

        scheduler = OperationsScheduler(
            tasks=tasks,
            heartbeat_store=heartbeats,
            alert_sink=alert_sink,
            recon_runner=runner,
            recon_store=recon_store,
            config=SchedulerConfig(
                reconcile_on_start=True,
                max_consecutive_failures=max_consecutive_failures,
            ),
        )

        def _on_sigint(signum: int, frame: object) -> None:
            scheduler.request_stop()

        signal.signal(signal.SIGINT, _on_sigint)
        signal.signal(signal.SIGTERM, _on_sigint)

        try:
            asyncio.run(scheduler.run())
        except SchedulerStartupBlockedError as exc:
            print(f"scheduler: startup blocked: {exc}", file=sys.stderr)
            sys.exit(2)
        except KeyboardInterrupt:
            scheduler.request_stop()
            print("scheduler: stopped")
    finally:
        heartbeats.close()
        recon_store.close()


__all__ = ["scheduler_app"]
