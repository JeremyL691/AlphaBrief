"""DuckDB-backed store for AI Trading Committee cycles and attempts.

Tables (owned by ``alphabrief_api.db.schema``):

* ``ai_daily_cycles`` — one row per daily cycle, JSON payload of the
  full ``DailyCycleRecord``.
* ``ai_committee_votes`` — one row per vote emitted by the committee,
  linked back to its cycle. Allows fast voting history queries without
  loading the full cycle JSON.
* ``ai_order_attempts`` — one row per intent submitted through the
  risk gate / paper broker pipeline. Records the outcome
  (``executed``, ``blocked_*``, ``error``) and the stringified
  ``RiskDecision`` for replay.

The store reads / writes only. It never calls providers, never places
orders, and never bypasses the deterministic ``RiskGate``. Decimal
fields are persisted as ``TEXT`` to preserve precision (mirrors the
existing ``portfolio_snapshot`` and ``account_equity_snapshots``
tables).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import duckdb

from alphabrief_trader.db_schema import (
    apply_ai_trading_schema,
    drop_ai_trading_schema,
)
from alphabrief_trader.schemas import (
    DailyCycleRecord,
    DailyCycleSummary,
)

_DEFAULT_DB_DIR = Path.home() / ".alphabrief" / "data"


def _db_dir() -> Path:
    ai_dir = os.environ.get("ALPHABRIEF_AI_DB_DIR")
    if ai_dir:
        return Path(ai_dir)
    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    return _DEFAULT_DB_DIR


def _db_path() -> Path:
    db_dir = _db_dir()
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "alphabrief.db"


def _serialize(value: Any) -> str:
    """JSON-safe stringify that preserves Decimal and datetime."""
    return json.dumps(value, default=str, sort_keys=True)


# ---------------------------------------------------------------------------
# AiTradingStore
# ---------------------------------------------------------------------------


class AiTradingStore:
    """DuckDB-backed persistent store for AI trading cycles.

    Usage::

        store = AiTradingStore()
        cycle_id = store.save_cycle(record)
        rows = store.list_cycles(limit=20)
        store.get_cycle(cycle_id)
        store.clear()
        store.close()
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _db_path()
        self._db_path = Path(db_path)
        self._conn = duckdb.connect(str(self._db_path))
        apply_ai_trading_schema(self._conn)

    # ------------------------------------------------------------------
    # Cycle persistence
    # ------------------------------------------------------------------

    def save_cycle(self, record: DailyCycleRecord) -> str:
        """Persist a full cycle + its votes and attempts, atomically.

        Returns the ``cycle_id``. The cycle row stores the full
        ``DailyCycleRecord`` JSON; child tables denormalize votes and
        attempts for fast queries. The cycle, its votes, and its attempts
        commit in one transaction: a failure rolls everything back, so a
        partially recorded cycle can never exist (M03-W03, REQ-PLAT-005).
        """
        cycle_id = record.cycle_id
        self._conn.execute("BEGIN")
        try:
            self._insert_cycle_facts(record)
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return cycle_id

    def _insert_cycle_facts(self, record: DailyCycleRecord) -> None:
        """Insert the cycle row, votes, and attempts (within one transaction)."""
        cycle_id = record.cycle_id
        self._conn.execute(
            """
            INSERT INTO ai_daily_cycles (
                cycle_id, trading_day, symbols_json, outcome, enabled,
                live_trading_enabled, summary, cycle_json, created_at
            ) VALUES (?, ?, ?::JSON, ?, ?, ?, ?, ?::JSON, ?)
            """,
            [
                cycle_id,
                record.trading_day,
                _serialize(record.symbols),
                record.outcome,
                record.enabled,
                record.live_trading_enabled,
                record.summary,
                _serialize(record.model_dump(mode="json")),
                record.created_at,
            ],
        )

        for vote_index, vote in enumerate(record.votes):
            self._conn.execute(
                """
                INSERT INTO ai_committee_votes (
                    cycle_id, vote_index, role, model_name, view, confidence,
                    suggested_action, target_position_pct, veto,
                    needs_human_review, vote_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON, ?)
                """,
                [
                    cycle_id,
                    vote_index,
                    vote.role,
                    vote.model_name,
                    vote.view,
                    vote.confidence,
                    vote.suggested_action,
                    format(vote.target_position_pct, "f"),
                    vote.veto,
                    vote.needs_human_review,
                    _serialize(vote.model_dump(mode="json")),
                    vote.created_at,
                ],
            )

        for attempt in record.attempts:
            self._conn.execute(
                """
                INSERT INTO ai_order_attempts (
                    cycle_id, intent_id, outcome, approved,
                    requires_human_review, filled, order_id,
                    attempt_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?::JSON, ?)
                """,
                [
                    cycle_id,
                    attempt.intent_id,
                    attempt.outcome,
                    attempt.approved,
                    attempt.requires_human_review,
                    attempt.filled,
                    attempt.order_id,
                    _serialize(attempt.model_dump(mode="json")),
                    attempt.created_at,
                ],
            )

    def get_cycle(self, cycle_id: str) -> dict[str, Any] | None:
        """Return the full cycle record JSON, or ``None``."""
        row = self._conn.execute(
            "SELECT cycle_json, created_at FROM ai_daily_cycles "
            "WHERE cycle_id = ?",
            [cycle_id],
        ).fetchone()
        if row is None:
            return None
        cycle_json: object = row[0]
        if isinstance(cycle_json, str):
            data: Any = json.loads(cycle_json)
        else:
            data = cycle_json
        return cast(dict[str, Any], data)

    def get_cycle_by_key(self, cycle_key: str) -> dict[str, Any] | None:
        """Return the newest terminal cycle for a deterministic cycle key.

        Used by the daily cycle's idempotency guard (REQ-AI-009): the
        same (cycle key, snapshot fingerprint) must never produce a
        second committee run, proposal, or OrderIntent.
        """
        row = self._conn.execute(
            "SELECT cycle_json FROM ai_daily_cycles "
            "WHERE cycle_json ->> 'cycle_key' = ? "
            "ORDER BY created_at DESC LIMIT 1",
            [cycle_key],
        ).fetchone()
        if row is None:
            return None
        cycle_json: object = row[0]
        if isinstance(cycle_json, str):
            data: Any = json.loads(cycle_json)
        else:
            data = cycle_json
        return cast(dict[str, Any], data)

    def get_latest_cycle(self) -> dict[str, Any] | None:
        """Return the most-recently-created cycle, or ``None``."""
        row = self._conn.execute(
            "SELECT cycle_json FROM ai_daily_cycles "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        cycle_json: object = row[0]
        if isinstance(cycle_json, str):
            data: Any = json.loads(cycle_json)
        else:
            data = cycle_json
        return cast(dict[str, Any], data)

    def list_cycles(self, *, limit: int = 20) -> list[DailyCycleSummary]:
        """Return one :class:`DailyCycleSummary` per cycle, newest-first."""
        rows = self._conn.execute(
            """
            SELECT cycle_id, trading_day, cycle_json, created_at
            FROM ai_daily_cycles
            ORDER BY created_at DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()

        results: list[DailyCycleSummary] = []
        for row in rows:
            cycle_json = row[2]
            data = (
                json.loads(cycle_json) if isinstance(cycle_json, str) else cycle_json
            )
            symbols = data.get("symbols", [])
            attempts = data.get("attempts", []) or []
            plans = data.get("plans", []) or []
            executed = sum(
                1 for a in attempts if a.get("outcome") == "executed"
            )
            blocked = sum(
                1
                for a in attempts
                if isinstance(a.get("outcome"), str)
                and a.get("outcome", "").startswith("blocked")
            )
            results.append(
                DailyCycleSummary(
                    cycle_id=str(row[0]),
                    trading_day=str(row[1]),
                    symbols=list(symbols),
                    plan_count=len(plans),
                    attempt_count=len(attempts),
                    executed_count=executed,
                    blocked_count=blocked,
                    outcome=data.get("outcome", "error"),
                    enabled=bool(data.get("enabled", False)),
                    live_trading_enabled=bool(
                        data.get("live_trading_enabled", False)
                    ),
                    created_at=str(row[3]),
                )
            )
        return results

    def list_cycles_for_day(self, day: str) -> list[DailyCycleSummary]:
        """Return cycles whose ``trading_day`` matches ``YYYY-MM-DD``."""
        rows = self._conn.execute(
            """
            SELECT cycle_id, trading_day, cycle_json, created_at
            FROM ai_daily_cycles
            WHERE trading_day = ?
            ORDER BY created_at DESC
            """,
            [day],
        ).fetchall()
        results: list[DailyCycleSummary] = []
        for row in rows:
            cycle_json = row[2]
            data = (
                json.loads(cycle_json) if isinstance(cycle_json, str) else cycle_json
            )
            symbols = data.get("symbols", [])
            attempts = data.get("attempts", []) or []
            plans = data.get("plans", []) or []
            executed = sum(
                1 for a in attempts if a.get("outcome") == "executed"
            )
            blocked = sum(
                1
                for a in attempts
                if isinstance(a.get("outcome"), str)
                and a.get("outcome", "").startswith("blocked")
            )
            results.append(
                DailyCycleSummary(
                    cycle_id=str(row[0]),
                    trading_day=str(row[1]),
                    symbols=list(symbols),
                    plan_count=len(plans),
                    attempt_count=len(attempts),
                    executed_count=executed,
                    blocked_count=blocked,
                    outcome=data.get("outcome", "error"),
                    enabled=bool(data.get("enabled", False)),
                    live_trading_enabled=bool(
                        data.get("live_trading_enabled", False)
                    ),
                    created_at=str(row[3]),
                )
            )
        return results

    def list_attempts(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return attempt rows newest-first as plain dicts (string Decimals)."""
        rows = self._conn.execute(
            """
            SELECT intent_id, cycle_id, outcome, approved,
                   requires_human_review, filled, order_id,
                   attempt_json, created_at
            FROM ai_order_attempts
            ORDER BY created_at DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            attempt_json = row[7]
            data = (
                json.loads(attempt_json)
                if isinstance(attempt_json, str)
                else attempt_json
            )
            out.append(
                {
                    "intent_id": str(row[0]),
                    "cycle_id": str(row[1]),
                    "outcome": str(row[2]),
                    "approved": bool(row[3]),
                    "requires_human_review": bool(row[4]),
                    "filled": bool(row[5]),
                    "order_id": str(row[6]) if row[6] is not None else None,
                    "created_at": str(row[8]),
                    "attempt": data,
                }
            )
        return out

    # ------------------------------------------------------------------
    # Discipline config snapshot (read-only advisory)
    # ------------------------------------------------------------------

    def get_discipline_snapshot(self) -> dict[str, Any] | None:
        """Return the latest persisted discipline config, or ``None``."""
        row = self._conn.execute(
            "SELECT config_json, updated_at FROM ai_discipline_config "
            "ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        config_json = row[0]
        data = (
            json.loads(config_json) if isinstance(config_json, str) else config_json
        )
        return {"config": data, "updated_at": str(row[1])}

    def save_discipline_snapshot(
        self, config: dict[str, Any]
    ) -> str:
        """Persist an immutable snapshot of the discipline config."""
        snapshot_id = f"disc_{int(datetime.now().timestamp() * 1000)}"
        self._conn.execute(
            """
            INSERT INTO ai_discipline_config (
                snapshot_id, config_json, updated_at
            ) VALUES (?, ?::JSON, ?)
            """,
            [
                snapshot_id,
                _serialize(config),
                datetime.now().isoformat(),
            ],
        )
        return snapshot_id

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Drop and recreate AI-trading tables (for test isolation)."""
        drop_ai_trading_schema(self._conn)
        apply_ai_trading_schema(self._conn)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


#: Legal cycle phase order — checkpoints only advance monotonically and
#: resume from the last persisted gate (REQ-CYCLE-002).
CYCLE_PHASE_ORDER: tuple[str, ...] = (
    "ingest",
    "snapshot",
    "committee",
    "risk",
    "execute",
    "record",
)

#: Legal daily-cycle phase order for the M11-W01 durable state machine.
#: ``execute`` records its outcome (``executed`` | ``no_trade`` |
#: ``blocked``) so the "execute or no-trade" gate is one phase.
CYCLE_STATE_PHASE_ORDER: tuple[str, ...] = (
    "preflight",
    "ingest",
    "snapshot",
    "discuss",
    "propose",
    "risk",
    "execute",
    "reconcile",
    "report",
    "complete",
)


class CycleCheckpointStore:
    """Compare-and-set cycle checkpoints over append-only facts (M03-W03).

    Each checkpoint row records the phase a cycle reached plus the
    output fact IDs produced up to that gate. Advances are compare-and-
    set: a writer whose expected phase does not match the stored phase
    (a stale writer) is rejected, and phase changes must be strictly
    monotonic. Projections rebuild from the fact tables and compare
    byte-for-byte with the stored record after JSON normalization.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _db_path()
        self._db_path = Path(db_path)
        self._conn = duckdb.connect(str(self._db_path))
        apply_ai_trading_schema(self._conn)

    def checkpoint(
        self,
        cycle_id: str,
        phase: str,
        *,
        output_ids: dict[str, Any] | None = None,
        expected_phase: str | None = None,
    ) -> bool:
        """Advance the cycle checkpoint atomically; False on stale or illegal.

        Raises ``ValueError`` for phases outside :data:`CYCLE_PHASE_ORDER`.
        A stale writer (``expected_phase`` does not match the stored
        phase) and every non-monotonic transition are rejected without
        mutating the checkpoint.
        """
        if phase not in CYCLE_PHASE_ORDER:
            raise ValueError(
                f"unknown cycle phase {phase!r}; expected one of "
                f"{CYCLE_PHASE_ORDER}"
            )
        target_order = CYCLE_PHASE_ORDER.index(phase)

        current = self.get_checkpoint(cycle_id)
        current_phase = current["phase"] if current else None
        current_order = (
            CYCLE_PHASE_ORDER.index(current_phase)
            if current_phase in CYCLE_PHASE_ORDER
            else -1
        )
        if expected_phase is not None and current_phase != expected_phase:
            return False
        if current is not None and target_order <= current_order:
            return False

        payload = json.dumps(output_ids or {}, sort_keys=True)
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """
            INSERT INTO cycle_checkpoints (
                cycle_id, phase, phase_order, output_ids_json, updated_at
            )
            VALUES (?, ?, ?, ?::JSON, ?)
            ON CONFLICT (cycle_id) DO UPDATE SET
                phase = EXCLUDED.phase,
                phase_order = EXCLUDED.phase_order,
                output_ids_json = EXCLUDED.output_ids_json,
                updated_at = EXCLUDED.updated_at
            """,
            [cycle_id, phase, target_order, payload, now],
        )
        return True

    def get_checkpoint(self, cycle_id: str) -> dict[str, Any] | None:
        """Return the stored checkpoint for *cycle_id*, or ``None``."""
        row = self._conn.execute(
            """SELECT cycle_id, phase, phase_order, output_ids_json, updated_at
               FROM cycle_checkpoints WHERE cycle_id = ?""",
            [cycle_id],
        ).fetchone()
        if row is None:
            return None
        output: object = row[3]
        if isinstance(output, str):
            output_ids = json.loads(output)
        else:
            output_ids = output
        return {
            "cycle_id": str(row[0]),
            "phase": str(row[1]),
            "phase_order": int(row[2]),
            "output_ids": output_ids,
            "updated_at": str(row[4]),
        }

    def rebuild_projection(self, cycle_id: str) -> dict[str, Any] | None:
        """Reconstruct the cycle record from its append-only fact rows.

        The base facts come from ``ai_daily_cycles``; votes and attempts
        are rebuilt from their own immutable fact tables so the current
        projection is always derivable from the facts.
        """
        base = AiTradingStore(db_path=self._db_path).get_cycle(cycle_id)
        if base is None:
            return None
        votes = [
            json.loads(row[0]) if isinstance(row[0], str) else row[0]
            for row in self._conn.execute(
                """SELECT vote_json FROM ai_committee_votes
                   WHERE cycle_id = ? ORDER BY vote_index""",
                [cycle_id],
            ).fetchall()
        ]
        attempts = [
            json.loads(row[0]) if isinstance(row[0], str) else row[0]
            for row in self._conn.execute(
                """SELECT attempt_json FROM ai_order_attempts
                   WHERE cycle_id = ? ORDER BY intent_id""",
                [cycle_id],
            ).fetchall()
        ]
        return {**base, "votes": votes, "attempts": attempts}

    def projection_matches_stored(self, cycle_id: str) -> bool:
        """Return True when the rebuilt projection equals the stored record.

        Both sides are normalized with ``sort_keys`` and ``default=str``
        so the comparison is byte-for-byte after normalization
        (AC-M03-W03-02).
        """
        stored = AiTradingStore(db_path=self._db_path).get_cycle(cycle_id)
        rebuilt = self.rebuild_projection(cycle_id)
        if stored is None or rebuilt is None:
            return False
        return _normalize(stored) == _normalize(rebuilt)

    def clear(self) -> None:
        """Drop and recreate AI-trading tables (for test isolation)."""
        drop_ai_trading_schema(self._conn)
        apply_ai_trading_schema(self._conn)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


class CycleStateStore:
    """Persisted compare-and-set daily-cycle state machine (M11-W01).

    The current state lives in ``cycle_state`` (one row per cycle) and
    every legal advance appends one immutable row to
    ``cycle_state_transitions`` in the same transaction. Advances are
    compare-and-set: a writer whose ``expected_phase`` does not match
    the stored phase is a stale writer and is rejected without mutating
    anything. ``resume_phase`` returns the next phase after the last
    committed gate so a restart never repeats a completed side effect.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _db_path()
        self._db_path = Path(db_path)
        self._conn = duckdb.connect(str(self._db_path))
        apply_ai_trading_schema(self._conn)

    def begin(
        self,
        cycle_id: str,
        phase: str,
        *,
        outcome: str | None = None,
        transition_id: str | None = None,
    ) -> bool:
        """Initialize a cycle at *phase*; False when it already exists.

        The initial phase is itself recorded as the first immutable
        transition (prior phase ``None``), so every phase of the cycle —
        including the first — has a durable audit row.
        """
        order = CYCLE_STATE_PHASE_ORDER.index(phase)
        row = self._conn.execute(
            "SELECT cycle_id FROM cycle_state WHERE cycle_id = ?",
            [cycle_id],
        ).fetchone()
        if row is not None:
            return False
        transition_id = transition_id or f"t_{uuid4().hex[:12]}"
        self._conn.execute("BEGIN")
        try:
            self._conn.execute(
                """
                INSERT INTO cycle_state_transitions (
                    transition_id, cycle_id, phase, phase_order,
                    prior_phase, attempt_count, input_hashes_json,
                    output_ids_json, outcome
                )
                VALUES (?, ?, ?, ?, NULL, 1, '{}'::JSON, '{}'::JSON, ?)
                """,
                [transition_id, cycle_id, phase, order, outcome],
            )
            self._conn.execute(
                """
                INSERT INTO cycle_state (cycle_id, phase, phase_order, outcome)
                VALUES (?, ?, ?, ?)
                """,
                [cycle_id, phase, order, outcome],
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return True

    def advance(
        self,
        cycle_id: str,
        *,
        expected_phase: str,
        next_phase: str,
        input_hashes: dict[str, str] | None = None,
        output_ids: dict[str, str] | None = None,
        attempt_count: int = 1,
        outcome: str | None = None,
        transition_id: str | None = None,
    ) -> bool:
        """Atomically append one transition and advance the state.

        Returns False (without mutating anything) when ``expected_phase``
        does not match the stored phase — a stale writer — or when the
        target phase is not strictly after the stored phase.
        """
        if next_phase not in CYCLE_STATE_PHASE_ORDER:
            raise ValueError(
                f"unknown cycle phase {next_phase!r}; expected one of "
                f"{CYCLE_STATE_PHASE_ORDER}"
            )
        target_order = CYCLE_STATE_PHASE_ORDER.index(next_phase)
        current = self.get_state(cycle_id)
        if current is None or current["phase"] != expected_phase:
            return False
        current_order = CYCLE_STATE_PHASE_ORDER.index(current["phase"])
        if target_order <= current_order:
            return False

        hashes_json = json.dumps(input_hashes or {}, sort_keys=True)
        outputs_json = json.dumps(output_ids or {}, sort_keys=True)
        transition_id = transition_id or f"t_{uuid4().hex[:12]}"
        self._conn.execute("BEGIN")
        try:
            self._conn.execute(
                """
                INSERT INTO cycle_state_transitions (
                    transition_id, cycle_id, phase, phase_order,
                    prior_phase, attempt_count, input_hashes_json,
                    output_ids_json, outcome
                )
                VALUES (?, ?, ?, ?, ?, ?, ?::JSON, ?::JSON, ?)
                """,
                [
                    transition_id,
                    cycle_id,
                    next_phase,
                    target_order,
                    expected_phase,
                    attempt_count,
                    hashes_json,
                    outputs_json,
                    outcome,
                ],
            )
            self._conn.execute(
                """
                UPDATE cycle_state
                SET phase = ?, phase_order = ?,
                    outcome = COALESCE(?, outcome)
                WHERE cycle_id = ? AND phase = ?
                """,
                [next_phase, target_order, outcome, cycle_id, expected_phase],
            )
            # DuckDB does not report UPDATE rowcounts, so the compare-and-
            # set effect is verified by re-reading the state: unless the
            # phase actually advanced, the writer was stale and the whole
            # transaction rolls back.
            verify = self._conn.execute(
                "SELECT phase FROM cycle_state WHERE cycle_id = ?",
                [cycle_id],
            ).fetchone()
            if verify is None or verify[0] != next_phase:
                self._conn.execute("ROLLBACK")
                return False
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return True

    def get_state(self, cycle_id: str) -> dict[str, Any] | None:
        """Return the current persisted state for *cycle_id*."""
        row = self._conn.execute(
            "SELECT cycle_id, phase, phase_order, outcome, updated_at "
            "FROM cycle_state WHERE cycle_id = ?",
            [cycle_id],
        ).fetchone()
        if row is None:
            return None
        return {
            "cycle_id": str(row[0]),
            "phase": str(row[1]),
            "phase_order": int(row[2]),
            "outcome": row[3],
            "updated_at": str(row[4]),
        }

    def get_transitions(self, cycle_id: str) -> list[dict[str, Any]]:
        """Return every committed transition for *cycle_id*, in order."""
        rows = self._conn.execute(
            """
            SELECT transition_id, cycle_id, phase, phase_order, prior_phase,
                   attempt_count, input_hashes_json, output_ids_json,
                   outcome, created_at
            FROM cycle_state_transitions
            WHERE cycle_id = ?
            ORDER BY phase_order, created_at
            """,
            [cycle_id],
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            hashes: object = row[6]
            outputs: object = row[7]
            result.append(
                {
                    "transition_id": str(row[0]),
                    "cycle_id": str(row[1]),
                    "phase": str(row[2]),
                    "phase_order": int(row[3]),
                    "prior_phase": row[4],
                    "attempt_count": int(row[5]),
                    "input_hashes": (
                        json.loads(hashes) if isinstance(hashes, str) else hashes
                    ),
                    "output_ids": (
                        json.loads(outputs) if isinstance(outputs, str) else outputs
                    ),
                    "outcome": row[8],
                    "created_at": str(row[9]),
                }
            )
        return result

    def resume_phase(self, cycle_id: str) -> str | None:
        """Return the phase whose side effect has not committed yet.

        Each transition commits only after its phase's side effect, so
        the stored phase is the next phase to run. ``None`` means the
        cycle is complete; a missing state means start at the first
        phase.
        """
        state = self.get_state(cycle_id)
        if state is None:
            return CYCLE_STATE_PHASE_ORDER[0]
        if state["phase"] == "complete":
            return None
        return str(state["phase"])

    def clear(self) -> None:
        """Drop and recreate the AI-trading tables (test isolation)."""
        drop_ai_trading_schema(self._conn)
        apply_ai_trading_schema(self._conn)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


def _normalize(value: Any) -> str:
    """Canonical JSON serialization for byte-for-byte comparison."""
    return json.dumps(value, sort_keys=True, default=str)


def _today_iso() -> str:
    return date.today().isoformat()


__all__ = ["AiTradingStore"]
