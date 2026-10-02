"""Real-shaped refresh failures, ownership, and resident task wiring."""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest
from alphabrief_api.db import MarketDataStore
from alphabrief_cli import cycle_commands, run_commands, scheduler_commands
from alphabrief_cli.run_commands import Runtime
from alphabrief_execution.broker.oanda import market_sync
from alphabrief_execution.operations.scheduler import OperationsScheduler
from test_market_sync import _client, _MemoryStore


@pytest.mark.parametrize("required", [True, False])
def test_short_response_is_not_a_complete_fresh_window(required: bool) -> None:
    store = _MemoryStore()
    counts, errors = market_sync.sync_bars(
        _client(), instruments=("EUR_USD",), store=store,
        timeframes=(("H1", 3),), require_full_window=required,
    )
    if required:
        assert counts == {} and errors == {"EUR_USD:H1": "IncompleteWindow"}
        assert store.bars == []
    else:
        assert counts == {"EUR_USD:H1": 2} and errors == {}


def test_storage_failure_is_classified_and_other_windows_continue() -> None:
    class Sink(_MemoryStore):
        def insert_bars(self, bars: Any, source: str, data_version: str) -> int:
            if bars[0].symbol == "EUR_USD":
                raise RuntimeError("private request URL must not be recorded")
            return super().insert_bars(bars, source, data_version)

    counts, errors = market_sync.sync_bars(
        _client(), instruments=("EUR_USD", "USD_JPY"), store=Sink(),
        timeframes=(("H1", 2),), require_full_window=True,
    )
    assert errors == {"EUR_USD:H1": "RuntimeError"}
    assert counts == {"USD_JPY:H1": 2}


@pytest.mark.parametrize("failure", [False, True])
def test_worker_closes_its_market_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: bool,
) -> None:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    stores: list[MarketDataStore] = []
    owner: list[int] = []
    closed: list[int] = []
    original = MarketDataStore.close

    def refresh(store: MarketDataStore, symbols: tuple[str, ...]) -> dict[str, str]:
        assert symbols == ("EUR_USD",)
        stores.append(store)
        owner.append(threading.get_ident())
        return {"EUR_USD:H1": "TimeoutError"} if failure else {}

    def close(store: MarketDataStore) -> None:
        closed.append(threading.get_ident())
        original(store)

    monkeypatch.setattr(cycle_commands, "_refresh_market_bars", refresh)
    monkeypatch.setattr(MarketDataStore, "close", close)
    if failure:
        with pytest.raises(RuntimeError, match="^market_refresh_failed$"):
            run_commands.market_sync_once(symbols=("EUR_USD",))
    else:
        run_commands.market_sync_once(symbols=("EUR_USD",))
    assert len(stores) == 1 and owner == closed


def _runtime(refresh: Any) -> Runtime:
    return Runtime(host="127.0.0.1", port=8765, universe=("EUR_USD",),
                   market_refresher=refresh)


def test_cancelled_refresh_waits_for_worker_without_blocking_event_loop() -> None:
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def refresh() -> None:
        entered.set()
        assert release.wait(5)
        finished.set()

    async def check() -> None:
        runtime = _runtime(refresh)
        task = asyncio.create_task(runtime._run_market_sync())
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            await asyncio.sleep(0.01)
            assert not task.done() and not finished.is_set()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()

    asyncio.run(check())


def test_two_refresh_invocations_never_overlap() -> None:
    entered, release = threading.Event(), threading.Event()
    calls: list[int] = []

    def refresh() -> None:
        calls.append(len(calls))
        entered.set()
        assert release.wait(5)

    async def check() -> None:
        runtime = _runtime(refresh)
        first = asyncio.create_task(runtime._run_market_sync())
        assert await asyncio.to_thread(entered.wait, 2)
        second = asyncio.create_task(runtime._run_market_sync())
        try:
            await asyncio.sleep(0.01)
            assert calls == [0]
        finally:
            release.set()
        await asyncio.gather(first, second)
        assert calls == [0, 1]

    asyncio.run(check())


@pytest.mark.parametrize("task_name", ["market_sync", "reconcile"])
def test_read_only_tasks_run_immediately_even_with_an_open_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    task_name: str,
) -> None:
    from alphabrief_execution.broker.recon_store import BrokerReconStore
    from alphabrief_execution.operations.scheduler import HeartbeatStore

    heartbeat = HeartbeatStore(tmp_path / "runtime.db")
    recon = BrokerReconStore(tmp_path / "runtime.db")
    recon.raise_freeze(reason="test", source="test")
    monkeypatch.setattr(scheduler_commands, "_open_heartbeat_store", lambda: heartbeat)
    monkeypatch.setattr(scheduler_commands, "_open_recon_store", lambda: recon)
    runs: list[int] = []
    monkeypatch.setattr(
        scheduler_commands, "_reconcile_runner",
        lambda store: lambda scope: runs.append(1),
    )

    async def check() -> None:
        runtime = _runtime(lambda: runs.append(1))
        scheduler: OperationsScheduler = await runtime._build_scheduler()
        task = next(t for t in scheduler._tasks if t.name == "market_sync")
        reconcile_task = next(t for t in scheduler._tasks if t.name == "reconcile")
        assert reconcile_task.run_when_frozen
        assert task.interval_seconds == 900 and task.timeout_seconds == 300
        assert task.max_retries == 0 and task.enabled and task.run_when_frozen
        selected = task if task_name == "market_sync" else reconcile_task
        runner = asyncio.create_task(scheduler._run_task(selected))
        try:
            for _ in range(100):
                await asyncio.sleep(0.01)
                if heartbeat.last_run_at(task_name) is not None:
                    break
            assert runs == [1]
            assert heartbeat.list_heartbeats()[0]["last_status"] == "ok"
            assert recon.has_open_freeze()
        finally:
            scheduler.request_stop()
            await runner

    try:
        asyncio.run(check())
    finally:
        heartbeat.close()
        recon.close()
