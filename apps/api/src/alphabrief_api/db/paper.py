"""DuckDB-backed paper store for AlphaBrief.

``PaperStore`` provides persistent storage for audit events, portfolio
snapshots, and broker orders, replacing the in-memory broker state that
was used before Phase 7 Round 4.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

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


# ---------------------------------------------------------------------------
# PaperStore
# ---------------------------------------------------------------------------


class PaperStore:
    """DuckDB-backed persistent store for paper trading state.

    Usage::

        store = PaperStore()
        eid = store.save_audit_event(
            event_type="order_created", symbol="BTC-USD", details={...}
        )
        store.get_audit_events()          # -> list[dict]
        sid = store.save_portfolio_snapshot(
            cash="100000", realized_pnl="0",
            total_value="100000", positions={},
        )
        store.get_latest_portfolio_snapshot()  # -> dict | None
        oid = store.save_order(order_data)
        store.get_orders()                # -> list[dict]
        store.clear()                     # drop + recreate tables
        store.close()
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _db_path()
        self._db_path = Path(db_path)
        self._conn = duckdb.connect(str(self._db_path))
        apply_schema(self._conn)

    # ------------------------------------------------------------------
    # Audit events
    # ------------------------------------------------------------------

    def save_audit_event(
        self,
        event_type: str,
        symbol: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> str:
        """Persist an audit event and return its ID."""
        event_id = f"audit_{uuid4().hex[:12]}"
        self._conn.execute(
            """
            INSERT INTO audit_events (id, event_type, symbol, details_json)
            VALUES (?, ?, ?, ?::JSON)
            """,
            [event_id, event_type, symbol, json.dumps(details or {})],
        )
        return event_id

    def get_audit_events(
        self,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return audit events ordered by creation time (newest first)."""
        if event_type is not None:
            rows = self._conn.execute(
                """SELECT id, event_type, symbol, details_json, created_at
                   FROM audit_events
                   WHERE event_type = ?
                   ORDER BY created_at DESC""",
                [event_type],
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT id, event_type, symbol, details_json, created_at
                   FROM audit_events
                   ORDER BY created_at DESC"""
            ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            details: dict[str, Any] = (
                row[3] if isinstance(row[3], dict) else json.loads(str(row[3]))
            )
            results.append(
                {
                    "id": row[0],
                    "event_type": row[1],
                    "symbol": row[2],
                    "details": details,
                    "created_at": str(row[4]),
                }
            )
        return results

    # ------------------------------------------------------------------
    # Portfolio snapshots
    # ------------------------------------------------------------------

    def save_portfolio_snapshot(
        self,
        cash: str,
        realized_pnl: str,
        total_value: str,
        positions: dict[str, Any],
    ) -> str:
        """Persist a portfolio snapshot and return its ID."""
        snapshot_id = f"psnap_{uuid4().hex[:12]}"
        self._conn.execute(
            """
            INSERT INTO portfolio_snapshot
            (id, cash, realized_pnl, total_value, positions_json)
            VALUES (?, ?, ?, ?, ?::JSON)
            """,
            [snapshot_id, cash, realized_pnl, total_value, json.dumps(positions)],
        )
        return snapshot_id

    def get_latest_portfolio_snapshot(self) -> dict[str, Any] | None:
        """Return the most recent portfolio snapshot, or ``None``."""
        row = self._conn.execute(
            """SELECT id, cash, realized_pnl, total_value, positions_json, created_at
               FROM portfolio_snapshot
               ORDER BY created_at DESC
               LIMIT 1"""
        ).fetchone()
        if row is None:
            return None

        positions: dict[str, Any] = (
            row[4] if isinstance(row[4], dict) else json.loads(str(row[4]))
        )
        return {
            "id": row[0],
            "cash": row[1],
            "realized_pnl": row[2],
            "total_value": row[3],
            "positions": positions,
            "created_at": str(row[5]),
        }

    def list_portfolio_snapshots(
        self,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return portfolio snapshots ordered by creation time (newest first)."""
        rows = self._conn.execute(
            """SELECT id, cash, realized_pnl, total_value, positions_json, created_at
               FROM portfolio_snapshot
               ORDER BY created_at DESC
               LIMIT ?""",
            [limit],
        ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            positions: dict[str, Any] = (
                row[4] if isinstance(row[4], dict) else json.loads(str(row[4]))
            )
            results.append(
                {
                    "id": row[0],
                    "cash": row[1],
                    "realized_pnl": row[2],
                    "total_value": row[3],
                    "positions": positions,
                    "created_at": str(row[5]),
                }
            )
        return results

    # ------------------------------------------------------------------
    # Broker orders
    # ------------------------------------------------------------------

    def save_order(self, order_data: dict[str, Any]) -> str:
        """Persist a broker order as an 'order_created' audit event."""
        symbol = order_data.get("symbol", "")
        return self.save_audit_event(
            event_type="order_created",
            symbol=symbol,
            details=order_data,
        )

    def get_orders(
        self,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return broker orders (audit events with event_type='order_created')."""
        if status is not None:
            return [
                e
                for e in self.get_audit_events(event_type="order_created")
                if e.get("details", {}).get("status") == status
            ]
        return self.get_audit_events(event_type="order_created")

    # ------------------------------------------------------------------
    # R21.3 account equity snapshots (daily-loss + drawdown)
    # ------------------------------------------------------------------
    #
    # Append-only equity snapshots the paper route writes after each
    # fill. The drawdown high-water mark is ``max(equity)`` across all
    # snapshots; day-start equity is the earliest snapshot of the
    # current calendar day (UTC). Both are read by the route before
    # RiskGate evaluation so the gate stays pure (no DB import).

    def save_equity_snapshot(
        self,
        account_id: str,
        captured_at: datetime,
        equity: Decimal,
        realized_pnl_day: Decimal = Decimal("0"),
    ) -> str:
        """Persist an account equity snapshot and return its ID."""
        snapshot_id = f"esnap_{uuid4().hex[:12]}"
        self._conn.execute(
            """
            INSERT INTO account_equity_snapshots
            (snapshot_id, account_id, captured_at, equity, realized_pnl_day)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                snapshot_id,
                account_id,
                captured_at,
                str(equity),
                str(realized_pnl_day),
            ],
        )
        return snapshot_id

    def get_high_water_mark(self, account_id: str) -> Decimal | None:
        """Return the persisted peak equity (``max(equity)``), or ``None``.

        Resilient across restarts: the peak is read from the
        append-only table, so a process restart cannot reset it. This
        keeps the drawdown floor tighten-only across restarts.
        """
        row = self._conn.execute(
            """
            SELECT MAX(CAST(equity AS DECIMAL(38, 18)))
            FROM account_equity_snapshots
            WHERE account_id = ?
            """,
            [account_id],
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return Decimal(str(row[0]))

    def get_day_start_equity(self, account_id: str, day: date) -> Decimal | None:
        """Return the earliest equity snapshot's equity on *day* (UTC), or ``None``.

        *day* is compared against the ``captured_at`` UTC calendar date.
        ``CAST(... AT TIME ZONE 'UTC' AS DATE)`` pins the cast to UTC;
        DuckDB's default timestamp-to-date cast uses the session time
        zone, which would mis-attribute snapshots across the day
        boundary.
        """
        row = self._conn.execute(
            """
            SELECT CAST(equity AS DECIMAL(38, 18))
            FROM account_equity_snapshots
            WHERE account_id = ?
              AND CAST(captured_at AT TIME ZONE 'UTC' AS DATE) = ?
            ORDER BY captured_at ASC
            LIMIT 1
            """,
            [account_id, day],
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return Decimal(str(row[0]))

    def get_latest_equity(self, account_id: str) -> Decimal | None:
        """Return the most recent snapshot's equity, or ``None``."""
        row = self._conn.execute(
            """
            SELECT CAST(equity AS DECIMAL(38, 18))
            FROM account_equity_snapshots
            WHERE account_id = ?
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            [account_id],
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return Decimal(str(row[0]))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Drop and recreate all tables (for test isolation)."""
        drop_schema(self._conn)
        # A fresh connection has a clean catalog: reusing a long-lived
        # connection across drop/recreate cycles can leave DuckDB
        # dependency entries that fail the next transactional commit.
        self._conn.close()
        self._conn = duckdb.connect(str(self._db_path))
        apply_schema(self._conn)

    def close(self) -> None:
        """Close the DuckDB connection."""
        try:
            self._conn.close()
        except Exception:
            pass  # already closed


__all__ = ["PaperStore"]
