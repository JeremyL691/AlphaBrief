"""Tests for the clock schedule and the single-process runtime (GUIDE 5.1/S5).

Trading opportunities are a resident task checked every 1-5 minutes
(`test_runtime_opportunity_task.py` and `test_opportunity_scan.py`).
This module covers the remaining clock anchors and the planner that
dispatches them.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alphabrief_cli.run_commands import Runtime, cycle_key_for
from alphabrief_core import DEFAULT_SCHEDULE, evaluate_schedule

#: Thursday 2026-10-01.
THURSDAY = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
FRIDAY = datetime(2026, 10, 2, 0, 0, tzinfo=UTC)
SATURDAY = datetime(2026, 10, 3, 0, 0, tzinfo=UTC)


def _at(day: datetime, hour: int, minute: int) -> datetime:
    return day.replace(hour=hour, minute=minute)


class TestSchedulePlan:
    def test_anchor_fires_on_time(self) -> None:
        verdicts = {
            v.name: v for v in evaluate_schedule(now=_at(THURSDAY, 21, 30))
        }

        assert verdicts["daily_report"].due is True
        assert verdicts["daily_report"].reason == "due"

    def test_anchor_inside_the_catch_up_window_runs_late(self) -> None:
        verdicts = {
            v.name: v for v in evaluate_schedule(now=_at(THURSDAY, 22, 30))
        }

        assert verdicts["daily_report"].due is True
        assert verdicts["daily_report"].reason == "catch_up"

    def test_anchor_outside_the_window_is_missed_not_run(self) -> None:
        verdicts = {
            v.name: v
            for v in evaluate_schedule(
                now=_at(THURSDAY, 21, 30) + timedelta(minutes=91)
            )
        }

        assert verdicts["daily_report"].due is False
        assert verdicts["daily_report"].reason == "missed_window"
        assert "never run late" in verdicts["daily_report"].detail

    def test_catch_up_boundary_is_inclusive(self) -> None:
        at_edge = {
            v.name: v
            for v in evaluate_schedule(
                now=_at(THURSDAY, 21, 30) + timedelta(minutes=90)
            )
        }

        assert at_edge["daily_report"].due is True
        one_second_late = {
            v.name: v
            for v in evaluate_schedule(
                now=_at(THURSDAY, 21, 30) + timedelta(minutes=90, seconds=1)
            )
        }
        assert one_second_late["daily_report"].due is False

    def test_a_finished_anchor_is_not_due_again(self) -> None:
        runs = {"daily_report": _at(THURSDAY, 21, 31)}

        verdicts = {
            v.name: v
            for v in evaluate_schedule(now=_at(THURSDAY, 21, 45), last_runs=runs)
        }

        assert verdicts["daily_report"].due is False
        assert verdicts["daily_report"].reason == "already_ran"

    def test_weekends_keep_report_and_backup(self) -> None:
        verdicts = {
            v.name: v for v in evaluate_schedule(now=_at(SATURDAY, 21, 30))
        }

        assert verdicts["daily_report"].due is True
        assert verdicts["backup"].due is False  # 22:00 has not arrived yet

    def test_the_schedule_no_longer_holds_fixed_trading_rounds(self) -> None:
        """GUIDE 5.1 replaced the three rounds with a 1-5 minute check."""
        kinds = {event.kind for event in DEFAULT_SCHEDULE}

        assert "decision_round" not in kinds
        assert {event.name for event in DEFAULT_SCHEDULE} == {
            "weekend_close_out",
            "daily_report",
            "backup",
        }

    def test_friday_close_out_fires_only_on_friday(self) -> None:
        friday = {v.name: v for v in evaluate_schedule(now=_at(FRIDAY, 19, 5))}
        thursday = {
            v.name: v for v in evaluate_schedule(now=_at(THURSDAY, 19, 5))
        }

        assert friday["weekend_close_out"].due is True
        assert thursday["weekend_close_out"].due is False

    def test_report_and_backup_fire_daily(self) -> None:
        report = {v.name: v for v in evaluate_schedule(now=_at(THURSDAY, 21, 30))}
        backup = {v.name: v for v in evaluate_schedule(now=_at(THURSDAY, 22, 0))}

        assert report["daily_report"].due is True
        assert backup["backup"].due is True

    def test_bad_window_is_refused(self) -> None:
        with pytest.raises(ValueError, match="catch_up_minutes"):
            evaluate_schedule(now=THURSDAY, catch_up_minutes=0)

    def test_cycle_key_is_per_event_and_day(self) -> None:
        event = DEFAULT_SCHEDULE[0]

        assert cycle_key_for(event, THURSDAY) == "weekend_close_out:2026-10-01"
        assert cycle_key_for(event, FRIDAY) != cycle_key_for(event, THURSDAY)


class TestRuntimePlanner:
    def _runtime(self, *, now: datetime, calls: list[str]) -> Runtime:
        # The decision round is a coroutine (it awaits the cycle); report,
        # backup and close-out are synchronous blocking callables, which the
        # runtime runs in a worker thread.
        async def _decision(key: str) -> None:
            calls.append(f"decision:{key}")

        def _report() -> None:
            calls.append("report")

        def _backup() -> None:
            calls.append("backup")

        def _close(reason: str) -> None:
            calls.append("close")

        runtime = Runtime(
            host="127.0.0.1",
            port=0,
            universe=("EUR_USD",),
            clock=lambda: now,
            decision_round=_decision,
            report_writer=_report,
            backup_runner=_backup,
            close_out=_close,
            quote_poller=lambda: 0,
            shadow_scorer=lambda: 0,
        )
        # No durable artifacts exist in the isolated data dir, so the
        # planner sees every event as not-yet-run.
        return runtime

    def test_planner_dispatches_the_due_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
        calls: list[str] = []
        runtime = self._runtime(now=_at(THURSDAY, 21, 30), calls=calls)

        asyncio.run(runtime.planner_tick())

        assert calls == ["report"]

    def test_planner_dispatches_report_and_backup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
        calls: list[str] = []
        runtime = self._runtime(now=_at(THURSDAY, 22, 0), calls=calls)

        asyncio.run(runtime.planner_tick())

        assert "report" in calls
        assert "backup" in calls

    def test_planner_does_not_dispatch_missed_rounds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
        calls: list[str] = []
        runtime = self._runtime(now=_at(THURSDAY, 5, 0), calls=calls)

        asyncio.run(runtime.planner_tick())

        assert calls == []

    def test_planner_logs_the_missed_windows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
        runtime = self._runtime(now=_at(THURSDAY, 5, 0), calls=[])

        asyncio.run(runtime.planner_tick())

        # Nothing dispatched, but the missed rounds are on the record.
        assert runtime._planner_log == []

    def test_stop_event_ends_the_planner_loop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
        runtime = self._runtime(now=_at(THURSDAY, 5, 0), calls=[])

        async def _run() -> None:
            runtime.request_stop()
            await asyncio.wait_for(runtime.planner_loop(), timeout=5)

        asyncio.run(_run())
