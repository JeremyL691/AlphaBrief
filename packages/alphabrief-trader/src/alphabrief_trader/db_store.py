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
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

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
        """Persist a full cycle + its votes and attempts.

        Returns the ``cycle_id``. The cycle row stores the full
        ``DailyCycleRecord`` JSON; child tables denormalize votes and
        attempts for fast queries.
        """
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

        return cycle_id

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


def _today_iso() -> str:
    return date.today().isoformat()


__all__ = ["AiTradingStore"]
