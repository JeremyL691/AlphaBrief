"""The runtime must actually check for opportunities (GUIDE 5.1).

The soak evaluator counts runs of the scheduler task named
``ai_daily_cycle``. Before this contract, `alphabrief run run` registered
that task with ``on_ai_cycle=None``, so the task did not exist at all and
the evaluator saw zero opportunity rounds for every day - the reason a
real backend produced 0 qualified soak days while looking healthy.

These tests pin the wiring, not the scan itself (that is
``test_opportunity_scan.py``): the runtime must register the task under
the exact evaluator name, at the configured cadence, and it must be able
to run while the account is frozen so its own failure episode can clear.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alphabrief_cli.run_commands import Runtime


@pytest.fixture()
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Runtime:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    return Runtime(
        host="127.0.0.1",
        port=0,
        universe=("EUR_USD",),
        clock=lambda: datetime(2026, 10, 20, 12, 0, tzinfo=UTC),
        decision_round=lambda key: None,
        report_writer=lambda: None,
        backup_runner=lambda: None,
        close_out=lambda reason: None,
        quote_poller=lambda: 0,
        shadow_scorer=lambda: 0,
        market_refresher=lambda: None,
        position_monitor=lambda: 0,
    )


def _tasks(runtime: Runtime) -> dict[str, object]:
    scheduler = asyncio.run(runtime._build_scheduler())
    return {task.name: task for task in scheduler._tasks}  # noqa: SLF001 - contract


def test_runtime_registers_the_opportunity_task(runtime: Runtime) -> None:
    """The evaluator's CYCLE_TASK_NAME must exist in the live scheduler."""
    from alphabrief_trader.soak_evaluator import CYCLE_TASK_NAME

    names = _tasks(runtime)

    assert CYCLE_TASK_NAME in names, (
        "the runtime does not register "
        f"{CYCLE_TASK_NAME!r}; the soak evaluator would count zero "
        "opportunity rounds for every day"
    )


def test_opportunity_task_runs_at_the_guide_cadence(runtime: Runtime) -> None:
    """GUIDE 5.1 asks for a check every 1-5 minutes, not once a day."""
    from alphabrief_trader.soak_evaluator import CYCLE_TASK_NAME

    task = _tasks(runtime)[CYCLE_TASK_NAME]

    assert 60 <= task.interval_seconds <= 300  # type: ignore[attr-defined]


def test_opportunity_task_keeps_its_durable_name(runtime: Runtime) -> None:
    """Renaming the task would silently zero the soak's round counting."""
    from alphabrief_trader.soak_evaluator import CYCLE_TASK_NAME

    assert CYCLE_TASK_NAME == "ai_daily_cycle"
    assert CYCLE_TASK_NAME in _tasks(runtime)


def test_opportunity_task_runs_while_frozen(runtime: Runtime) -> None:
    """A freeze stops new exposure, not the evidence collection (GUIDE 5.9)."""
    from alphabrief_trader.soak_evaluator import CYCLE_TASK_NAME

    task = _tasks(runtime)[CYCLE_TASK_NAME]

    assert task.run_when_frozen is True  # type: ignore[attr-defined]


def test_opportunity_task_has_no_blind_retries(runtime: Runtime) -> None:
    """A retried scan could double-submit; the cycle key makes it safe, but
    a scan needs no retry because the next tick is 1-5 minutes away."""
    from alphabrief_trader.soak_evaluator import CYCLE_TASK_NAME

    task = _tasks(runtime)[CYCLE_TASK_NAME]

    assert task.max_retries == 0  # type: ignore[attr-defined]


def test_scheduler_still_registers_the_operational_tasks(runtime: Runtime) -> None:
    """The opportunity task must not displace reconciliation or monitoring."""
    names = _tasks(runtime)

    for expected in (
        "reconcile",
        "position_monitor",
        "quote_poll",
        "market_sync",
        "shadow_score",
    ):
        assert expected in names, f"{expected} is missing from the runtime"
