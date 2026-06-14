"""DuckDB-backed brief store for AlphaBrief.

``BriefStore`` provides persistent storage for DailyAlphaBriefs,
replacing the in-memory dictionary that was used before Phase 7 Round 3.
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
# BriefStore
# ---------------------------------------------------------------------------


class BriefStore:
    """DuckDB-backed persistent store for DailyAlphaBriefs.

    Usage::

        store = BriefStore()
        bid = store.save_brief(brief_data)
        store.get_brief(bid)   # -> dict | None
        store.list_briefs()    # -> list[dict]
        store.clear()          # drop + recreate tables
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

    def save_brief(self, brief_data: dict[str, Any], brief_id: str | None = None) -> str:
        """Persist a DailyAlphaBrief and return the brief ID."""
        if brief_id is None:
            brief_id = f"brief_{uuid4().hex[:12]}"
        # Ensure the stored JSON has the matching ID
        brief_data = {**brief_data, "brief_id": brief_id}
        self._conn.execute(
            """
            INSERT INTO briefs (id, brief_json)
            VALUES (?, ?::JSON)
            """,
            [brief_id, json.dumps(brief_data)],
        )
        return brief_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_brief(self, brief_id: str) -> dict[str, Any] | None:
        """Return the full brief for *brief_id*, or ``None``."""
        row = self._conn.execute(
            """SELECT id, created_at, brief_json
               FROM briefs WHERE id = ?""",
            [brief_id],
        ).fetchone()
        if row is None:
            return None

        brief: dict[str, Any] = (
            row[2] if isinstance(row[2], dict) else json.loads(str(row[2]))
        )
        return {
            "id": row[0],
            "created_at": str(row[1]),
            "brief": brief,
        }

    def list_briefs(self) -> list[dict[str, Any]]:
        """Return brief summaries ordered by creation time (newest first)."""
        rows = self._conn.execute(
            """SELECT id, created_at, brief_json
               FROM briefs
               ORDER BY created_at DESC"""
        ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            brief: dict[str, Any] = (
                row[2] if isinstance(row[2], dict) else json.loads(str(row[2]))
            )
            results.append(
                {
                    "id": row[0],
                    "created_at": str(row[1]),
                    "headline": brief.get("headline", ""),
                    "trading_day": brief.get("trading_day", ""),
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


__all__ = ["BriefStore"]
