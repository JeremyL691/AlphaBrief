"""DuckDB-backed backtest report store for AlphaBrief.

``BacktestReportStore`` provides persistent storage for backtest reports,
replacing the in-memory dictionary that was used before Phase 7 Round 2.
"""

from __future__ import annotations

import json
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
# BacktestReportStore
# ---------------------------------------------------------------------------


class BacktestReportStore:
    """DuckDB-backed persistent store for backtest reports.

    Usage::

        store = BacktestReportStore()
        rid = store.save_report(report_json, symbol="BTC", strategy_name="MA Trend")
        store.get_report(rid)       # -> dict | None
        store.list_reports()        # -> list[dict]
        store.clear()               # drop + recreate tables
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

    def save_report(
        self,
        report_json: dict[str, Any],
        *,
        symbol: str,
        strategy_name: str,
        report_engine: str = "legacy",
        engine_payload: dict[str, Any] | None = None,
    ) -> str:
        """Persist a backtest report and return its generated ID."""
        report_id = f"backtest_{uuid4().hex[:12]}"
        stored_report = dict(report_json)
        if engine_payload is not None:
            stored_report["engine_payload"] = engine_payload
        self._conn.execute(
            """
            INSERT INTO backtest_reports (
                id, symbol, strategy_name, report_engine, report_json
            )
            VALUES (?, ?, ?, ?, ?::JSON)
            """,
            [
                report_id,
                symbol,
                strategy_name,
                report_engine,
                json.dumps(stored_report),
            ],
        )
        return report_id

    def save_env_v2_report(
        self,
        report_dict: dict[str, Any],
        *,
        symbol: str,
        strategy_name: str,
    ) -> str:
        return self.save_report(
            report_dict,
            symbol=symbol,
            strategy_name=strategy_name,
            report_engine="env_v2",
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        """Return the full backtest report for *report_id*, or ``None``."""
        row = self._conn.execute(
            """SELECT id, symbol, strategy_name,
                      created_at, report_engine, report_json
               FROM backtest_reports WHERE id = ?""",
            [report_id],
        ).fetchone()
        if row is None:
            return None

        report: dict[str, Any] = (
            row[5] if isinstance(row[5], dict) else json.loads(str(row[5]))
        )
        return {
            "id": row[0],
            "symbol": row[1],
            "strategy_name": row[2],
            "created_at": str(row[3]),
            "report_engine": row[4],
            "report": report,
        }

    def list_reports(self) -> list[dict[str, Any]]:
        """Return all backtest reports ordered by creation time (newest first)."""
        rows = self._conn.execute(
            """SELECT id, symbol, strategy_name,
                      created_at, report_engine, report_json
               FROM backtest_reports
               ORDER BY created_at DESC"""
        ).fetchall()

        return self._rows_to_report_dicts(rows)

    def list_reports_by_engine(self, engine: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT id, symbol, strategy_name,
                      created_at, report_engine, report_json
               FROM backtest_reports
               WHERE report_engine = ?
               ORDER BY created_at DESC""",
            [engine],
        ).fetchall()

        return self._rows_to_report_dicts(rows)

    def _rows_to_report_dicts(self, rows: list[Any]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for row in rows:
            report: dict[str, Any] = (
                row[5] if isinstance(row[5], dict) else json.loads(str(row[5]))
            )
            results.append(
                {
                    "id": row[0],
                    "symbol": row[1],
                    "strategy_name": row[2],
                    "created_at": str(row[3]),
                    "report_engine": row[4],
                    "report": report,
                }
            )
        return results

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


__all__ = ["BacktestReportStore"]
