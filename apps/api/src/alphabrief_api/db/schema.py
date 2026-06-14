"""DuckDB schema definitions for the AlphaBrief persistent storage layer.

All DDL statements use ``CREATE TABLE IF NOT EXISTS`` so the schema can be
applied safely on every application start.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Table: symbols
# ---------------------------------------------------------------------------

CREATE_SYMBOLS_TABLE = """
CREATE TABLE IF NOT EXISTS symbols (
    symbol          VARCHAR PRIMARY KEY,
    source          VARCHAR NOT NULL,
    data_version    VARCHAR NOT NULL,
    bar_count       INTEGER NOT NULL,
    time_start      TIMESTAMPTZ,
    time_end        TIMESTAMPTZ,
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

# ---------------------------------------------------------------------------
# Table: bars
# ---------------------------------------------------------------------------

CREATE_BARS_TABLE = """
CREATE TABLE IF NOT EXISTS bars (
    symbol          VARCHAR NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL,
    open            DECIMAL(38, 18) NOT NULL,
    high            DECIMAL(38, 18) NOT NULL,
    low             DECIMAL(38, 18) NOT NULL,
    close           DECIMAL(38, 18) NOT NULL,
    volume          DECIMAL(38, 18) NOT NULL,
    source          VARCHAR NOT NULL,
    data_version    VARCHAR NOT NULL,
    PRIMARY KEY     (symbol, timestamp)
)
"""

# ---------------------------------------------------------------------------
# Ordered list for apply / clear helpers
# ---------------------------------------------------------------------------

_SCHEMA_STATEMENTS: tuple[str, ...] = (
    CREATE_SYMBOLS_TABLE,
    CREATE_BARS_TABLE,
)

# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------


def apply_schema(connection: Any) -> None:
    """Create all tables (idempotent)."""
    for stmt in _SCHEMA_STATEMENTS:
        connection.execute(stmt)


def drop_schema(connection: Any) -> None:
    """Drop all tables (for test isolation)."""
    connection.execute("DROP TABLE IF EXISTS bars")
    connection.execute("DROP TABLE IF EXISTS symbols")


__all__ = [
    "apply_schema",
    "drop_schema",
    "CREATE_BARS_TABLE",
    "CREATE_SYMBOLS_TABLE",
]
