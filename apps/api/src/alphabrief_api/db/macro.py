"""DuckDB-backed persistent store for macro-economic indicators."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
from alphabrief_news.types import MacroIndicator

from alphabrief_api.db.schema import apply_schema, drop_schema

# ---------------------------------------------------------------------------
# Default data directory
# ---------------------------------------------------------------------------

_DEFAULT_DB_DIR = Path.home() / ".alphabrief" / "data"


def _db_dir() -> Path:
    """Return the configured data directory for the DuckDB database."""
    import os

    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    return _DEFAULT_DB_DIR


def _db_path() -> Path:
    """Return the full path to the DuckDB database file."""
    db_dir = _db_dir()
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "alphabrief.db"


# ---------------------------------------------------------------------------
# MacroStore
# ---------------------------------------------------------------------------


class MacroStore:
    """DuckDB-backed persistent store for macro-economic indicators."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _db_path()
        self._db_path = Path(db_path)
        self._conn = duckdb.connect(str(self._db_path))
        apply_schema(self._conn)

    def insert_indicators(self, indicators: list[MacroIndicator]) -> int:
        """Insert or replace indicators. Returns the number inserted."""
        if not indicators:
            return 0

        rows: list[tuple[object, ...]] = []
        for indicator in indicators:
            rows.append(
                (
                    indicator.indicator_id,
                    indicator.name,
                    indicator.country,
                    indicator.released_at,
                    indicator.period,
                    float(indicator.value),
                    indicator.unit,
                    indicator.source,
                    indicator.data_version,
                )
            )

        self._conn.executemany(
            """
            INSERT OR REPLACE INTO macro_indicators (
                indicator_id, name, country, released_at, period,
                value, unit, source, data_version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        return len(indicators)

    def get_indicator(self, indicator_id: str) -> MacroIndicator | None:
        """Return the most recent observation for *indicator_id*."""
        row = self._conn.execute(
            """SELECT indicator_id, name, country, released_at, period,
                      value, unit, source, data_version
               FROM macro_indicators
               WHERE indicator_id = ?
               ORDER BY released_at DESC
               LIMIT 1""",
            [indicator_id],
        ).fetchone()
        if row is None:
            return None
        return _row_to_indicator(row)

    def list_indicators(
        self,
        indicator_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MacroIndicator]:
        """Return indicators, optionally filtered by id and time window."""
        conditions: list[str] = []
        params: list[object] = []

        if indicator_id is not None:
            conditions.append("indicator_id = ?")
            params.append(indicator_id)
        if start is not None:
            conditions.append("released_at >= ?")
            params.append(start)
        if end is not None:
            conditions.append("released_at < ?")
            params.append(end)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        rows = self._conn.execute(
            f"""SELECT indicator_id, name, country, released_at, period,
                       value, unit, source, data_version
                FROM macro_indicators
                {where_clause}
                ORDER BY released_at DESC
                LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()

        return [_row_to_indicator(row) for row in rows]

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
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_indicator(row: tuple[object, ...]) -> MacroIndicator:
    """Convert a DuckDB row into a ``MacroIndicator`` domain object."""
    released_at = row[3]
    if isinstance(released_at, datetime):
        released_at = (
            released_at
            if released_at.tzinfo is not None
            else released_at.replace(tzinfo=UTC)
        ).astimezone(UTC)
    else:
        released_at = datetime.fromisoformat(str(released_at))

    return MacroIndicator(
        indicator_id=str(row[0]),
        name=str(row[1]),
        country=str(row[2]),
        released_at=released_at,
        period=str(row[4]) if row[4] is not None else None,
        value=Decimal(str(row[5])),
        unit=str(row[6]) if row[6] is not None else None,
        source=str(row[7]),
        data_version=str(row[8]),
    )


__all__ = ["MacroStore"]
