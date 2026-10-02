"""Native holding facts, exit execution and worker ownership."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from _helpers import FakeExecutionBackend
from alphabrief_cli import cycle_commands as commands
from alphabrief_cli import run_commands, scheduler_commands
from alphabrief_execution.broker.oanda.client import OandaHttpClient
from alphabrief_execution.broker.oanda.trade_ops import (
    TradeOperationError,
    TradeOpsClient,
)
from alphabrief_risk.entry_rules import EntryRulePolicy
from alphabrief_trader.db_store import AiTradingStore
from test_cycle_sizing_and_close import NOW as GATE_NOW
from test_cycle_sizing_and_close import _account_context, _risk_gate

NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)
D = Decimal


@pytest.fixture(autouse=True)
def isolated_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))


def trade(identity: int, *, age: int = 48, units: str = "1000") -> dict[str, Any]:
    return {
        "id": str(identity),
        "instrument": "EUR_USD",
        "state": "OPEN",
        "currentUnits": units,
        "initialUnits": units,
        "openTime": (NOW - timedelta(hours=age)).isoformat(),
    }


class Client:
    def __init__(self, trades: list[dict[str, Any]], *, units: str = "1000") -> None:
        self.trades = trades
        self.units = units
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.summary_reads = 0
        self.position_reads = 0
        self.page_watermark = "900"
        self.changed_watermark = False
        self.changed_units: str | None = None
        self.long_override: str | None = None

    def account_path(self, suffix: str) -> str:
        return suffix

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        assert method == "GET"
        body: dict[str, Any]
        params = kwargs.get("params", {})
        self.calls.append((path, params))
        if path == "/summary":
            self.summary_reads += 1
            watermark = (
                "901" if self.changed_watermark and self.summary_reads > 1 else "900"
            )
            body = {
                "account": {
                    "id": "test-account",
                    "currency": "USD",
                    "balance": "100000",
                    "NAV": "100000",
                    "unrealizedPL": "0",
                    "marginUsed": "20",
                    "marginAvailable": "99980",
                    "openOrderCount": 0,
                    "openTradeCount": len(self.trades),
                    "openPositionCount": 1,
                    "lastTransactionID": watermark,
                }
            }
        elif path == "/trades":
            assert params["state"] == "OPEN"
            before = int(params.get("beforeID", 100000))
            rows = sorted(
                (t for t in self.trades if int(t["id"]) < before),
                key=lambda t: int(t["id"]),
                reverse=True,
            )[: params["count"]]
            body = {"trades": rows, "lastTransactionID": self.page_watermark}
        elif path == "/positions":
            self.position_reads += 1
            units = (
                self.changed_units
                if self.position_reads > 1 and self.changed_units is not None
                else self.units
            )
            value = D(units)
            body = {
                "positions": [
                    {
                        "instrument": "EUR_USD",
                        "long": {
                            "units": self.long_override or str(max(value, D(0))),
                            "unrealizedPL": "0",
                        },
                        "short": {"units": str(min(value, D(0))), "unrealizedPL": "0"},
                    }
                ]
            }
        else:
            raise AssertionError(path)
        return SimpleNamespace(json_body=body)


def install(monkeypatch: pytest.MonkeyPatch, client: Client) -> list[dict[str, Any]]:
    monkeypatch.setattr(commands, "oanda_is_configured", lambda: True)
    monkeypatch.setattr(commands, "build_oanda_paper_client", lambda: client)
    monkeypatch.setattr(commands, "_position_mark", lambda symbol: D("1.1"))
    submitted: list[dict[str, Any]] = []

    def close(**kwargs: Any) -> dict[str, Any]:
        submitted.append(kwargs)
        return {
            "instrument": kwargs["instrument"],
            "closed": True,
            "outcome": "executed",
        }

    monkeypatch.setattr(commands, "_close_through_the_cycle", close)
    return submitted


@pytest.mark.parametrize(
    "age,units,expected", [(47, "1000", 0), (48, "1000", 1), (72, "-1000", 1)]
)
def test_native_holding_age_and_short_direction(
    monkeypatch: pytest.MonkeyPatch, age: int, units: str, expected: int
) -> None:
    client = Client([trade(1, age=age, units=units)], units=units)
    submitted = install(monkeypatch, client)
    report = commands.close_due_positions(now=NOW, trading="on")
    assert len(submitted) == expected
    if expected:
        assert submitted[0]["position_units"] == D(units)
        assert submitted[0]["close_key"].startswith("holding_exit_")
        assert report["closed"][0]["closed"]


def test_old_trade_beyond_first_page_and_one_exit_per_instrument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client(
        [trade(i, age=48 if i == 1 else 1, units="1") for i in range(1, 602)],
        units="601",
    )
    submitted = install(monkeypatch, client)
    report = commands.close_due_positions(now=NOW, trading="on")
    assert report["checked"] == 601 and len(report["due"]) == len(submitted) == 1
    assert submitted[0]["position_units"] == D(601)
    assert [p for path, p in client.calls if path == "/trades"] == [
        {"state": "OPEN", "count": 500},
        {"state": "OPEN", "count": 500, "beforeID": "102"},
        {"state": "OPEN", "count": 500, "beforeID": "1"},
    ]


@pytest.mark.parametrize(
    "kind", ["page", "summary", "mismatch", "hedged", "zero_trade", "changed"]
)
def test_bad_or_changing_facts_never_submit(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    client = Client([trade(1)])
    if kind == "page":
        client.page_watermark = "899"
    elif kind == "summary":
        client.changed_watermark = True
    elif kind == "mismatch":
        client.units = "2000"
    elif kind == "hedged":
        client.units, client.long_override = "-1000", "1000"
    elif kind == "zero_trade":
        client.trades[0]["currentUnits"] = "0"
    else:
        client.changed_units = "900"
    submitted = install(monkeypatch, client)
    with pytest.raises((ValueError, TradeOperationError)):
        commands.close_due_positions(now=NOW, trading="on")
    assert submitted == []


@pytest.mark.parametrize(
    "stamp",
    [None, "2026-09-29T12:00:00", "bad", (NOW + timedelta(hours=1)).isoformat()],
)
def test_unknown_or_invalid_open_time_closes_conservatively(
    monkeypatch: pytest.MonkeyPatch, stamp: str | None
) -> None:
    row = trade(1, age=1)
    row["openTime"] = stamp
    submitted = install(monkeypatch, Client([row]))
    commands.close_due_positions(now=NOW, trading="on")
    assert len(submitted) == 1 and "unknown" in submitted[0]["reason"]


def test_off_reports_without_submitting_and_friday_closes_fresh_trade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submitted = install(monkeypatch, Client([trade(1, age=1)]))
    friday = datetime(2026, 10, 2, 19, tzinfo=UTC)
    report = commands.close_due_positions(now=friday, trading="off")
    assert len(report["due"]) == 1 and report["closed"] == [] and submitted == []
    commands.close_due_positions(now=friday, trading="on")
    assert len(submitted) == 1 and "Friday" in submitted[0]["reason"]


def test_already_closed_between_observations_is_not_resubmitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client([trade(1)])
    client.changed_units = "0"
    submitted = install(monkeypatch, client)
    result = commands.close_due_positions(now=NOW, trading="on")
    assert (
        submitted == [] and result["closed"][0]["detail"] == "position already closed"
    )


def test_missing_mark_becomes_a_runtime_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submitted = install(monkeypatch, Client([trade(1)]))
    monkeypatch.setattr(commands, "_position_mark", lambda symbol: None)
    monkeypatch.setattr(scheduler_commands, "trading_mode", lambda: "on")
    with pytest.raises(RuntimeError, match="position_exit_refused"):
        run_commands.position_monitor_once(now=NOW)
    assert submitted == []


def test_resident_off_is_inert_even_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scheduler_commands, "trading_mode", lambda: "off")

    def unexpected(**kwargs: Any) -> Any:
        raise AssertionError("off reached broker/database")

    monkeypatch.setattr(commands, "close_due_positions", unexpected)
    assert run_commands.position_monitor_once(now=NOW) == 0
    assert run_commands.close_out_once(reason="Friday") == 0


@pytest.mark.parametrize("state", ["filled", "stale", "kill", "off", "unknown"])
def test_actual_close_orchestration_persists_attempt_without_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))

    def unexpected(**kwargs: Any) -> Any:
        raise AssertionError("system close constructed model channels")

    monkeypatch.setattr(commands, "build_ai_trading_committee", unexpected)
    context = _account_context(
        quote_age_seconds=20 if state == "stale" else 1,
        frozen={"EUR_USD": "reconciliation freeze"},
    )
    monkeypatch.setattr(
        commands, "_account_context_provider", lambda *a, **k: lambda symbol: context
    )
    monkeypatch.setattr(commands, "_risk_sources", lambda *a, **k: object())
    gate = _risk_gate(
        ("EUR_USD",),
        entry_rules=EntryRulePolicy(
            max_quote_age_seconds=15,
            require_quote_tradeable=True,
        ),
    )
    if state == "kill":
        gate.kill_switch.activate("test")
    monkeypatch.setattr(commands, "_risk_gate", lambda symbols: gate)

    class UnknownBackend(FakeExecutionBackend):
        def submit(self, *args: Any, **kwargs: Any) -> Any:
            from alphabrief_trader.execution_backend import ExecutionBackendError

            super().submit(*args, **kwargs)
            raise ExecutionBackendError("SUBMIT_UNKNOWN")

    backend = UnknownBackend() if state == "unknown" else FakeExecutionBackend()
    monkeypatch.setattr(commands, "_execution_backend", lambda **kwargs: backend)

    # Control only this test's wall-clock so native rule-3 quote age is precise.
    class Clock:
        @staticmethod
        def now(tz: Any = None) -> datetime:
            return GATE_NOW

    monkeypatch.setattr(commands, "datetime", Clock)
    result = commands._close_through_the_cycle(
        instrument="EUR_USD",
        position_units=D("-1000"),
        reference_price=D("1.1"),
        reason="held 48h",
        trading="off" if state == "off" else "on",
        close_key="test-position-incarnation",
    )
    store = AiTradingStore(tmp_path / "alphabrief.duckdb")
    try:
        saved = store.get_cycle(result["cycle_id"])
        assert saved is not None
        attempt = saved["attempts"][0]
        assert attempt["order_intent_json"]["reduce_only"] is True
        assert attempt["order_intent_json"]["side"] == "buy"
        assert (
            attempt["risk_decision_json"]["decision_id"] == result["risk_decision_id"]
        )
        assert saved["votes"] == [] and saved["plans"] == []
        assert backend.submission_count == (1 if state in {"filled", "unknown"} else 0)
        assert saved["outcome"] == (
            "executed"
            if state == "filled"
            else "error"
            if state == "unknown"
            else "blocked_trading_off"
            if state == "off"
            else "blocked_risk_gate"
        )
        if state in {"filled", "unknown"}:
            replay = commands._close_through_the_cycle(
                instrument="EUR_USD",
                position_units=D("-1000"),
                reference_price=D("1.1"),
                reason="held 48h",
                trading="on",
                close_key="test-position-incarnation",
            )
            assert replay["outcome"] == "exit_already_submitted"
            assert backend.submission_count == 1
    finally:
        store.close()


def test_cancelled_exit_keeps_lock_until_worker_finishes() -> None:
    entered, release = threading.Event(), threading.Event()
    calls: list[str] = []

    def monitor() -> int:
        calls.append("monitor")
        entered.set()
        assert release.wait(5)
        return 1

    async def check() -> None:
        runtime = run_commands.Runtime(
            host="127.0.0.1",
            port=8765,
            universe=("EUR_USD",),
            position_monitor=monitor,
            close_out=lambda reason: calls.append("Friday"),
        )
        first = asyncio.create_task(runtime._run_position_monitor())
        assert await asyncio.to_thread(entered.wait, 2)
        first.cancel()
        second = asyncio.create_task(runtime._run_close_out())
        try:
            await asyncio.sleep(0.01)
            assert calls == ["monitor"] and not first.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        await second
        assert calls == ["monitor", "Friday"]

    asyncio.run(check())


def test_default_resident_task_runs_while_frozen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alphabrief_execution.broker.recon_store import BrokerReconStore
    from alphabrief_execution.operations.scheduler import HeartbeatStore

    heartbeat = HeartbeatStore(tmp_path / "runtime.db")
    recon = BrokerReconStore(tmp_path / "runtime.db")
    recon.raise_freeze(reason="test", source="test")
    monkeypatch.setattr(scheduler_commands, "_open_heartbeat_store", lambda: heartbeat)
    monkeypatch.setattr(scheduler_commands, "_open_recon_store", lambda: recon)
    called: list[datetime] = []
    monkeypatch.setattr(
        run_commands,
        "position_monitor_once",
        lambda **kwargs: called.append(kwargs["now"]),
    )

    async def check() -> None:
        runtime = run_commands.Runtime(
            host="127.0.0.1",
            port=8765,
            universe=("EUR_USD",),
            clock=lambda: NOW,
        )
        scheduler = await runtime._build_scheduler()
        task = next(t for t in scheduler._tasks if t.name == "position_monitor")
        assert task.interval_seconds == 60 and task.timeout_seconds == 600
        assert task.run_when_frozen and task.enabled and task.max_retries == 0
        runner = asyncio.create_task(scheduler._run_task(task))
        try:
            for _ in range(100):
                await asyncio.sleep(0.01)
                if heartbeat.last_run_at(task.name) is not None:
                    break
            assert (
                called == [NOW]
                and heartbeat.list_heartbeats()[0]["last_status"] == "ok"
            )
            assert recon.has_open_freeze()
        finally:
            scheduler.request_stop()
            await runner

    try:
        asyncio.run(check())
    finally:
        heartbeat.close()
        recon.close()


def test_open_snapshot_pagination_bound_is_not_silently_truncated() -> None:
    client = Client([trade(i, units="1") for i in range(1, 52)])
    with pytest.raises(TradeOperationError, match="pagination_limit"):
        TradeOpsClient(cast(OandaHttpClient, client)).open_trade_history(
            expected_watermark="900", page_size=1
        )


@pytest.mark.parametrize("limit", [0, -1, True])
def test_invalid_holding_limit_refuses(limit: int) -> None:
    from alphabrief_trader.close_policy import evaluate_close

    with pytest.raises(ValueError, match="holding limit"):
        evaluate_close(
            instrument="EUR_USD", open_time=NOW, now=NOW, max_hold_hours=limit
        )


def test_naive_policy_clock_refuses_before_broker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client([trade(1)])
    submitted = install(monkeypatch, client)
    with pytest.raises(ValueError, match="timezone aware"):
        commands.close_due_positions(now=NOW.replace(tzinfo=None), trading="on")
    assert client.calls == [] and submitted == []


def test_manual_position_reader_preserves_native_short_sign(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install(monkeypatch, Client([trade(1, units="-1000")], units="-1000"))
    assert commands._open_positions() == {"EUR_USD": (D("-1000"), D("1.1"))}
