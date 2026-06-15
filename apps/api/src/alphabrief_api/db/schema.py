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
# Table: backtest_reports
# ---------------------------------------------------------------------------

CREATE_BACKTEST_REPORTS_TABLE = """
CREATE TABLE IF NOT EXISTS backtest_reports (
    id              TEXT PRIMARY KEY,
    symbol          TEXT NOT NULL,
    strategy_name   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    report_json     JSON NOT NULL
)
"""

# ---------------------------------------------------------------------------
# Table: briefs
# ---------------------------------------------------------------------------

CREATE_BRIEFS_TABLE = """
CREATE TABLE IF NOT EXISTS briefs (
    id              TEXT PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    brief_json      JSON NOT NULL
)
"""

# ---------------------------------------------------------------------------
# Table: audit_events
# ---------------------------------------------------------------------------

CREATE_AUDIT_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS audit_events (
    id              TEXT PRIMARY KEY,
    event_type      TEXT NOT NULL,
    symbol          TEXT,
    details_json    JSON,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

# ---------------------------------------------------------------------------
# Table: portfolio_snapshot
# ---------------------------------------------------------------------------

CREATE_PORTFOLIO_SNAPSHOT_TABLE = """
CREATE TABLE IF NOT EXISTS portfolio_snapshot (
    id              TEXT PRIMARY KEY,
    cash            TEXT NOT NULL,
    realized_pnl    TEXT NOT NULL,
    total_value     TEXT NOT NULL,
    positions_json  JSON NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

# ---------------------------------------------------------------------------
# Table: review_snapshots
# ---------------------------------------------------------------------------

CREATE_REVIEW_SNAPSHOTS_TABLE = """
CREATE TABLE IF NOT EXISTS review_snapshots (
    id              TEXT PRIMARY KEY,
    snapshot_json   JSON NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

# ---------------------------------------------------------------------------
# Table: debate_records
# ---------------------------------------------------------------------------

CREATE_DEBATE_RECORDS_TABLE = """
CREATE TABLE IF NOT EXISTS debate_records (
    id              TEXT PRIMARY KEY,
    question_json   JSON NOT NULL,
    responses_json  JSON NOT NULL,
    consensus_json  JSON NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

# ---------------------------------------------------------------------------
# Ordered list for apply / clear helpers
# ---------------------------------------------------------------------------

_SCHEMA_STATEMENTS: tuple[str, ...] = (
    CREATE_SYMBOLS_TABLE,
    CREATE_BARS_TABLE,
    CREATE_BACKTEST_REPORTS_TABLE,
    CREATE_BRIEFS_TABLE,
    CREATE_AUDIT_EVENTS_TABLE,
    CREATE_PORTFOLIO_SNAPSHOT_TABLE,
    CREATE_REVIEW_SNAPSHOTS_TABLE,
    CREATE_DEBATE_RECORDS_TABLE,
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
    connection.execute("DROP TABLE IF EXISTS debate_records")
    connection.execute("DROP TABLE IF EXISTS review_snapshots")
    connection.execute("DROP TABLE IF EXISTS portfolio_snapshot")
    connection.execute("DROP TABLE IF EXISTS audit_events")
    connection.execute("DROP TABLE IF EXISTS briefs")
    connection.execute("DROP TABLE IF EXISTS backtest_reports")
    connection.execute("DROP TABLE IF EXISTS bars")
    connection.execute("DROP TABLE IF EXISTS symbols")


__all__ = [
    "apply_schema",
    "drop_schema",
    "CREATE_AUDIT_EVENTS_TABLE",
    "CREATE_BACKTEST_REPORTS_TABLE",
    "CREATE_BARS_TABLE",
    "CREATE_BRIEFS_TABLE",
    "CREATE_DEBATE_RECORDS_TABLE",
    "CREATE_PORTFOLIO_SNAPSHOT_TABLE",
    "CREATE_REVIEW_SNAPSHOTS_TABLE",
    "CREATE_SYMBOLS_TABLE",
]
