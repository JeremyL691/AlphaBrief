"""Immutable persisted RiskDecision records (M08-W07).

Every approved decision is persisted before execution with immutable
rule order, inputs and policy hashes, source IDs, timestamps, approved
flag, max quantity, reasons, tags, context freshness, and decision
expiry (REQ-RISK-009, AC-M08-W07-01). Records are append-only: there is
no API to modify the approved flag, inputs, or hashes after approval —
the only state transition is a compare-and-set ``consume`` marking an
executed decision as already consumed.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
from pydantic import BaseModel, ConfigDict, Field, field_validator


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("risk decision decimal values must not be floats")
    return value


class RiskDecisionRecord(BaseModel):
    """One immutable persisted risk decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_id: str = Field(min_length=1)
    intent_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    approved: bool
    reason: str = Field(min_length=1)
    max_quantity: Decimal | None = None
    risk_tags: tuple[str, ...] = ()
    policy_hash: str = Field(min_length=1)
    inputs_hash: str = Field(min_length=1)
    snapshot_hash: str | None = None
    rule_results: str = ""
    source_ids: tuple[str, ...] = ()
    context_freshness: bool = False
    created_at: datetime
    expiry_at: datetime | None = None
    consumed: bool = False
    consumed_at: datetime | None = None

    @field_validator("max_quantity", mode="before")
    @classmethod
    def max_quantity_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)

    def is_expired(self, now: datetime | None = None) -> bool:
        """True when the decision has passed its expiry."""
        if self.expiry_at is None:
            return False
        return (now or datetime.now(UTC)) > self.expiry_at


class RiskDecisionStoreError(RuntimeError):
    """A classified risk-decision store failure (always fail-closed)."""

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        self.detail = detail
        super().__init__(f"risk decision store failed ({kind}): {detail}")


_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS risk_decisions (
    decision_id      TEXT PRIMARY KEY,
    intent_id        TEXT NOT NULL,
    account_id       TEXT NOT NULL,
    approved         BOOLEAN NOT NULL,
    reason           TEXT NOT NULL,
    max_quantity     TEXT,
    risk_tags        TEXT NOT NULL,
    policy_hash      TEXT NOT NULL,
    inputs_hash      TEXT NOT NULL,
    snapshot_hash    TEXT,
    rule_results     TEXT NOT NULL,
    source_ids       TEXT NOT NULL,
    context_freshness BOOLEAN NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL,
    expiry_at        TIMESTAMPTZ,
    consumed         BOOLEAN NOT NULL DEFAULT FALSE,
    consumed_at      TIMESTAMPTZ
);
"""


class RiskDecisionStore:
    """DuckDB-backed append-only risk decision store."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _default_db_path()
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._conn.execute(_CREATE_TABLES)

    def persist(self, record: RiskDecisionRecord) -> bool:
        """Persist one immutable record; a duplicate ID is ignored.

        There is no update path: the approved flag, inputs, hashes,
        reason, tags, and rule results can never be mutated after
        approval (REQ-RISK-009).
        """
        inserted = self._conn.execute(
            """
            INSERT OR IGNORE INTO risk_decisions (
                decision_id, intent_id, account_id, approved, reason,
                max_quantity, risk_tags, policy_hash, inputs_hash,
                snapshot_hash, rule_results, source_ids,
                context_freshness, created_at, expiry_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                record.decision_id,
                record.intent_id,
                record.account_id,
                record.approved,
                record.reason,
                str(record.max_quantity) if record.max_quantity is not None else None,
                ",".join(record.risk_tags),
                record.policy_hash,
                record.inputs_hash,
                record.snapshot_hash,
                record.rule_results,
                ",".join(record.source_ids),
                record.context_freshness,
                record.created_at,
                record.expiry_at,
            ],
        ).fetchone()
        return bool(inserted and inserted[0] > 0)

    def get(self, decision_id: str) -> RiskDecisionRecord | None:
        row = self._conn.execute(
            """
            SELECT decision_id, intent_id, account_id, approved, reason,
                   max_quantity, risk_tags, policy_hash, inputs_hash,
                   snapshot_hash, rule_results, source_ids,
                   context_freshness, created_at, expiry_at, consumed,
                   consumed_at
            FROM risk_decisions WHERE decision_id = ?
            """,
            [decision_id],
        ).fetchone()
        if row is None:
            return None
        return RiskDecisionRecord(
            decision_id=str(row[0]),
            intent_id=str(row[1]),
            account_id=str(row[2]),
            approved=bool(row[3]),
            reason=str(row[4]),
            max_quantity=Decimal(str(row[5])) if row[5] is not None else None,
            risk_tags=tuple(str(row[6]).split(",")) if row[6] else (),
            policy_hash=str(row[7]),
            inputs_hash=str(row[8]),
            snapshot_hash=str(row[9]) if row[9] is not None else None,
            rule_results=str(row[10]),
            source_ids=tuple(str(row[11]).split(",")) if row[11] else (),
            context_freshness=bool(row[12]),
            created_at=row[13],
            expiry_at=row[14],
            consumed=bool(row[15]),
            consumed_at=row[16],
        )

    def consume(self, decision_id: str, *, owner: str) -> bool:
        """CAS: mark an unconsumed decision as consumed exactly once.

        A second consume (or a consume of an unknown decision) returns
        False — an already-executed decision can never be re-executed.
        """
        if not owner.strip():
            raise RiskDecisionStoreError("invalid_owner", "owner must not be empty")
        updated = self._conn.execute(
            """
            UPDATE risk_decisions
            SET consumed = TRUE, consumed_at = ?
            WHERE decision_id = ? AND consumed = FALSE
            """,
            [datetime.now(UTC), decision_id],
        ).fetchone()
        return bool(updated and updated[0] > 0)

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
    "RiskDecisionRecord",
    "RiskDecisionStore",
    "RiskDecisionStoreError",
]
