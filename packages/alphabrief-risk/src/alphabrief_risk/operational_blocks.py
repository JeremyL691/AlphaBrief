"""Operational health blocks for new exposure (M08-W06).

Kill switch, open freeze, stale broker, unresolved reconciliation diff,
transaction gap, failed required backup, lost writer lease, and
unhealthy scheduler each block new exposure with a distinct persisted
rule result (REQ-RISK-007, AC-M08-W06-01). Missing health evidence for a
configured condition fails closed — an unverifiable system state never
silently unblocks execution.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from pydantic import BaseModel, ConfigDict, Field


class OperationalHealthEvidence(BaseModel):
    """One typed snapshot of every operational health condition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kill_switch_active: bool | None = None
    freeze_open: bool | None = None
    broker_stale: bool | None = None
    reconciliation_diff_unresolved: bool | None = None
    transaction_gap_open: bool | None = None
    backup_failed: bool | None = None
    writer_lease_lost: bool | None = None
    scheduler_unhealthy: bool | None = None
    captured_at: datetime
    source_id: str = Field(min_length=1)


class OperationalBlockResult(BaseModel):
    """One stable typed operational-block verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    condition: str = Field(min_length=1)
    blocked: bool
    detail: str = Field(min_length=1)


class OperationalBlockError(RuntimeError):
    """Raised when new exposure is blocked by an unhealthy condition."""

    def __init__(self, conditions: list[str], detail: str) -> None:
        self.conditions = conditions
        super().__init__(f"new exposure blocked: {detail}")


#: Every condition evaluated by the operational health layer.
ALL_CONDITIONS: tuple[str, ...] = (
    "kill_switch",
    "freeze",
    "stale_broker",
    "reconciliation_diff",
    "transaction_gap",
    "backup_failure",
    "writer_lease",
    "scheduler_health",
)


def evaluate_operational_blocks(
    evidence: OperationalHealthEvidence,
    *,
    require_evidence: tuple[str, ...] = ALL_CONDITIONS,
) -> tuple[OperationalBlockResult, ...]:
    """Evaluate every health condition into a distinct rule result.

    A condition whose evidence is missing while it is in
    ``require_evidence`` fails closed (blocked with an unverifiable
    reason). A condition outside ``require_evidence`` with missing
    evidence is recorded as unblocked-but-unverified so it never blocks
    silently and never fabricates a clean bill of health.
    """
    flags: dict[str, bool | None] = {
        "kill_switch": evidence.kill_switch_active,
        "freeze": evidence.freeze_open,
        "stale_broker": evidence.broker_stale,
        "reconciliation_diff": evidence.reconciliation_diff_unresolved,
        "transaction_gap": evidence.transaction_gap_open,
        "backup_failure": evidence.backup_failed,
        "writer_lease": evidence.writer_lease_lost,
        "scheduler_health": evidence.scheduler_unhealthy,
    }
    results: list[OperationalBlockResult] = []
    for condition in ALL_CONDITIONS:
        value = flags[condition]
        if value is None:
            if condition in require_evidence:
                results.append(
                    OperationalBlockResult(
                        condition=condition,
                        blocked=True,
                        detail=f"{condition} evidence missing; fails closed",
                    )
                )
            else:
                results.append(
                    OperationalBlockResult(
                        condition=condition,
                        blocked=False,
                        detail=f"{condition} evidence missing; unverified",
                    )
                )
            continue
        if value:
            results.append(
                OperationalBlockResult(
                    condition=condition,
                    blocked=True,
                    detail=f"{condition} is unhealthy",
                )
            )
        else:
            results.append(
                OperationalBlockResult(
                    condition=condition,
                    blocked=False,
                    detail=f"{condition} is healthy",
                )
            )
    return tuple(results)


def blocking_conditions(
    results: tuple[OperationalBlockResult, ...],
) -> tuple[str, ...]:
    """The distinct conditions blocking new exposure."""
    return tuple(
        result.condition for result in results if result.blocked
    )


class OperationalBlockStore:
    """DuckDB-backed durable record of operational block verdicts."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _default_db_path()
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operational_block_results (
                record_id   BIGINT PRIMARY KEY,
                account_id  TEXT NOT NULL,
                condition   TEXT NOT NULL,
                blocked     BOOLEAN NOT NULL,
                detail      TEXT NOT NULL,
                captured_at TIMESTAMPTZ NOT NULL
            )
            """
        )

    def persist(
        self,
        account_id: str,
        results: tuple[OperationalBlockResult, ...],
        *,
        captured_at: datetime | None = None,
    ) -> int:
        """Append one immutable row per condition verdict."""
        now = captured_at or datetime.now(UTC)
        for result in results:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(record_id), 0) + 1 FROM operational_block_results"
            ).fetchone()
            record_id = int(row[0]) if row else 1
            self._conn.execute(
                """
                INSERT INTO operational_block_results (
                    record_id, account_id, condition, blocked, detail, captured_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    record_id,
                    account_id,
                    result.condition,
                    result.blocked,
                    result.detail,
                    now,
                ],
            )
        return len(results)

    def latest(self, account_id: str) -> list[dict[str, Any]]:
        """The most recent verdict per condition (distinct, persisted)."""
        rows = self._conn.execute(
            """
            SELECT condition, blocked, detail, captured_at
            FROM operational_block_results
            WHERE account_id = ? AND record_id IN (
                SELECT MAX(record_id) FROM operational_block_results
                WHERE account_id = ? GROUP BY condition
            )
            ORDER BY condition
            """,
            [account_id, account_id],
        ).fetchall()
        return [
            {
                "condition": str(row[0]),
                "blocked": bool(row[1]),
                "detail": str(row[2]),
                "captured_at": str(row[3]),
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


__all__ = [
    "ALL_CONDITIONS",
    "OperationalBlockError",
    "OperationalBlockResult",
    "OperationalBlockStore",
    "OperationalHealthEvidence",
    "blocking_conditions",
    "evaluate_operational_blocks",
]
