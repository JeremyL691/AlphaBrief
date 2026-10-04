"""DuckDB store for soak runs (PROJECT_GUIDE S9, S10, S11).

Persists and retrieves soak execution runs from the ``soak_runs`` table
created in schema migration 5. Every write is transaction-safe and uses
UTC timestamps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from alphabrief_core import paths as _paths

CREATE_SOAK_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS soak_runs (
    run_index        INTEGER NOT NULL,
    started_at       TIMESTAMPTZ NOT NULL,
    state            TEXT NOT NULL,
    reason           TEXT,
    superseded_by    INTEGER,
    created_at       TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_index)
)
"""


@dataclass(frozen=True)
class SoakRun:
    """A single continuous soak test run record."""

    run_index: int
    started_at: datetime
    state: str  # "active" | "reset" | "completed" | "halted"
    reason: str | None
    superseded_by: int | None
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_index": self.run_index,
            "started_at": self.started_at.isoformat(),
            "state": self.state,
            "reason": self.reason,
            "superseded_by": self.superseded_by,
            "created_at": self.created_at.isoformat(),
        }


def _parse_dt(val: Any) -> datetime:
    if isinstance(val, datetime):
        return val.astimezone(UTC) if val.tzinfo else val.replace(tzinfo=UTC)
    s = str(val).strip().replace("Z", "+00:00")
    if s.endswith("UTC"):
        s = s[:-3].strip() + "+00:00"
    dt = datetime.fromisoformat(s)
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def _row_to_run(row: tuple[Any, ...]) -> SoakRun:
    return SoakRun(
        run_index=int(row[0]),
        started_at=_parse_dt(row[1]),
        state=str(row[2]),
        reason=str(row[3]) if row[3] is not None else None,
        superseded_by=int(row[4]) if row[4] is not None else None,
        created_at=_parse_dt(row[5]),
    )


class SoakStore:
    """Store for managing soak run lifecycles in DuckDB."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _paths.db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._conn.execute(CREATE_SOAK_RUNS_TABLE)

    def get_active_run(self) -> SoakRun | None:
        """Return the active soak run, or None if no active run exists."""
        row = self._conn.execute(
            """
            SELECT run_index, started_at, state, reason, superseded_by, created_at
            FROM soak_runs
            WHERE state = 'active'
            ORDER BY run_index DESC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        return _row_to_run(row)

    def get_latest_run(self) -> SoakRun | None:
        """Return the most recently created soak run, regardless of state."""
        row = self._conn.execute(
            """
            SELECT run_index, started_at, state, reason, superseded_by, created_at
            FROM soak_runs
            ORDER BY run_index DESC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        return _row_to_run(row)

    def start_soak(self, started_at: datetime | None = None) -> SoakRun:
        """Start a new soak run or return the currently active one.

        If a soak is already active, it is returned without modification.
        Otherwise, a new active run is created with run_index incremented.
        """
        active = self.get_active_run()
        if active is not None:
            return active

        now = datetime.now(UTC)
        start_time = started_at or now
        latest = self.get_latest_run()
        next_index = (latest.run_index + 1) if latest else 0

        self._conn.execute(
            """
            INSERT INTO soak_runs (
                run_index, started_at, state, reason, superseded_by, created_at
            )
            VALUES (?, ?, 'active', NULL, NULL, ?)
            """,
            [next_index, start_time.isoformat(), now.isoformat()],
        )
        return SoakRun(
            run_index=next_index,
            started_at=start_time,
            state="active",
            reason=None,
            superseded_by=None,
            created_at=now,
        )

    def record_reset(
        self,
        reason: str,
        *,
        new_started_at: datetime | None = None,
    ) -> SoakRun:
        """Reset the current active soak run and start a new one from Day 0."""
        now = datetime.now(UTC)
        active = self.get_active_run()
        latest = self.get_latest_run()
        next_index = (latest.run_index + 1) if latest else 0

        if active is not None:
            self._conn.execute(
                """
                UPDATE soak_runs
                SET state = 'reset', reason = ?, superseded_by = ?
                WHERE run_index = ?
                """,
                [reason, next_index, active.run_index],
            )

        start_time = new_started_at or now
        self._conn.execute(
            """
            INSERT INTO soak_runs (
                run_index, started_at, state, reason, superseded_by, created_at
            )
            VALUES (?, ?, 'active', NULL, NULL, ?)
            """,
            [next_index, start_time.isoformat(), now.isoformat()],
        )
        return SoakRun(
            run_index=next_index,
            started_at=start_time,
            state="active",
            reason=None,
            superseded_by=None,
            created_at=now,
        )

    def complete_soak(self) -> None:
        """Mark the active soak run as completed (14 qualified days)."""
        active = self.get_active_run()
        if active is not None:
            self._conn.execute(
                "UPDATE soak_runs SET state = 'completed' WHERE run_index = ?",
                [active.run_index],
            )

    def halt_soak(self, reason: str) -> None:
        """Mark the active soak run as halted."""
        active = self.get_active_run()
        if active is not None:
            self._conn.execute(
                "UPDATE soak_runs SET state = 'halted', reason = ? WHERE run_index = ?",
                [reason, active.run_index],
            )

    def list_runs(self) -> list[SoakRun]:
        """Return all soak runs ordered by run_index ASC."""
        rows = self._conn.execute(
            """
            SELECT run_index, started_at, state, reason, superseded_by, created_at
            FROM soak_runs
            ORDER BY run_index ASC
            """
        ).fetchall()
        return [_row_to_run(r) for r in rows]

    def close(self) -> None:
        self._conn.close()


__all__ = ["SoakRun", "SoakStore"]
