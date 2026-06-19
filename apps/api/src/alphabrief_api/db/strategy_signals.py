"""DuckDB-backed strategy-signal history store for AlphaBrief.

``StrategySignalStore`` records individual :class:`alphabrief_core.Signal`
objects emitted by a strategy, making signal history a first-class
advisory artifact in the system.

The store is **purely advisory**:

- It never blocks orders.
- It never modifies ``RiskDecision`` semantics.
- It is not consulted by ``RiskGate`` or ``PaperBroker``.

Its purpose is to support post-hoc analysis: backtest replay, manual
recording, and dashboard inspection. The table is keyed on
``signal_id`` (idempotent upsert) and indexed by
``(strategy_id, signal_ts DESC)`` for fast per-strategy lookups.

This module is additive. It does not modify the strategy spec
store, the risk gate, or any execution path.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from alphabrief_api.db.schema import apply_schema, drop_schema

# ---------------------------------------------------------------------------
# Default data directory
# ---------------------------------------------------------------------------

_DEFAULT_DB_DIR = Path.home() / ".alphabrief" / "data"


def _db_dir() -> Path:
    import os

    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    return _DEFAULT_DB_DIR


def _db_path() -> Path:
    db_dir = _db_dir()
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "alphabrief.db"


def now() -> str:
    """ISO-8601 UTC timestamp string for DB writes."""
    from datetime import UTC

    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# StrategySignalStore
# ---------------------------------------------------------------------------

# Allowed source labels. ``other`` is the default for unknown callers.
_VALID_SOURCES: frozenset[str] = frozenset({"backtest", "manual", "other"})


class StrategySignalStore:
    """DuckDB-backed persistent store for strategy signal history.

    Usage::

        store = StrategySignalStore()
        store.save_signal(signal_dict, source="manual")
        store.list_signals(strategy_id="sma_trend_v1")
        store.list_signals(strategy_id="sma_trend_v1", symbol="BTC-USD")
        store.count_signals(strategy_id="sma_trend_v1")
        store.get_signal(signal_id="...")
        store.delete_signal(signal_id="...")
        store.clear()
        store.close()
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _db_path()
        self._db_path = Path(db_path)
        self._conn = duckdb.connect(str(self._db_path))
        apply_schema(self._conn)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save_signal(
        self,
        signal: dict[str, Any],
        *,
        source: str = "other",
    ) -> str:
        """Persist a strategy signal. Returns the ``signal_id``.

        The payload is validated against the signal schema fields
        (``signal_id``, ``strategy_id``, ``symbol``, ``timestamp``,
        ``direction``, ``confidence``, ``horizon``). The full payload
        is stored as JSON for forward compatibility.

        ``source`` records the call site. Must be one of ``"backtest"``,
        ``"manual"``, ``"other"``.
        """
        if source not in _VALID_SOURCES:
            raise ValueError(
                f"source must be one of {sorted(_VALID_SOURCES)}, got {source!r}"
            )

        signal_id = signal.get("signal_id")
        if not isinstance(signal_id, str) or signal_id.strip() == "":
            raise ValueError("signal.signal_id must be a non-empty string")

        strategy_id = signal.get("strategy_id")
        if not isinstance(strategy_id, str) or strategy_id.strip() == "":
            raise ValueError("signal.strategy_id must be a non-empty string")

        symbol = signal.get("symbol")
        if not isinstance(symbol, str) or symbol.strip() == "":
            raise ValueError("signal.symbol must be a non-empty string")

        timestamp = signal.get("timestamp")
        if not isinstance(timestamp, str) or timestamp.strip() == "":
            raise ValueError("signal.timestamp must be an ISO-8601 string")

        direction = signal.get("direction")
        if not isinstance(direction, str) or direction.strip() == "":
            raise ValueError("signal.direction must be a non-empty string")

        confidence = signal.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise ValueError("signal.confidence must be a number in [0, 1]")
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError("signal.confidence must be in [0, 1]")

        horizon = signal.get("horizon")
        if not isinstance(horizon, str) or horizon.strip() == "":
            raise ValueError("signal.horizon must be a non-empty string")

        self._conn.execute(
            """
            INSERT INTO strategy_signals (
                signal_id, strategy_id, symbol, signal_ts,
                direction, confidence, horizon, source, signal_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?::JSON)
            ON CONFLICT (signal_id) DO UPDATE SET
                strategy_id = EXCLUDED.strategy_id,
                symbol = EXCLUDED.symbol,
                signal_ts = EXCLUDED.signal_ts,
                direction = EXCLUDED.direction,
                confidence = EXCLUDED.confidence,
                horizon = EXCLUDED.horizon,
                source = EXCLUDED.source,
                signal_json = EXCLUDED.signal_json,
                created_at = EXCLUDED.created_at
            """,
            [
                signal_id,
                strategy_id,
                symbol,
                timestamp,
                direction,
                float(confidence),
                horizon,
                source,
                json.dumps(signal),
            ],
        )
        return signal_id

    def delete_signal(self, signal_id: str) -> bool:
        """Remove a single signal. Returns ``True`` if a row was deleted."""
        existing = self.get_signal(signal_id)
        if existing is None:
            return False
        self._conn.execute(
            "DELETE FROM strategy_signals WHERE signal_id = ?",
            [signal_id],
        )
        return True

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_signal(self, signal_id: str) -> dict[str, Any] | None:
        """Return the full record for *signal_id*, or ``None``."""
        row = self._conn.execute(
            """SELECT signal_id, strategy_id, symbol, signal_ts,
                      direction, confidence, horizon, source,
                      signal_json, created_at
               FROM strategy_signals WHERE signal_id = ?""",
            [signal_id],
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row, include_payload=True)

    def list_signals(
        self,
        *,
        strategy_id: str | None = None,
        symbol: str | None = None,
        source: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return signal summary rows ordered by ``signal_ts DESC``.

        Filters are AND-combined. ``limit`` is applied as a hard
        upper bound on the number of rows returned. Summaries
        exclude the JSON ``signal_json`` payload; use
        :meth:`get_signal` to fetch the full record.
        """
        sql = """SELECT signal_id, strategy_id, symbol, signal_ts,
                        direction, confidence, horizon, source,
                        signal_json, created_at
                 FROM strategy_signals"""
        clauses: list[str] = []
        params: list[Any] = []
        if strategy_id is not None:
            clauses.append("strategy_id = ?")
            params.append(strategy_id)
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol)
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY signal_ts DESC, signal_id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))

        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r, include_payload=False) for r in rows]

    def count_signals(
        self,
        *,
        strategy_id: str | None = None,
        symbol: str | None = None,
        source: str | None = None,
    ) -> int:
        """Return the number of stored signals matching the filters."""
        sql = "SELECT COUNT(*) FROM strategy_signals"
        clauses: list[str] = []
        params: list[Any] = []
        if strategy_id is not None:
            clauses.append("strategy_id = ?")
            params.append(strategy_id)
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol)
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        row = self._conn.execute(sql, params).fetchone()
        return int(row[0]) if row is not None else 0

    def list_strategy_ids(self) -> list[str]:
        """Return the distinct set of strategy_ids with at least one signal."""
        rows = self._conn.execute(
            "SELECT DISTINCT strategy_id FROM strategy_signals "
            "ORDER BY strategy_id ASC"
        ).fetchall()
        return [str(r[0]) for r in rows]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(
        row: tuple[Any, ...],
        *,
        include_payload: bool,
    ) -> dict[str, Any]:
        signal_raw = row[8]
        signal_obj: dict[str, Any] = (
            signal_raw
            if isinstance(signal_raw, dict)
            else json.loads(str(signal_raw))
        )
        result: dict[str, Any] = {
            "signal_id": row[0],
            "strategy_id": row[1],
            "symbol": row[2],
            "timestamp": str(row[3]),
            "direction": row[4],
            "confidence": float(row[5]),
            "horizon": row[6],
            "source": row[7],
            "created_at": str(row[9]),
        }
        if include_payload:
            result["signal"] = signal_obj
        return result

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Drop and recreate all tables (for test isolation)."""
        drop_schema(self._conn)
        apply_schema(self._conn)

    def close(self) -> None:
        """Close the DuckDB connection."""
        try:
            self._conn.close()
        except Exception:
            pass  # already closed


__all__ = ["StrategySignalStore"]
