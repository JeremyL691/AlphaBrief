"""DuckDB-backed debate store for AlphaBrief.

``DebateStore`` provides persistent storage for AI debate records including
questions, agent responses, and consensus outputs.
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
# DebateStore
# ---------------------------------------------------------------------------


class DebateStore:
    """DuckDB-backed persistent store for AI debate records.

    Usage::

        store = DebateStore()
        did = store.save_debate_record(
            question="What is the market outlook?",
            responses=[{"agent": "bull", "text": "..."}],
            consensus={"verdict": "bullish"},
        )
        store.get_debate_record(did)       # -> dict | None
        store.list_debate_records()        # -> list[dict]
        store.clear()                      # drop + recreate tables
        store.close()
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _db_path()
        self._db_path = Path(db_path)
        self._conn = duckdb.connect(str(self._db_path))
        apply_schema(self._conn)

    # ------------------------------------------------------------------
    # Debate records
    # ------------------------------------------------------------------

    def save_debate_record(
        self,
        question: dict[str, Any] | str,
        responses: list[dict[str, Any]] | str,
        consensus: dict[str, Any] | str,
    ) -> str:
        """Persist a debate record and return its ID.

        Parameters
        ----------
        question : dict | str
            The debate question / prompt payload (serialised to JSON).
        responses : list[dict] | str
            Agent responses (serialised to JSON).
        consensus : dict | str
            The consensus output (serialised to JSON).
        """
        record_id = f"deb_{uuid4().hex[:12]}"
        self._conn.execute(
            """
            INSERT INTO debate_records
            (id, question_json, responses_json, consensus_json)
            VALUES (?, ?::JSON, ?::JSON, ?::JSON)
            """,
            [
                record_id,
                json.dumps(question) if not isinstance(question, str) else question,
                json.dumps(responses) if not isinstance(responses, str) else responses,
                json.dumps(consensus) if not isinstance(consensus, str) else consensus,
            ],
        )
        return record_id

    def get_debate_record(self, record_id: str) -> dict[str, Any] | None:
        """Return a single debate record by ID, or ``None``."""
        row = self._conn.execute(
            """SELECT id, question_json, responses_json, consensus_json, created_at
               FROM debate_records
               WHERE id = ?""",
            [record_id],
        ).fetchone()
        if row is None:
            return None

        return {
            "id": row[0],
            "question": (
                row[1] if isinstance(row[1], dict) else json.loads(str(row[1]))
            ),
            "responses": (
                row[2] if isinstance(row[2], list) else json.loads(str(row[2]))
            ),
            "consensus": (
                row[3] if isinstance(row[3], dict) else json.loads(str(row[3]))
            ),
            "created_at": str(row[4]),
        }

    def list_debate_records(
        self,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return debate records ordered by creation time (newest first)."""
        rows = self._conn.execute(
            """SELECT id, question_json, responses_json, consensus_json, created_at
               FROM debate_records
               ORDER BY created_at DESC
               LIMIT ?""",
            [limit],
        ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            results.append(
                {
                    "id": row[0],
                    "question": (
                        row[1] if isinstance(row[1], dict) else json.loads(str(row[1]))
                    ),
                    "responses": (
                        row[2] if isinstance(row[2], list) else json.loads(str(row[2]))
                    ),
                    "consensus": (
                        row[3] if isinstance(row[3], dict) else json.loads(str(row[3]))
                    ),
                    "created_at": str(row[4]),
                }
            )
        return results

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


__all__ = ["DebateStore"]
