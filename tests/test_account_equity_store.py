"""R21.3 — account equity snapshot store (DuckDB-backed).

The store is the only persistence boundary for daily-loss + drawdown
state. Two invariants are exercised here:

* **HWM persists across a store reopen** — closing the connection and
  re-opening against the same file returns the same peak, so the
  drawdown floor is tighten-only across restarts.
* **Day-start equity is per UTC calendar day** — the earliest snapshot
  on a given ``captured_at`` calendar date is the day-start equity.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from alphabrief_api.db import PaperStore

ACCOUNT = "paper_local"


def _fresh_store(tmp_path: Path) -> PaperStore:
    """Build a PaperStore against an isolated DuckDB file."""
    db_dir = tmp_path / "alphabrief_db"
    db_dir.mkdir(parents=True, exist_ok=True)
    import os

    os.environ["ALPHABRIEF_DATA_DIR"] = str(db_dir)
    return PaperStore(db_path=db_dir / "alphabrief.db")


def _ts(day: int, hour: int = 14) -> datetime:
    return (
        datetime(2026, 6, 22, hour, 0, tzinfo=UTC)
        if day == 22
        else datetime(2026, 6, day, hour, 0, tzinfo=UTC)
    )


def test_save_and_read_back_latest_equity(tmp_path: Path) -> None:
    store = _fresh_store(tmp_path)
    try:
        assert store.get_latest_equity(ACCOUNT) is None
        store.save_equity_snapshot(ACCOUNT, _ts(22, 10), Decimal("100000"))
        store.save_equity_snapshot(ACCOUNT, _ts(22, 12), Decimal("101000"))
        assert store.get_latest_equity(ACCOUNT) == Decimal("101000")
    finally:
        store.close()


def test_high_water_mark_persists_across_store_reopen(tmp_path: Path) -> None:
    # First store instance writes a peak.
    store1 = _fresh_store(tmp_path)
    store1.save_equity_snapshot(ACCOUNT, _ts(22, 10), Decimal("100000"))
    store1.save_equity_snapshot(ACCOUNT, _ts(22, 12), Decimal("120000"))
    store1.save_equity_snapshot(ACCOUNT, _ts(22, 14), Decimal("110000"))  # drawdown
    hwm_before = store1.get_high_water_mark(ACCOUNT)
    store1.close()

    # Reopen against the same file — HWM must survive (tighten-only across
    # restarts; an in-memory HWM would reset and silently widen the floor).
    store2 = PaperStore(db_path=tmp_path / "alphabrief_db" / "alphabrief.db")
    try:
        assert store2.get_high_water_mark(ACCOUNT) == Decimal("120000")
        assert hwm_before == Decimal("120000")
    finally:
        store2.close()


def test_high_water_mark_is_zero_for_untouched_account(tmp_path: Path) -> None:
    store = _fresh_store(tmp_path)
    try:
        assert store.get_high_water_mark(ACCOUNT) is None
    finally:
        store.close()


def test_day_start_equity_returns_earliest_snapshot_in_day(tmp_path: Path) -> None:
    store = _fresh_store(tmp_path)
    try:
        store.save_equity_snapshot(ACCOUNT, _ts(22, 10), Decimal("100000"))
        store.save_equity_snapshot(ACCOUNT, _ts(22, 12), Decimal("99000"))
        store.save_equity_snapshot(ACCOUNT, _ts(22, 14), Decimal("98000"))
        assert store.get_day_start_equity(ACCOUNT, date(2026, 6, 22)) == Decimal(
            "100000"
        )
    finally:
        store.close()


def test_day_start_equity_is_per_calendar_day(tmp_path: Path) -> None:
    store = _fresh_store(tmp_path)
    try:
        store.save_equity_snapshot(ACCOUNT, _ts(22, 23), Decimal("100000"))
        # No snapshot on the 23rd yet.
        assert store.get_day_start_equity(ACCOUNT, date(2026, 6, 23)) is None
        # First snapshot on the 23rd sets the day-start.
        store.save_equity_snapshot(ACCOUNT, _ts(23, 9), Decimal("95000"))
        assert store.get_day_start_equity(ACCOUNT, date(2026, 6, 23)) == Decimal(
            "95000"
        )
        # A later same-day snapshot is not the day-start.
        store.save_equity_snapshot(ACCOUNT, _ts(23, 14), Decimal("93000"))
        assert store.get_day_start_equity(ACCOUNT, date(2026, 6, 23)) == Decimal(
            "95000"
        )
    finally:
        store.close()


def test_equity_snapshot_records_realized_pnl_day(tmp_path: Path) -> None:
    # The realized_pnl_day column is persisted alongside equity. The store
    # round-trips it on read by virtue of writing through the same table;
    # this test pins the column behavior so a future schema change is
    # caught explicitly.
    store = _fresh_store(tmp_path)
    try:
        store.save_equity_snapshot(
            ACCOUNT, _ts(22, 10), Decimal("100000"), realized_pnl_day=Decimal("50")
        )
        rows = store._conn.execute(
            "SELECT realized_pnl_day FROM account_equity_snapshots "
            "WHERE account_id = ?",
            [ACCOUNT],
        ).fetchall()
        assert rows and Decimal(str(rows[0][0])) == Decimal("50")
    finally:
        store.close()
