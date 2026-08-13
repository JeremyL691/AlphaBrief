"""DuckDB schema helpers owned by the AI trading package.

The API-wide schema also creates these tables when the FastAPI data layer is
initialized. The package store keeps a local copy of the AI-only DDL so
``alphabrief_trader`` can be imported and tested without importing
``alphabrief_api`` and triggering the application router graph.
"""

from __future__ import annotations

from typing import Any

CREATE_AI_DAILY_CYCLES_TABLE = """
CREATE TABLE IF NOT EXISTS ai_daily_cycles (
    cycle_id              TEXT PRIMARY KEY,
    trading_day           TEXT NOT NULL,
    symbols_json          JSON NOT NULL,
    outcome               TEXT NOT NULL,
    enabled               BOOLEAN NOT NULL,
    live_trading_enabled  BOOLEAN NOT NULL,
    summary               TEXT NOT NULL,
    cycle_json            JSON NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_AI_DAILY_CYCLES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_ai_daily_cycles_day
    ON ai_daily_cycles (trading_day, created_at DESC)
"""

CREATE_AI_COMMITTEE_VOTES_TABLE = """
CREATE TABLE IF NOT EXISTS ai_committee_votes (
    cycle_id              TEXT NOT NULL,
    vote_index            INTEGER NOT NULL,
    role                  TEXT NOT NULL,
    model_name            TEXT NOT NULL,
    view                  TEXT NOT NULL,
    confidence            DOUBLE NOT NULL,
    suggested_action      TEXT NOT NULL,
    target_position_pct   TEXT NOT NULL,
    veto                  BOOLEAN NOT NULL,
    needs_human_review    BOOLEAN NOT NULL,
    vote_json             JSON NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (cycle_id, vote_index)
)
"""

CREATE_AI_COMMITTEE_VOTES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_ai_committee_votes_role_created
    ON ai_committee_votes (role, created_at DESC)
"""

CREATE_AI_ORDER_ATTEMPTS_TABLE = """
CREATE TABLE IF NOT EXISTS ai_order_attempts (
    cycle_id                TEXT NOT NULL,
    intent_id               TEXT NOT NULL,
    outcome                 TEXT NOT NULL,
    approved                BOOLEAN NOT NULL,
    requires_human_review   BOOLEAN NOT NULL,
    filled                  BOOLEAN NOT NULL,
    order_id                TEXT,
    attempt_json            JSON NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (cycle_id, intent_id)
)
"""

CREATE_AI_ORDER_ATTEMPTS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_ai_order_attempts_cycle
    ON ai_order_attempts (cycle_id, created_at DESC)
"""

CREATE_AI_DISCIPLINE_CONFIG_TABLE = """
CREATE TABLE IF NOT EXISTS ai_discipline_config (
    snapshot_id   TEXT PRIMARY KEY,
    config_json   JSON NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_CYCLE_CHECKPOINTS_TABLE = """
CREATE TABLE IF NOT EXISTS cycle_checkpoints (
    cycle_id        TEXT PRIMARY KEY,
    phase           TEXT NOT NULL,
    phase_order     INTEGER NOT NULL,
    output_ids_json JSON NOT NULL DEFAULT '{}',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_CYCLE_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS cycle_state (
    cycle_id        TEXT PRIMARY KEY,
    phase           TEXT NOT NULL,
    phase_order     INTEGER NOT NULL,
    outcome         TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_CYCLE_STATE_TRANSITIONS_TABLE = """
CREATE TABLE IF NOT EXISTS cycle_state_transitions (
    transition_id     TEXT PRIMARY KEY,
    cycle_id          TEXT NOT NULL,
    phase             TEXT NOT NULL,
    phase_order       INTEGER NOT NULL,
    prior_phase       TEXT,
    attempt_count     INTEGER NOT NULL DEFAULT 0,
    input_hashes_json JSON NOT NULL DEFAULT '{}',
    output_ids_json   JSON NOT NULL DEFAULT '{}',
    outcome           TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_CYCLE_STATE_TRANSITIONS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_cycle_state_transitions_cycle
    ON cycle_state_transitions (cycle_id, phase_order, created_at)
"""

CREATE_SCHEDULER_LEASE_TABLE = """
CREATE TABLE IF NOT EXISTS scheduler_lease (
    holder_id       TEXT NOT NULL,
    acquired_at     TIMESTAMPTZ NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1
)
"""

CREATE_SCHEDULER_RUNTIME_TABLE = """
CREATE TABLE IF NOT EXISTS scheduler_runtime (
    row_id          INTEGER PRIMARY KEY CHECK (row_id = 1),
    leader_id       TEXT,
    active_config_json JSON NOT NULL DEFAULT '{}',
    running_phase   TEXT,
    heartbeat_at    TIMESTAMPTZ,
    last_outcome    TEXT,
    next_due_at     TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_EXECUTION_MODE_TABLE = """
CREATE TABLE IF NOT EXISTS execution_mode (
    row_id      INTEGER PRIMARY KEY CHECK (row_id = 1),
    mode        TEXT NOT NULL,
    reasons_json JSON NOT NULL DEFAULT '[]',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_AI_SCHEMA_STATEMENTS: tuple[str, ...] = (
    CREATE_AI_DAILY_CYCLES_TABLE,
    CREATE_AI_DAILY_CYCLES_INDEX,
    CREATE_AI_COMMITTEE_VOTES_TABLE,
    CREATE_AI_COMMITTEE_VOTES_INDEX,
    CREATE_AI_ORDER_ATTEMPTS_TABLE,
    CREATE_AI_ORDER_ATTEMPTS_INDEX,
    CREATE_AI_DISCIPLINE_CONFIG_TABLE,
    CREATE_CYCLE_CHECKPOINTS_TABLE,
    CREATE_CYCLE_STATE_TABLE,
    CREATE_CYCLE_STATE_TRANSITIONS_TABLE,
    CREATE_CYCLE_STATE_TRANSITIONS_INDEX,
    CREATE_SCHEDULER_LEASE_TABLE,
    CREATE_SCHEDULER_RUNTIME_TABLE,
    CREATE_EXECUTION_MODE_TABLE,
)


def apply_ai_trading_schema(connection: Any) -> None:
    """Create the AI trading tables and indexes on ``connection``."""

    for statement in _AI_SCHEMA_STATEMENTS:
        connection.execute(statement)


def drop_ai_trading_schema(connection: Any) -> None:
    """Drop only AI trading tables, leaving the rest of the DB intact."""

    connection.execute("DROP TABLE IF EXISTS execution_mode")
    connection.execute("DROP TABLE IF EXISTS scheduler_runtime")
    connection.execute("DROP TABLE IF EXISTS scheduler_lease")
    connection.execute("DROP TABLE IF EXISTS cycle_state_transitions")
    connection.execute("DROP TABLE IF EXISTS cycle_state")
    connection.execute("DROP TABLE IF EXISTS cycle_checkpoints")
    connection.execute("DROP TABLE IF EXISTS ai_order_attempts")
    connection.execute("DROP TABLE IF EXISTS ai_committee_votes")
    connection.execute("DROP TABLE IF EXISTS ai_daily_cycles")
    connection.execute("DROP TABLE IF EXISTS ai_discipline_config")


__all__ = [
    "CREATE_AI_COMMITTEE_VOTES_INDEX",
    "CREATE_CYCLE_CHECKPOINTS_TABLE",
    "CREATE_CYCLE_STATE_TABLE",
    "CREATE_CYCLE_STATE_TRANSITIONS_INDEX",
    "CREATE_CYCLE_STATE_TRANSITIONS_TABLE",
    "CREATE_AI_COMMITTEE_VOTES_TABLE",
    "CREATE_AI_DAILY_CYCLES_INDEX",
    "CREATE_AI_DAILY_CYCLES_TABLE",
    "CREATE_AI_DISCIPLINE_CONFIG_TABLE",
    "CREATE_AI_ORDER_ATTEMPTS_INDEX",
    "CREATE_AI_ORDER_ATTEMPTS_TABLE",
    "CREATE_EXECUTION_MODE_TABLE",
    "CREATE_SCHEDULER_LEASE_TABLE",
    "CREATE_SCHEDULER_RUNTIME_TABLE",
    "apply_ai_trading_schema",
    "drop_ai_trading_schema",
]
