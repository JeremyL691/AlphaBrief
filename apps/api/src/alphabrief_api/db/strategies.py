"""DuckDB-backed strategy spec store for AlphaBrief.

``StrategySpecStore`` provides persistent storage for :class:`StrategySpec`
objects, making strategies first-class persistent artifacts in the
system. This round is intentionally minimal: it provides CRUD on the
JSON-serialized spec plus an ``enabled`` flag. It does **not** interpret
strategy signals, modify RiskGate semantics, or expose live-trading
state.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

from alphabrief_api.db.schema import apply_schema, drop_schema

# Sentinel for "caller did not pass enabled explicitly" so save_spec can
# preserve the existing flag on upsert.
_UNSET = object()

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
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# StrategySpecStore
# ---------------------------------------------------------------------------


class StrategySpecStore:
    """DuckDB-backed persistent store for StrategySpec objects.

    Usage::

        store = StrategySpecStore()
        store.save_spec({"strategy_id": "...", "spec": {...}, "enabled": False})
        store.get_spec("sma_trend_v1")    # -> dict | None
        store.list_specs()               # -> list[dict]
        store.list_specs(enabled_only=True)
        store.set_enabled("sma_trend_v1", True)
        store.delete_spec("sma_trend_v1")
        store.clear()                    # drop + recreate tables
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

    def save_spec(
        self,
        spec: dict[str, Any],
        *,
        enabled: Any = _UNSET,
    ) -> str:
        """Persist a strategy spec and return its strategy_id.

        If a spec with the same ``strategy_id`` already exists, it is
        replaced (upsert). When ``enabled`` is omitted the existing
        flag is preserved (defaulting to ``False`` for first saves).
        """
        strategy_id = spec.get("strategy_id")
        if not isinstance(strategy_id, str) or strategy_id.strip() == "":
            raise ValueError("strategy_id must be a non-empty string")

        name = spec.get("name")
        version = spec.get("version")
        if not isinstance(name, str) or name.strip() == "":
            raise ValueError("spec.name must be a non-empty string")
        if not isinstance(version, str) or version.strip() == "":
            raise ValueError("spec.version must be a non-empty string")

        if enabled is _UNSET:
            existing = self.get_spec(strategy_id)
            enabled = bool(existing.get("enabled", False)) if existing else False
        else:
            if not isinstance(enabled, bool):
                raise ValueError("enabled must be a bool")
        self._conn.execute(
            """
            INSERT INTO strategy_specs (strategy_id, name, version, enabled, spec_json)
            VALUES (?, ?, ?, ?, ?::JSON)
            ON CONFLICT (strategy_id) DO UPDATE SET
                name = EXCLUDED.name,
                version = EXCLUDED.version,
                enabled = EXCLUDED.enabled,
                spec_json = EXCLUDED.spec_json,
                updated_at = ?
            """,
            [strategy_id, name, version, bool(enabled), json.dumps(spec), now()],
        )
        return strategy_id

    def set_enabled(self, strategy_id: str, enabled: bool) -> bool:
        """Flip the enabled flag for a strategy.

        Returns ``True`` if a row was updated, ``False`` if no such
        ``strategy_id`` exists.
        """
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a bool")
        if not self.exists(strategy_id):
            return False
        self._conn.execute(
            """
            UPDATE strategy_specs
            SET enabled = ?, updated_at = ?
            WHERE strategy_id = ?
            """,
            [enabled, now(), strategy_id],
        )
        return True

    def delete_spec(self, strategy_id: str) -> bool:
        """Remove a strategy. Returns ``True`` if a row was deleted."""
        if not self.exists(strategy_id):
            return False
        self._conn.execute(
            "DELETE FROM strategy_specs WHERE strategy_id = ?",
            [strategy_id],
        )
        return True

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_spec(self, strategy_id: str) -> dict[str, Any] | None:
        """Return the full record for *strategy_id*, or ``None``."""
        row = self._conn.execute(
            """SELECT strategy_id, name, version, enabled,
                      spec_json, created_at, updated_at
               FROM strategy_specs WHERE strategy_id = ?""",
            [strategy_id],
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row, include_spec=True)

    def list_specs(
        self,
        *,
        enabled_only: bool | None = None,
    ) -> list[dict[str, Any]]:
        """Return summary rows ordered by strategy_id ascending.

        ``enabled_only=True`` filters to rows with ``enabled = TRUE``;
        ``enabled_only=False`` filters to rows with ``enabled = FALSE``;
        ``None`` returns all rows.
        """
        sql = """SELECT strategy_id, name, version, enabled,
                        spec_json, created_at, updated_at
                 FROM strategy_specs"""
        params: list[Any] = []
        if enabled_only is True:
            sql += " WHERE enabled = TRUE"
        elif enabled_only is False:
            sql += " WHERE enabled = FALSE"
        sql += " ORDER BY strategy_id ASC"

        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r, include_spec=False) for r in rows]

    def list_enabled_strategy_ids(self) -> list[str]:
        """Return the strategy_ids of every enabled strategy."""
        rows = self._conn.execute(
            "SELECT strategy_id FROM strategy_specs "
            "WHERE enabled = TRUE ORDER BY strategy_id ASC"
        ).fetchall()
        return [str(r[0]) for r in rows]

    def exists(self, strategy_id: str) -> bool:
        """Return ``True`` if a spec with this id exists."""
        row = self._conn.execute(
            "SELECT 1 FROM strategy_specs WHERE strategy_id = ?",
            [strategy_id],
        ).fetchone()
        return row is not None

    def count(self) -> int:
        """Return the total number of stored specs."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM strategy_specs"
        ).fetchone()
        return int(row[0]) if row is not None else 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(
        row: tuple[Any, ...],
        *,
        include_spec: bool,
    ) -> dict[str, Any]:
        spec_raw = row[4]
        spec_obj: dict[str, Any] = (
            spec_raw if isinstance(spec_raw, dict) else json.loads(str(spec_raw))
        )
        result: dict[str, Any] = {
            "strategy_id": row[0],
            "name": row[1],
            "version": row[2],
            "enabled": bool(row[3]),
            "created_at": str(row[5]),
            "updated_at": str(row[6]),
        }
        if include_spec:
            result["spec"] = spec_obj
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


__all__ = ["StrategySpecStore"]