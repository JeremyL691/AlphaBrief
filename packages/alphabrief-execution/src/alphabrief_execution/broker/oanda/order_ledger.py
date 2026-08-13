"""Local append-only order ledger with idempotency identities (M07-W01).

Atomically maps cycle, intent, risk decision, client request, client
extension, broker order, trade, and transaction identities into one
deterministic submit identity per ``(cycle_id, intent_id)``. Every
transition is a compare-and-set over immutable history: identity
collision, mismatched payload hash, stale owner, ambiguous in-flight
state, and missing approved decision freeze submission — never an
overwrite, fallback, or user question.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import duckdb
from pydantic import BaseModel, ConfigDict, Field

LedgerState = Literal[
    "RESERVED", "BOUND", "SUBMITTED", "COMPLETED", "FROZEN"
]

#: States that are terminal: no later compare-and-set may leave them.
_TERMINAL_STATES: frozenset[str] = frozenset({"COMPLETED", "FROZEN"})

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS order_ledger_reservations (
    submit_id      TEXT PRIMARY KEY,
    cycle_id       TEXT NOT NULL,
    intent_id      TEXT NOT NULL,
    decision_id    TEXT NOT NULL,
    payload_hash   TEXT NOT NULL,
    owner          TEXT NOT NULL,
    status         TEXT NOT NULL,
    broker_order_id TEXT,
    state          TEXT,
    transaction_id TEXT,
    created_at     TIMESTAMPTZ NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL,
    UNIQUE (cycle_id, intent_id)
);
CREATE TABLE IF NOT EXISTS order_ledger_events (
    event_id   BIGINT PRIMARY KEY,
    submit_id  TEXT NOT NULL,
    kind       TEXT NOT NULL,
    detail     TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS order_ledger_events_submit ON
    order_ledger_events (submit_id);
"""


class ReservationOutcome(BaseModel):
    """One deterministic reservation verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    submit_id: str = Field(min_length=1)
    status: LedgerState
    reused: bool = False


class LedgerTransitionError(RuntimeError):
    """A classified ledger transition failure (always fail-closed)."""

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        super().__init__(f"order ledger transition failed ({kind}): {detail}")


class OrderLedger:
    """DuckDB-backed append-only order ledger with CAS transitions."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _default_db_path()
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._conn.execute(_CREATE_TABLES)

    # ------------------------------------------------------------------
    # Reservation
    # ------------------------------------------------------------------

    def reserve(
        self,
        *,
        cycle_id: str,
        intent_id: str,
        decision_id: str,
        payload_hash: str,
        owner: str,
    ) -> ReservationOutcome:
        """Reserve the one deterministic submit identity.

        The submit identity is derived from ``(cycle_id, intent_id)``, so
        any replay of the same cycle and intent returns the same
        identity. A replay with a different decision or payload is an
        identity collision and freezes instead of overwriting.
        """
        submit_id = _submit_id(cycle_id, intent_id)
        existing = self._reservation_row(submit_id)
        if existing is not None:
            return self._replay_verdict(existing, decision_id, payload_hash, owner)
        now = datetime.now(UTC)
        try:
            self._conn.execute("BEGIN")
            self._conn.execute(
                """
                INSERT INTO order_ledger_reservations (
                    submit_id, cycle_id, intent_id, decision_id,
                    payload_hash, owner, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'RESERVED', ?, ?)
                """,
                [
                    submit_id,
                    cycle_id,
                    intent_id,
                    decision_id,
                    payload_hash,
                    owner,
                    now,
                    now,
                ],
            )
            self._append_event(submit_id, "RESERVED", f"cycle={cycle_id}")
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            # A concurrent reservation won the race: replay the verdict.
            existing = self._reservation_row(submit_id)
            if existing is not None:
                return self._replay_verdict(
                    existing, decision_id, payload_hash, owner
                )
            raise
        return ReservationOutcome(submit_id=submit_id, status="RESERVED")

    # ------------------------------------------------------------------
    # Compare-and-set transitions
    # ------------------------------------------------------------------

    def bind_decision(
        self,
        submit_id: str,
        *,
        decision_id: str,
        payload_hash: str,
        owner: str,
    ) -> None:
        """Bind the approved decision; CAS from RESERVED to BOUND."""
        reservation = self._require_reservation(submit_id)
        self._check_owner(reservation, owner)
        if reservation["decision_id"] != decision_id:
            raise LedgerTransitionError(
                "identity_collision",
                f"decision {decision_id!r} conflicts with reserved "
                f"{reservation['decision_id']!r}",
            )
        if reservation["payload_hash"] != payload_hash:
            raise LedgerTransitionError(
                "payload_mismatch",
                "payload hash differs from the reserved hash",
            )
        if reservation["status"] == "BOUND":
            return  # idempotent replay of the same bind
        if reservation["status"] in _TERMINAL_STATES:
            raise LedgerTransitionError(
                "state_conflict",
                f"cannot bind decision in terminal state {reservation['status']}",
            )
        if reservation["status"] == "SUBMITTED":
            raise LedgerTransitionError(
                "in_flight_ambiguous",
                "submit already attempted; resolve the outcome before binding",
            )
        self._cas_status(
            submit_id,
            expected="RESERVED",
            target="BOUND",
            kind="BIND",
            detail=f"decision={decision_id}",
        )

    def record_submit_attempt(
        self,
        submit_id: str,
        *,
        payload_hash: str,
        owner: str,
    ) -> None:
        """Record one submit attempt; CAS from BOUND to SUBMITTED.

        A missing approved decision, a mismatched payload, or an
        ambiguous in-flight state freezes submission instead of
        overwriting.
        """
        reservation = self._require_reservation(submit_id)
        self._check_owner(reservation, owner)
        if reservation["payload_hash"] != payload_hash:
            raise LedgerTransitionError(
                "payload_mismatch",
                "payload hash differs from the reserved hash",
            )
        if reservation["status"] == "SUBMITTED":
            raise LedgerTransitionError(
                "in_flight_ambiguous",
                "submit outcome unknown; resolve before any retry",
            )
        if reservation["status"] in _TERMINAL_STATES:
            raise LedgerTransitionError(
                "state_conflict",
                f"cannot submit in terminal state {reservation['status']}",
            )
        if reservation["status"] == "RESERVED":
            raise LedgerTransitionError(
                "missing_decision",
                "no approved decision bound; submission frozen",
            )
        self._cas_status(
            submit_id,
            expected="BOUND",
            target="SUBMITTED",
            kind="SUBMIT_ATTEMPT",
            detail=f"payload_hash={payload_hash}",
        )

    def record_broker_result(
        self,
        submit_id: str,
        *,
        broker_order_id: str,
        state: str,
        transaction_id: str | None,
        owner: str,
    ) -> None:
        """Record the broker result; CAS from SUBMITTED to COMPLETED."""
        reservation = self._require_reservation(submit_id)
        self._check_owner(reservation, owner)
        if (
            reservation["status"] == "COMPLETED"
            and reservation["broker_order_id"] == broker_order_id
        ):
            return  # idempotent replay of the same broker result
        if reservation["status"] in _TERMINAL_STATES:
            raise LedgerTransitionError(
                "state_conflict",
                f"cannot record result in terminal state {reservation['status']}",
            )
        detail = json.dumps(
            {"broker_order_id": broker_order_id, "state": state},
            sort_keys=True,
        )
        now = datetime.now(UTC)
        self._conn.execute("BEGIN")
        try:
            updated = self._conn.execute(
                """
                UPDATE order_ledger_reservations
                SET status = 'COMPLETED',
                    broker_order_id = ?,
                    state = ?,
                    transaction_id = ?,
                    updated_at = ?
                WHERE submit_id = ? AND status = 'SUBMITTED'
                """,
                [broker_order_id, state, transaction_id, now, submit_id],
            ).fetchone()
            if updated is None or updated[0] == 0:
                self._conn.execute("ROLLBACK")
                raise LedgerTransitionError(
                    "state_conflict",
                    f"submit {submit_id} is not in SUBMITTED state",
                )
            self._append_event(submit_id, "BROKER_RESULT", detail)
            self._conn.execute("COMMIT")
        except LedgerTransitionError:
            raise
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def record_related_id(
        self,
        submit_id: str,
        *,
        kind: str,
        related_id: str,
        owner: str,
    ) -> None:
        """Append one related broker identity (trade, transaction)."""
        reservation = self._require_reservation(submit_id)
        self._check_owner(reservation, owner)
        if reservation["status"] != "COMPLETED":
            raise LedgerTransitionError(
                "state_conflict",
                "related IDs are only recorded after a completed submit",
            )
        self._append_event(
            submit_id,
            "RELATED_ID",
            json.dumps({"kind": kind, "related_id": related_id}, sort_keys=True),
        )

    def freeze(self, submit_id: str, *, reason: str, owner: str) -> None:
        """Freeze a reservation; no further transition may leave FROZEN."""
        reservation = self._require_reservation(submit_id)
        self._check_owner(reservation, owner)
        if reservation["status"] in _TERMINAL_STATES:
            raise LedgerTransitionError(
                "state_conflict",
                f"cannot freeze terminal state {reservation['status']}",
            )
        self._cas_status(
            submit_id,
            expected=reservation["status"],
            target="FROZEN",
            kind="FREEZE",
            detail=reason,
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def reservation(self, submit_id: str) -> dict[str, Any] | None:
        return self._reservation_row(submit_id)

    def status(self, submit_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT status FROM order_ledger_reservations WHERE submit_id = ?",
            [submit_id],
        ).fetchone()
        return str(row[0]) if row else None

    def events(self, submit_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT event_id, kind, detail, created_at
               FROM order_ledger_events
               WHERE submit_id = ?
               ORDER BY event_id ASC LIMIT ?""",
            [submit_id, limit],
        ).fetchall()
        return [
            {
                "event_id": int(row[0]),
                "kind": str(row[1]),
                "detail": str(row[2]),
                "created_at": str(row[3]),
            }
            for row in rows
        ]

    def reservation_count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM order_ledger_reservations"
        ).fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _reservation_row(self, submit_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            """SELECT submit_id, cycle_id, intent_id, decision_id,
                      payload_hash, owner, status, broker_order_id, state,
                      transaction_id
               FROM order_ledger_reservations WHERE submit_id = ?""",
            [submit_id],
        ).fetchone()
        if row is None:
            return None
        return {
            "submit_id": str(row[0]),
            "cycle_id": str(row[1]),
            "intent_id": str(row[2]),
            "decision_id": str(row[3]),
            "payload_hash": str(row[4]),
            "owner": str(row[5]),
            "status": str(row[6]),
            "broker_order_id": str(row[7]) if row[7] is not None else None,
            "state": str(row[8]) if row[8] is not None else None,
            "transaction_id": str(row[9]) if row[9] is not None else None,
        }

    def _replay_verdict(
        self,
        reservation: dict[str, Any],
        decision_id: str,
        payload_hash: str,
        owner: str,
    ) -> ReservationOutcome:
        if reservation["decision_id"] != decision_id:
            raise LedgerTransitionError(
                "identity_collision",
                f"decision {decision_id!r} conflicts with reserved "
                f"{reservation['decision_id']!r}",
            )
        if reservation["payload_hash"] != payload_hash:
            raise LedgerTransitionError(
                "payload_mismatch",
                "payload hash differs from the reserved hash",
            )
        if reservation["owner"] != owner:
            raise LedgerTransitionError(
                "stale_owner",
                f"owner {owner!r} does not own submit {reservation['submit_id']!r}",
            )
        return ReservationOutcome(
            submit_id=reservation["submit_id"],
            status=reservation["status"],
            reused=True,
        )

    def _require_reservation(self, submit_id: str) -> dict[str, Any]:
        reservation = self._reservation_row(submit_id)
        if reservation is None:
            raise LedgerTransitionError(
                "missing_reservation",
                f"no reservation for submit {submit_id!r}",
            )
        return reservation

    def _check_owner(self, reservation: dict[str, Any], owner: str) -> None:
        if reservation["owner"] != owner:
            raise LedgerTransitionError(
                "stale_owner",
                f"owner {owner!r} does not own submit {reservation['submit_id']!r}",
            )

    def _cas_status(
        self,
        submit_id: str,
        *,
        expected: str,
        target: str,
        kind: str,
        detail: str,
    ) -> None:
        now = datetime.now(UTC)
        self._conn.execute("BEGIN")
        try:
            updated = self._conn.execute(
                """
                UPDATE order_ledger_reservations
                SET status = ?, updated_at = ?
                WHERE submit_id = ? AND status = ?
                """,
                [target, now, submit_id, expected],
            ).fetchone()
            if updated is None or updated[0] == 0:
                self._conn.execute("ROLLBACK")
                raise LedgerTransitionError(
                    "state_conflict",
                    f"submit {submit_id} is not in {expected} state",
                )
            self._append_event(submit_id, kind, detail)
            self._conn.execute("COMMIT")
        except LedgerTransitionError:
            raise
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def _append_event(self, submit_id: str, kind: str, detail: str) -> None:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(event_id), 0) + 1 FROM order_ledger_events"
        ).fetchone()
        event_id = int(row[0]) if row else 1
        self._conn.execute(
            """
            INSERT INTO order_ledger_events (event_id, submit_id, kind,
                                             detail, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [event_id, submit_id, kind, detail, datetime.now(UTC)],
        )


def _submit_id(cycle_id: str, intent_id: str) -> str:
    return f"{cycle_id}:{intent_id}"


def _default_db_path() -> Path:
    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    base = Path(env_dir) if env_dir else Path.home() / ".alphabrief" / "data"
    return base / "alphabrief.db"


__all__ = [
    "LedgerState",
    "LedgerTransitionError",
    "OrderLedger",
    "ReservationOutcome",
]
