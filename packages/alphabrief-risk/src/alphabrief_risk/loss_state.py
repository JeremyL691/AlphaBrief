"""Durable day, high-water, and loss-streak state (M08-W04).

DuckDB-backed state that survives restart and can never reset, move
backward, or be replaced with current equity to widen an allowable
limit (AC-M08-W04-02):

- the high-water mark only ever moves up (compare-and-set);
- the day-start equity for a date is first-write-wins — a later same-day
  value can never replace it;
- the consecutive-loss streak derives from recorded day results and only
  resets to zero on an evidence-backed profitable day;
- before the first recorded day every read returns ``None`` so the
  configured rules fail closed instead of silently disabling themselves
  (AC-M08-W04-03).
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
from pydantic import BaseModel, ConfigDict, Field

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS account_loss_state (
    account_id         TEXT PRIMARY KEY,
    high_water_mark    TEXT,
    consecutive_losses BIGINT,
    updated_at         TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS account_day_results (
    account_id       TEXT NOT NULL,
    day_date         DATE NOT NULL,
    day_start_equity TEXT NOT NULL,
    end_equity       TEXT NOT NULL,
    pnl              TEXT NOT NULL,
    recorded_at      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (account_id, day_date)
);
"""


class DayResultSummary(BaseModel):
    """One deterministic day-result record verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(min_length=1)
    day_date: date
    day_start_equity: Decimal
    end_equity: Decimal
    pnl: Decimal
    high_water_mark: Decimal | None
    consecutive_losses: int | None
    recorded: bool


class LossStateStore:
    """DuckDB-backed durable loss state with compare-and-set semantics."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _default_db_path()
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._conn.execute(_CREATE_TABLES)

    def record_day_result(
        self,
        account_id: str,
        *,
        day_date: date,
        day_start_equity: Decimal,
        end_equity: Decimal,
        owner: str,
    ) -> DayResultSummary:
        """Record one day result with forward-only state updates.

        The day-start equity for a date is first-write-wins; the
        high-water mark never moves down; the loss streak increments on
        a losing day and resets to zero on a profitable day.
        """
        if not account_id.strip():
            raise ValueError("account_id must not be empty")
        now = datetime.now(UTC)
        current_hwm = self.high_water_mark(account_id)
        current_streak = self.consecutive_losses(account_id)

        self._conn.execute("BEGIN")
        try:
            inserted = self._conn.execute(
                """
                INSERT INTO account_day_results (
                    account_id, day_date, day_start_equity, end_equity,
                    pnl, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (account_id, day_date) DO NOTHING
                """,
                [
                    account_id,
                    day_date,
                    str(day_start_equity),
                    str(end_equity),
                    str(end_equity - day_start_equity),
                    now,
                ],
            ).fetchone()
            recorded = bool(inserted and inserted[0] > 0)
            # The authoritative day start is the first recorded value.
            row = self._conn.execute(
                """SELECT day_start_equity, end_equity, pnl
                   FROM account_day_results
                   WHERE account_id = ? AND day_date = ?""",
                [account_id, day_date],
            ).fetchone()
            assert row is not None
            start = Decimal(str(row[0]))
            end = Decimal(str(row[1]))
            pnl = Decimal(str(row[2]))

            new_streak: int | None
            if current_streak is None:
                new_streak = 1 if pnl < 0 else 0
            else:
                new_streak = current_streak + 1 if pnl < 0 else 0
            new_hwm = (
                end if current_hwm is None else max(current_hwm, end)
            )
            self._conn.execute(
                """
                INSERT INTO account_loss_state (
                    account_id, high_water_mark, consecutive_losses, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT (account_id) DO UPDATE SET
                    high_water_mark = EXCLUDED.high_water_mark,
                    consecutive_losses = EXCLUDED.consecutive_losses,
                    updated_at = EXCLUDED.updated_at
                """,
                [account_id, str(new_hwm), new_streak, now],
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return DayResultSummary(
            account_id=account_id,
            day_date=day_date,
            day_start_equity=start,
            end_equity=end,
            pnl=pnl,
            high_water_mark=new_hwm,
            consecutive_losses=new_streak,
            recorded=recorded,
        )

    def high_water_mark(self, account_id: str) -> Decimal | None:
        row = self._conn.execute(
            "SELECT high_water_mark FROM account_loss_state WHERE account_id = ?",
            [account_id],
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return Decimal(str(row[0]))

    def day_start(self, account_id: str, day_date: date) -> Decimal | None:
        row = self._conn.execute(
            """SELECT day_start_equity FROM account_day_results
               WHERE account_id = ? AND day_date = ?""",
            [account_id, day_date],
        ).fetchone()
        if row is None:
            return None
        return Decimal(str(row[0]))

    def consecutive_losses(self, account_id: str) -> int | None:
        row = self._conn.execute(
            "SELECT consecutive_losses FROM account_loss_state WHERE account_id = ?",
            [account_id],
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return int(row[0])

    def day_results(self, account_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT day_date, day_start_equity, end_equity, pnl, recorded_at
               FROM account_day_results WHERE account_id = ?
               ORDER BY day_date""",
            [account_id],
        ).fetchall()
        return [
            {
                "day_date": str(row[0]),
                "day_start_equity": str(row[1]),
                "end_equity": str(row[2]),
                "pnl": str(row[3]),
                "recorded_at": str(row[4]),
            }
            for row in rows
        ]

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass


def _default_db_path() -> Path:
    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    base = Path(env_dir) if env_dir else Path.home() / ".alphabrief" / "data"
    return base / "alphabrief.db"


__all__ = ["DayResultSummary", "LossStateStore"]
