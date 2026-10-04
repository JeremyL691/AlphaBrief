"""Tests for SoakStore lifecycle and persistence (PROJECT_GUIDE S10)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from alphabrief_trader.soak_store import SoakStore


def test_soak_store_initial_state_empty(tmp_path: Path) -> None:
    store = SoakStore(db_path=tmp_path / "test.duckdb")
    try:
        assert store.get_active_run() is None
        assert store.get_latest_run() is None
        assert store.list_runs() == []
    finally:
        store.close()


def test_soak_store_start_run_creates_active(tmp_path: Path) -> None:
    store = SoakStore(db_path=tmp_path / "test.duckdb")
    try:
        t0 = datetime(2026, 10, 4, 4, 0, tzinfo=UTC)
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
    store = SoakStore(db_path=tmp_path / "test.duckdb")
    try:
        t0 = datetime(2026, 10, 4, 4, 0, tzinfo=UTC)
        run0 = store.start_soak(started_at=t0)
        assert run0.run_index == 0

        t1 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
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
