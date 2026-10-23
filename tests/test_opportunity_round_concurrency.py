"""A committee round must not stall the opportunity-check cadence.

A round spends 21-31 model calls. With a reasoning model one round took over
seventeen minutes, and while it ran the ``ai_daily_cycle`` task recorded
nothing: four runs in half an hour instead of one every 180 seconds. The soak
evaluator counts those task runs as liveness, so a slow round would make every
day look like missed rounds and fail the run for the wrong reason.

The round therefore runs as its own task: the check returns promptly, and an
in-flight round blocks a second one instead of queueing it.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alphabrief_cli.run_commands import Runtime


def _runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, round_fn: Any) -> Runtime:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    return Runtime(
        host="127.0.0.1",
        port=0,
        universe=("EUR_USD",),
        clock=lambda: datetime(2026, 10, 23, 12, 0, tzinfo=UTC),
        decision_round=round_fn,
        report_writer=lambda: None,
        backup_runner=lambda: None,
        close_out=lambda reason: None,
        quote_poller=lambda: 0,
        shadow_scorer=lambda: 0,
        market_refresher=lambda: None,
        position_monitor=lambda: 0,
    )


class _SlowRound:
    """A committee round that takes long enough to stall a naive await."""

    def __init__(self) -> None:
        self.started = 0
        self.finished = 0
        self.release = asyncio.Event()

    async def __call__(self, cycle_key: str) -> None:
        del cycle_key
        self.started += 1
        await self.release.wait()
        self.finished += 1


def test_a_slow_round_does_not_block_the_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check must return while the round is still running."""
    round_fn = _SlowRound()
    runtime = _runtime(tmp_path, monkeypatch, round_fn)

    async def scenario() -> None:
        # Force an escalation without touching the market or a database.
        monkeypatch.setattr(
            runtime, "_opportunity_inputs", lambda: ([], True), raising=False
        )
        monkeypatch.setattr(
            runtime, "_opportunity_facts", lambda: (0, None), raising=False
        )
        monkeypatch.setattr(runtime, "_provider_available", lambda: True, raising=False)
        monkeypatch.setattr(runtime, "_opportunity_limits", lambda: _limits())
        monkeypatch.setattr(
            "alphabrief_trader.opportunity.scan_opportunities", _escalate
        )
        await asyncio.wait_for(runtime._run_opportunity_check(), timeout=2)
        # The check already returned; the round is queued as its own task.
        await asyncio.sleep(0)
        assert round_fn.started == 1
        assert round_fn.finished == 0, "the check waited for the whole round"
        round_fn.release.set()
        assert runtime._round_task is not None
        await runtime._round_task

    asyncio.run(scenario())


def test_a_second_check_does_not_start_an_overlapping_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two rounds at once would double the spend and the ledger pressure."""
    round_fn = _SlowRound()
    runtime = _runtime(tmp_path, monkeypatch, round_fn)

    async def scenario() -> None:
        monkeypatch.setattr(
            runtime, "_opportunity_inputs", lambda: ([], True), raising=False
        )
        monkeypatch.setattr(
            runtime, "_opportunity_facts", lambda: (0, None), raising=False
        )
        monkeypatch.setattr(runtime, "_provider_available", lambda: True, raising=False)
        monkeypatch.setattr(runtime, "_opportunity_limits", lambda: _limits())
        monkeypatch.setattr(
            "alphabrief_trader.opportunity.scan_opportunities", _escalate
        )
        await runtime._run_opportunity_check()
        await runtime._run_opportunity_check()
        assert round_fn.started == 1, "a second round was started while one ran"
        round_fn.release.set()
        assert runtime._round_task is not None
        await runtime._round_task

    asyncio.run(scenario())


def _limits() -> Any:
    from alphabrief_trader.opportunity import OpportunityLimits

    return OpportunityLimits()


def _escalate(*args: Any, **kwargs: Any) -> Any:
    from alphabrief_trader.opportunity import OpportunityScan

    return OpportunityScan(
        escalate=True,
        reason="signal_above_threshold",
        symbols=[],
        rounds_today=0,
    )
