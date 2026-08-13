"""Proposal → risk → execution → reconciliation correlation chain (M11-W06).

Submit occurs only when the proposal, OrderIntent, broker-fresh inputs,
immutable RiskDecision, execution enablement, and idempotency mapping
share one correlation chain; each order submits at most once (the
idempotency map is check-and-insert, persisted before any broker call is
repeated); every broker outcome triggers immediate reconciliation whose
linked order/transaction/trade/position/account evidence is persisted
before report completion.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphabrief_trader.db_schema import apply_ai_trading_schema


class CorrelationChain(BaseModel):
    """One immutable correlation chain across the whole cycle."""

    model_config = ConfigDict(extra="forbid")

    cycle_id: str = Field(min_length=1)
    trading_date: str = Field(min_length=1)
    proposal_ids: list[str] = Field(default_factory=list)
    intent_ids: list[str] = Field(default_factory=list)
    decision_ids: list[str] = Field(default_factory=list)
    client_order_ids: list[str] = Field(default_factory=list)
    broker_order_ids: list[str] = Field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True)


class ReconciliationEvidence(BaseModel):
    """Immediate post-trade reconciliation evidence (before report)."""

    model_config = ConfigDict(extra="forbid")

    cycle_id: str = Field(min_length=1)
    attempt_count: int = Field(ge=0)
    order_ids: list[str] = Field(default_factory=list)
    matched: bool
    account_snapshot: dict[str, str] = Field(default_factory=dict)
    detail: str = Field(min_length=1)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _tz(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value


class IdempotencyMap:
    """Persisted check-and-insert idempotency mapping (at-most-once)."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        clock: Any = None,
    ) -> None:
        if db_path is None:
            import os

            env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
            db_dir = Path(env_dir) if env_dir else Path.home() / ".alphabrief" / "data"
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = db_dir / "alphabrief.db"
        self._db_path = Path(db_path)
        self._conn = duckdb.connect(str(self._db_path))
        apply_ai_trading_schema(self._conn)
        self._clock = clock or (lambda: datetime.now(UTC))

    def existing(self, client_order_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT client_order_id, cycle_id, intent_id, broker_order_id "
            "FROM cycle_idempotency WHERE client_order_id = ?",
            [client_order_id],
        ).fetchone()
        if row is None:
            return None
        return {
            "client_order_id": str(row[0]),
            "cycle_id": str(row[1]),
            "intent_id": str(row[2]),
            "broker_order_id": row[3],
        }

    def register(
        self,
        *,
        client_order_id: str,
        cycle_id: str,
        intent_id: str,
        broker_order_id: str | None,
    ) -> bool:
        """Insert the mapping; False when the key already exists."""
        self._conn.execute("BEGIN")
        try:
            row = self._conn.execute(
                "SELECT client_order_id FROM cycle_idempotency "
                "WHERE client_order_id = ?",
                [client_order_id],
            ).fetchone()
            if row is not None:
                self._conn.execute("ROLLBACK")
                return False
            self._conn.execute(
                """
                INSERT INTO cycle_idempotency (
                    client_order_id, cycle_id, intent_id, broker_order_id,
                    submitted_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                [client_order_id, cycle_id, intent_id, broker_order_id, self._clock()],
            )
            self._conn.execute("COMMIT")
            return True
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


__all__ = [
    "CorrelationChain",
    "IdempotencyMap",
    "ReconciliationEvidence",
]
