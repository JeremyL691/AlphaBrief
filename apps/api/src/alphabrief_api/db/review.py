"""DuckDB-backed review store for AlphaBrief.

``ReviewStore`` provides persistent storage for review snapshots,
replacing the in-memory default snapshot that was used before Phase 7
Round 4.
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
# ReviewStore
# ---------------------------------------------------------------------------


class ReviewStore:
    """DuckDB-backed persistent store for review snapshots.

    Usage::

        store = ReviewStore()
        sid = store.save_snapshot(snapshot_data)
        store.get_snapshot(sid)         # -> dict | None
        store.get_latest_snapshot()     # -> dict | None
        store.list_snapshots()          # -> list[dict]
        store.clear()                   # drop + recreate tables
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

    def save_snapshot(
        self,
        snapshot_data: dict[str, Any],
        snapshot_id: str | None = None,
    ) -> str:
        """Persist a review snapshot and return the snapshot ID."""
        if snapshot_id is None:
            snapshot_id = f"snapshot_{uuid4().hex[:12]}"
        snapshot_data = {**snapshot_data, "snapshot_id": snapshot_id}
        self._conn.execute(
            """
            INSERT INTO review_snapshots (id, snapshot_json)
            VALUES (?, ?::JSON)
            """,
            [snapshot_id, json.dumps(snapshot_data)],
        )
        return snapshot_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        """Return the full snapshot for *snapshot_id*, or ``None``."""
        row = self._conn.execute(
            """SELECT id, created_at, snapshot_json
               FROM review_snapshots WHERE id = ?""",
            [snapshot_id],
        ).fetchone()
        if row is None:
            return None

        snapshot: dict[str, Any] = (
            row[2] if isinstance(row[2], dict) else json.loads(str(row[2]))
        )
        return {
            "id": row[0],
            "created_at": str(row[1]),
            "snapshot": snapshot,
        }

    def get_latest_snapshot(self) -> dict[str, Any] | None:
        """Return the most recent snapshot, or ``None``."""
        row = self._conn.execute(
            """SELECT id, created_at, snapshot_json
               FROM review_snapshots
               ORDER BY created_at DESC
               LIMIT 1"""
        ).fetchone()
        if row is None:
            return None

        snapshot: dict[str, Any] = (
            row[2] if isinstance(row[2], dict) else json.loads(str(row[2]))
        )
        return {
            "id": row[0],
            "created_at": str(row[1]),
            "snapshot": snapshot,
        }

    def list_snapshots(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return snapshots ordered by creation time (newest first)."""
        rows = self._conn.execute(
            """SELECT id, created_at, snapshot_json
               FROM review_snapshots
               ORDER BY created_at DESC
               LIMIT ?""",
            [limit],
        ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            snapshot: dict[str, Any] = (
                row[2] if isinstance(row[2], dict) else json.loads(str(row[2]))
            )
            results.append(
                {
                    "id": row[0],
                    "created_at": str(row[1]),
                    "headline": snapshot.get("headline", ""),
                    "snapshot_id": snapshot.get("snapshot_id", ""),
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


__all__ = ["ReviewStore"]
