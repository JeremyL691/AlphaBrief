"""Tests for SoakStore lifecycle and persistence (PROJECT_GUIDE S10)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alphabrief_trader.soak_store import (
    MAX_START_BACKDATE,
    SoakStartTimeError,
    SoakStore,
)


def test_soak_store_initial_state_empty(tmp_path: Path) -> None:
    store = SoakStore(db_path=tmp_path / "test.duckdb")
    try:
        assert store.get_active_run() is None
        assert store.get_latest_run() is None
        assert store.list_runs() == []
    finally:
        store.close()


def test_soak_store_start_run_creates_active(tmp_path: Path) -> None:
    t0 = datetime(2026, 10, 4, 4, 0, tzinfo=UTC)
    # Simulated clock: production uses the real clock, so a past start is
    # only reachable here by moving the store's own notion of "now".
    store = SoakStore(db_path=tmp_path / "test.duckdb", now_fn=lambda: t0)
    try:
        run = store.start_soak(started_at=t0)
        assert run.run_index == 0
        assert run.state == "active"
        assert run.started_at == t0
        assert run.reason is None
        assert run.superseded_by is None

        # Calling start_soak again returns existing active run
        again = store.start_soak()
        assert again.run_index == 0
        assert again.started_at == t0

        active = store.get_active_run()
        assert active is not None
        assert active.run_index == 0
    finally:
        store.close()


def test_soak_store_reset_supersedes_and_increments(tmp_path: Path) -> None:
    t0 = datetime(2026, 10, 4, 4, 0, tzinfo=UTC)
    clock = {"now": t0}
    store = SoakStore(db_path=tmp_path / "test.duckdb", now_fn=lambda: clock["now"])
    try:
        run0 = store.start_soak(started_at=t0)
        assert run0.run_index == 0

        t1 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
        clock["now"] = t1
        run1 = store.record_reset(
            reason="duplicate orders detected",
            new_started_at=t1,
        )
        assert run1.run_index == 1
        assert run1.state == "active"
        assert run1.started_at == t1

        runs = store.list_runs()
        assert len(runs) == 2
        assert runs[0].run_index == 0
        assert runs[0].state == "reset"
        assert runs[0].reason == "duplicate orders detected"
        assert runs[0].superseded_by == 1

        assert runs[1].run_index == 1
        assert runs[1].state == "active"
    finally:
        store.close()


def test_soak_store_complete_and_halt(tmp_path: Path) -> None:
    store = SoakStore(db_path=tmp_path / "test.duckdb")
    try:
        store.start_soak()
        assert store.get_active_run() is not None

        store.complete_soak()
        assert store.get_active_run() is None
        latest = store.get_latest_run()
        assert latest is not None
        assert latest.state == "completed"

        # Start a new run and halt it
        run2 = store.start_soak()
        assert run2.run_index == 1
        store.halt_soak("manual operator abort")
        assert store.get_active_run() is None
        latest2 = store.get_latest_run()
        assert latest2 is not None
        assert latest2.state == "halted"
        assert latest2.reason == "manual operator abort"
    finally:
        store.close()


def test_soak_store_rejects_backdated_start(tmp_path: Path) -> None:
    """Day 0 must be real elapsed time, never a backfilled date."""
    now = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    store = SoakStore(db_path=tmp_path / "test.duckdb", now_fn=lambda: now)
    try:
        with pytest.raises(SoakStartTimeError):
            store.start_soak(
                started_at=now - MAX_START_BACKDATE - timedelta(minutes=1)
            )
        assert store.get_active_run() is None
        # The tolerance still admits a start a few minutes ago (clock skew
        # and the gap between reading the clock and writing the row).
        run = store.start_soak(started_at=now - timedelta(minutes=2))
        assert run.started_at == now - timedelta(minutes=2)
    finally:
        store.close()


def test_soak_store_rejects_future_start(tmp_path: Path) -> None:
    now = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    store = SoakStore(db_path=tmp_path / "test.duckdb", now_fn=lambda: now)
    try:
        with pytest.raises(SoakStartTimeError):
            store.start_soak(started_at=now + timedelta(hours=1))
        assert store.get_active_run() is None
    finally:
        store.close()
