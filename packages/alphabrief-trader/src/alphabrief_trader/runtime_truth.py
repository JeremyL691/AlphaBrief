"""Persisted scheduler runtime truth (M11-W02).

The API and CLI task-status surfaces derive active configuration, the
leader ID, the running phase, heartbeat, last outcome, and next due
time from this single persisted authority, so every surface reports the
same executing runtime instead of guessing.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from alphabrief_trader.db_schema import apply_ai_trading_schema


def _default_db_dir() -> Path:
    import os

    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    return Path.home() / ".alphabrief" / "data"


def _default_db_path() -> Path:
    db_dir = _default_db_dir()
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "alphabrief.db"


class RuntimeTruthStore:
    """Single-row persisted scheduler runtime authority."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if db_path is None:
            db_path = _default_db_path()
        self._db_path = Path(db_path)
        self._conn = duckdb.connect(str(self._db_path))
        apply_ai_trading_schema(self._conn)
        self._clock = clock or (lambda: datetime.now(UTC))

    def update(
        self,
        *,
        leader_id: str | None,
        active_config: dict[str, Any] | None = None,
        running_phase: str | None = None,
        phase_started_at: datetime | None = None,
        last_outcome: str | None = None,
        failure_classification: str | None = None,
        next_due_at: datetime | None = None,
    ) -> None:
        """Upsert the single runtime-truth row."""
        self._conn.execute(
            """
            INSERT INTO scheduler_runtime (
                row_id, leader_id, active_config_json, running_phase,
                phase_started_at, heartbeat_at, last_outcome,
                failure_classification, next_due_at, updated_at
            )
            VALUES (1, ?, ?::JSON, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (row_id) DO UPDATE SET
                leader_id = EXCLUDED.leader_id,
                active_config_json = EXCLUDED.active_config_json,
                running_phase = EXCLUDED.running_phase,
                phase_started_at = EXCLUDED.phase_started_at,
                heartbeat_at = EXCLUDED.heartbeat_at,
                last_outcome = EXCLUDED.last_outcome,
                failure_classification = EXCLUDED.failure_classification,
                next_due_at = EXCLUDED.next_due_at,
                updated_at = EXCLUDED.updated_at
            """,
            [
                leader_id,
                json.dumps(active_config or {}, sort_keys=True),
                running_phase,
                phase_started_at,
                self._clock(),
                last_outcome,
                failure_classification,
                next_due_at,
                self._clock(),
            ],
        )

    def set_execution_mode(
        self,
        mode: str,
        reasons: list[str] | None = None,
    ) -> None:
        """Persist the current execution mode and its reasons."""
        self._conn.execute(
            """
            INSERT INTO execution_mode (row_id, mode, reasons_json, updated_at)
            VALUES (1, ?, ?::JSON, ?)
            ON CONFLICT (row_id) DO UPDATE SET
                mode = EXCLUDED.mode,
                reasons_json = EXCLUDED.reasons_json,
                updated_at = EXCLUDED.updated_at
            """,
            [mode, json.dumps(list(reasons or []), sort_keys=True), self._clock()],
        )

    def get_execution_mode(self) -> dict[str, Any] | None:
        """Return the persisted execution mode, or ``None`` when absent."""
        row = self._conn.execute(
            "SELECT mode, reasons_json, updated_at "
            "FROM execution_mode WHERE row_id = 1"
        ).fetchone()
        if row is None:
            return None
        reasons: object = row[1]
        return {
            "mode": str(row[0]),
            "reasons": (
                json.loads(reasons) if isinstance(reasons, str) else reasons
            ),
            "updated_at": row[2],
        }

    def heartbeat(self, *, leader_id: str, running_phase: str | None = None) -> None:
        """Refresh the heartbeat (and optional running phase) for the leader."""
        self._conn.execute(
            """
            UPDATE scheduler_runtime
            SET heartbeat_at = ?, running_phase = COALESCE(?, running_phase)
            WHERE row_id = 1 AND leader_id = ?
            """,
            [self._clock(), running_phase, leader_id],
        )

    def read(self) -> dict[str, Any] | None:
        """Return the persisted runtime truth, or ``None`` when absent."""
        row = self._conn.execute(
            "SELECT leader_id, active_config_json, running_phase, "
            "phase_started_at, heartbeat_at, last_outcome, "
            "failure_classification, next_due_at, updated_at "
            "FROM scheduler_runtime WHERE row_id = 1"
        ).fetchone()
        if row is None:
            return None
        config: object = row[1]
        return {
            "leader_id": row[0],
            "active_config": (
                json.loads(config) if isinstance(config, str) else config
            ),
            "running_phase": row[2],
            "phase_started_at": row[3],
            "heartbeat_at": row[4],
            "last_outcome": row[5],
            "failure_classification": row[6],
            "next_due_at": row[7],
            "updated_at": row[8],
        }

    def clear(self) -> None:
        self._conn.execute("DELETE FROM scheduler_runtime")

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


__all__ = ["RuntimeTruthStore"]
