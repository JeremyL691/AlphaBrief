"""Append-only order transition store (M06-W03).

Persists immutable broker transition facts and derives current
projections deterministically. Duplicate transition IDs are ignored
idempotently; out-of-order or conflicting transitions are quarantined
(recorded separately, never applied) and terminal projections are never
mutated — a fill is never fabricated.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
from pydantic import BaseModel, ConfigDict

from alphabrief_execution.broker.oanda.transitions import (
    OrderProjection,
    OrderTransition,
    apply_transition,
)

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS order_transitions (
    transition_id  TEXT PRIMARY KEY,
    order_id       TEXT NOT NULL,
    related_id     TEXT,
    kind           TEXT NOT NULL,
    before_state   TEXT,
    after_state    TEXT,
    quantity       TEXT NOT NULL,
    price          TEXT,
    reason         TEXT,
    financing      TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    occurred_at    TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS order_transition_rejections (
    transition_id TEXT PRIMARY KEY,
    order_id      TEXT NOT NULL,
    reason        TEXT NOT NULL,
    rejected_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS order_projections (
    order_id         TEXT PRIMARY KEY,
    state            TEXT NOT NULL,
    open_quantity    TEXT NOT NULL,
    filled_quantity  TEXT NOT NULL,
    average_price    TEXT,
    correlation_id   TEXT NOT NULL,
    updated_at       TIMESTAMPTZ NOT NULL
);
"""


class TransitionStoreSummary(BaseModel):
    """One deterministic record outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transition_id: str
    applied: bool
    rejected_reason: str | None = None


class OrderTransitionStore:
    """DuckDB-backed append-only transition store."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _default_db_path()
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._conn.execute(_CREATE_TABLES)

    def record(self, transition: OrderTransition) -> TransitionStoreSummary:
        """Append one transition fact and update its projection.

        Duplicate transition IDs are ignored idempotently; conflicting
        or out-of-order transitions are quarantined without mutating
        terminal projections; a fill is never fabricated.
        """
        existing = self._conn.execute(
            "SELECT transition_id FROM order_transitions WHERE transition_id = ?",
            [transition.transition_id],
        ).fetchone()
        if existing is not None:
            return TransitionStoreSummary(
                transition_id=transition.transition_id, applied=False
            )

        projection = self.projection(transition.order_id)
        updated, rejection = apply_transition(projection, transition)
        if rejection is not None:
            self._quarantine(transition, rejection.reason)
            return TransitionStoreSummary(
                transition_id=transition.transition_id,
                applied=False,
                rejected_reason=rejection.reason,
            )
        assert updated is not None, "an applied transition always yields a projection"

        self._conn.execute("BEGIN")
        try:
            self._conn.execute(
                """
                INSERT INTO order_transitions (
                    transition_id, order_id, related_id, kind,
                    before_state, after_state, quantity, price,
                    reason, financing, correlation_id, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    transition.transition_id,
                    transition.order_id,
                    transition.related_id,
                    transition.kind,
                    projection.state if projection else None,
                    updated.state,
                    str(transition.quantity),
                    str(transition.price) if transition.price is not None else None,
                    transition.reason,
                    str(transition.financing),
                    transition.correlation_id,
                    transition.occurred_at,
                ],
            )
            self._conn.execute(
                """
                INSERT INTO order_projections (
                    order_id, state, open_quantity, filled_quantity,
                    average_price, correlation_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (order_id) DO UPDATE SET
                    state = EXCLUDED.state,
                    open_quantity = EXCLUDED.open_quantity,
                    filled_quantity = EXCLUDED.filled_quantity,
                    average_price = EXCLUDED.average_price,
                    correlation_id = EXCLUDED.correlation_id,
                    updated_at = EXCLUDED.updated_at
                """,
                [
                    updated.order_id,
                    updated.state,
                    str(updated.open_quantity),
                    str(updated.filled_quantity),
                    (
                        str(updated.average_price)
                        if updated.average_price is not None
                        else None
                    ),
                    updated.correlation_id,
                    updated.updated_at,
                ],
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return TransitionStoreSummary(
            transition_id=transition.transition_id, applied=True
        )

    def projection(self, order_id: str) -> OrderProjection | None:
        row = self._conn.execute(
            """SELECT order_id, state, open_quantity, filled_quantity,
                      average_price, correlation_id, updated_at
               FROM order_projections WHERE order_id = ?""",
            [order_id],
        ).fetchone()
        if row is None:
            return None
        return OrderProjection(
            order_id=str(row[0]),
            state=str(row[1]),  # type: ignore[arg-type]
            open_quantity=Decimal(str(row[2])),
            filled_quantity=Decimal(str(row[3])),
            average_price=Decimal(str(row[4])) if row[4] is not None else None,
            correlation_id=str(row[5]),
            updated_at=row[6],
        )

    def rejections(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT transition_id, order_id, reason, rejected_at
               FROM order_transition_rejections
               ORDER BY rejected_at DESC LIMIT ?""",
            [limit],
        ).fetchall()
        return [
            {
                "transition_id": str(row[0]),
                "order_id": str(row[1]),
                "reason": str(row[2]),
                "rejected_at": str(row[3]),
            }
            for row in rows
        ]

    def transition_count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM order_transitions"
        ).fetchone()
        return int(row[0]) if row else 0

    def _quarantine(self, transition: OrderTransition, reason: str) -> None:
        self._conn.execute(
            """
            INSERT INTO order_transition_rejections (
                transition_id, order_id, reason
            ) VALUES (?, ?, ?)
            ON CONFLICT (transition_id) DO NOTHING
            """,
            [transition.transition_id, transition.order_id, reason],
        )

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


def _default_db_path() -> Path:
    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    base = Path(env_dir) if env_dir else Path.home() / ".alphabrief" / "data"
    return base / "alphabrief.db"


__all__ = [
    "OrderTransitionStore",
    "TransitionStoreSummary",
]
