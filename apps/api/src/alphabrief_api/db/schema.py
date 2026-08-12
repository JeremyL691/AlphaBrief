"""DuckDB schema definitions for the AlphaBrief persistent storage layer.

All DDL statements use ``CREATE TABLE IF NOT EXISTS`` so the schema can be
applied safely on every application start.
"""

from __future__ import annotations

from typing import Any

from alphabrief_api.db.migrations import (
    Migration,
    check_compatibility,
    migrate,
)

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
    report_engine   TEXT DEFAULT 'legacy',
    report_json     JSON NOT NULL
)
"""

ALTER_BACKTEST_REPORTS_ADD_REPORT_ENGINE = """
ALTER TABLE backtest_reports
ADD COLUMN IF NOT EXISTS report_engine TEXT DEFAULT 'legacy'
"""

UPDATE_BACKTEST_REPORTS_REPORT_ENGINE_DEFAULT = """
UPDATE backtest_reports SET report_engine = 'legacy' WHERE report_engine IS NULL
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
# Table: news_headlines
# ---------------------------------------------------------------------------

CREATE_NEWS_HEADLINES_TABLE = """
CREATE TABLE IF NOT EXISTS news_headlines (
    headline_id     VARCHAR PRIMARY KEY,
    published_at    TIMESTAMPTZ NOT NULL,
    symbols         VARCHAR NOT NULL,
    category        VARCHAR NOT NULL,
    source          VARCHAR NOT NULL,
    title           VARCHAR NOT NULL,
    summary         VARCHAR NOT NULL,
    url             VARCHAR,
    sentiment       VARCHAR,
    data_version    VARCHAR NOT NULL
)
"""

# ---------------------------------------------------------------------------
# Table: macro_indicators
# ---------------------------------------------------------------------------

CREATE_MACRO_INDICATORS_TABLE = """
CREATE TABLE IF NOT EXISTS macro_indicators (
    indicator_id    VARCHAR PRIMARY KEY,
    name            VARCHAR NOT NULL,
    country         VARCHAR NOT NULL,
    released_at     TIMESTAMPTZ NOT NULL,
    period          VARCHAR,
    value           DOUBLE NOT NULL,
    unit            VARCHAR,
    source          VARCHAR NOT NULL,
    data_version    VARCHAR NOT NULL
)
"""

# ---------------------------------------------------------------------------
# Table: model_evaluations
# ---------------------------------------------------------------------------

CREATE_MODEL_EVALUATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS model_evaluations (
    id                    TEXT PRIMARY KEY,
    model_id              TEXT NOT NULL,
    provider              TEXT NOT NULL,
    task_type             TEXT NOT NULL,
    eval_dataset          TEXT NOT NULL,
    json_valid_rate       DOUBLE,
    schema_pass_rate      DOUBLE,
    hallucination_rate    DOUBLE,
    avg_latency_ms        INTEGER,
    avg_cost_estimate     DOUBLE,
    sample_count          INTEGER NOT NULL,
    eval_config_json      TEXT NOT NULL DEFAULT '{}',
    evaluated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

# ---------------------------------------------------------------------------
# Table: strategy_specs
# ---------------------------------------------------------------------------

CREATE_STRATEGY_SPECS_TABLE = """
CREATE TABLE IF NOT EXISTS strategy_specs (
    strategy_id    TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    version        TEXT NOT NULL,
    enabled        BOOLEAN NOT NULL DEFAULT FALSE,
    spec_json      JSON NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

# ---------------------------------------------------------------------------
# Table: strategy_signals
# ---------------------------------------------------------------------------
#
# Persistent signal history. Each row is one strategy-generated
# signal. The store is **advisory**: it never blocks orders, never
# modifies risk decisions, and is never consulted by the execution
# path. It exists so backtests, manual runs, and the dashboard can
# replay / inspect what a strategy emitted at a specific bar
# timestamp. ``signal_json`` is the full signal payload (incl.
# optional ``evidence``), so the store is forward-compatible with
# future signal schema additions.
#
# ``source`` distinguishes the call site that produced the signal:
# - ``"backtest"``  : vectorized backtester
# - ``"manual"``    : explicit CLI / API call
# - ``"other"``     : default for unknown callers
#
# Phase 15 R15.5 records manual recordings from CLI/API; automatic
# backtest recording is wired when the vectorized backtester emits
# signals. Both code paths share this single table.

CREATE_STRATEGY_SIGNALS_TABLE = """
CREATE TABLE IF NOT EXISTS strategy_signals (
    signal_id      TEXT PRIMARY KEY,
    strategy_id    TEXT NOT NULL,
    symbol         TEXT NOT NULL,
    signal_ts      TIMESTAMPTZ NOT NULL,
    direction      TEXT NOT NULL,
    confidence     DOUBLE NOT NULL,
    horizon        TEXT NOT NULL,
    source         TEXT NOT NULL DEFAULT 'other',
    signal_json    JSON NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_STRATEGY_SIGNALS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_strategy_signals_strategy_ts
    ON strategy_signals (strategy_id, signal_ts DESC)
"""

# ---------------------------------------------------------------------------
# Table: strategy_admissions
# ---------------------------------------------------------------------------
#
# Strategy-admission records are append-only audit evidence. They are never
# consulted by RiskGate or execution code, so an approval cannot authorize an
# order by itself.

CREATE_STRATEGY_ADMISSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS strategy_admissions (
    admission_id            TEXT PRIMARY KEY,
    strategy_id             TEXT NOT NULL,
    strategy_version        TEXT NOT NULL,
    status                  TEXT NOT NULL,
    reviewer_id             TEXT NOT NULL,
    reviewed_at             TIMESTAMPTZ NOT NULL,
    evidence_json           JSON NOT NULL,
    supersedes_admission_id TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_STRATEGY_ADMISSIONS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_strategy_admissions_strategy_created
    ON strategy_admissions (strategy_id, created_at DESC)
"""

# ---------------------------------------------------------------------------
# Phase 17 broker reconciliation tables
# ---------------------------------------------------------------------------
#
# The broker reconciliation store keeps three append-only tables that
# together form an auditable trail of external paper broker activity:
#
# - ``broker_order_id_map``: bidirectional mapping between AlphaBrief
#   client order ids and external broker order ids. Idempotent submit
#   relies on this map; restarts reload it before the first order.
#
# - ``broker_recon_snapshots``: one row per reconciliation pass. The
#   ``scope`` column distinguishes startup / cycle / eod runs. A row
#   with ``all_match=False`` is the signal that auto-ordering must be
#   frozen; ``freeze_events`` records the resulting freeze.
#
# - ``broker_freeze_events``: append-only log of freeze and unfreeze
#   actions. A freeze is in effect while at least one row with
#   ``cleared_at IS NULL`` exists for the same scope. The store
#   refuses auto-submit while any open freeze is present.

CREATE_BROKER_ORDER_ID_MAP_TABLE = """
CREATE TABLE IF NOT EXISTS broker_order_id_map (
    client_order_id    TEXT PRIMARY KEY,
    broker_order_id    TEXT NOT NULL,
    status             TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_BROKER_RECON_SNAPSHOTS_TABLE = """
CREATE TABLE IF NOT EXISTS broker_recon_snapshots (
    snapshot_id        TEXT PRIMARY KEY,
    captured_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    scope              TEXT NOT NULL,
    orders_match       BOOLEAN NOT NULL,
    fills_match        BOOLEAN NOT NULL,
    cash_match         BOOLEAN NOT NULL,
    positions_match    BOOLEAN NOT NULL,
    diff_json          JSON NOT NULL DEFAULT '{}'
)
"""

CREATE_BROKER_FREEZE_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS broker_freeze_events (
    event_id           TEXT PRIMARY KEY,
    raised_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    cleared_at         TIMESTAMPTZ,
    scope              TEXT NOT NULL,
    reason             TEXT NOT NULL,
    source             TEXT NOT NULL,
    related_snapshot_id TEXT
)
"""

# ---------------------------------------------------------------------------
# Table: account_equity_snapshots
# ---------------------------------------------------------------------------
#
# R21.3: append-only account equity snapshots used by the daily-loss and
# drawdown risk rules. One row per fill (written by the paper route after
# each execution). The gate reads the latest snapshot (current equity, the
# drawdown high-water mark) and the day's first snapshot (day-start equity
# for the daily-loss check). Persisting across restarts keeps the
# drawdown floor tighten-only: an in-memory HWM would reset on restart and
# silently widen the floor. Equity is stored as TEXT to preserve Decimal
# precision (mirrors portfolio_snapshot's cash/realized_pnl columns).

CREATE_ACCOUNT_EQUITY_SNAPSHOTS_TABLE = """
CREATE TABLE IF NOT EXISTS account_equity_snapshots (
    snapshot_id        TEXT PRIMARY KEY,
    account_id         TEXT NOT NULL,
    captured_at        TIMESTAMPTZ NOT NULL,
    equity             TEXT NOT NULL,
    realized_pnl_day   TEXT NOT NULL DEFAULT '0',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_ACCOUNT_EQUITY_SNAPSHOTS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_account_equity_snapshots_account_captured
    ON account_equity_snapshots (account_id, captured_at)
"""

# ---------------------------------------------------------------------------
# AI Trading Committee tables (Phase 26)
# ---------------------------------------------------------------------------
#
# Three denormalized tables back ``AiTradingStore``:
#
# - ``ai_daily_cycles``    — one row per daily cycle, JSON of the full
#   ``DailyCycleRecord`` plus the columns the history list needs
#   (trading_day, outcome, summary, created_at).
# - ``ai_committee_votes`` — one row per committee vote, keyed by
#   (cycle_id, role). Enables fast voting-history queries without
#   reparsing the cycle JSON.
# - ``ai_order_attempts``  — one row per ``OrderAttempt``. JSON column
#   carries the full payload (intent / risk decision / fill) so an
#   operator can replay any cycle decision-by-decision.
# - ``ai_discipline_config`` — append-only snapshots of the discipline
#   config that was in effect for a cycle. Pure advisory; never read
#   by RiskGate.

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

# ---------------------------------------------------------------------------
# Ordered list for apply / clear helpers
# ---------------------------------------------------------------------------

_SCHEMA_STATEMENTS: tuple[str, ...] = (
    CREATE_SYMBOLS_TABLE,
    CREATE_BARS_TABLE,
    CREATE_BACKTEST_REPORTS_TABLE,
    ALTER_BACKTEST_REPORTS_ADD_REPORT_ENGINE,
    UPDATE_BACKTEST_REPORTS_REPORT_ENGINE_DEFAULT,
    CREATE_BRIEFS_TABLE,
    CREATE_AUDIT_EVENTS_TABLE,
    CREATE_PORTFOLIO_SNAPSHOT_TABLE,
    CREATE_REVIEW_SNAPSHOTS_TABLE,
    CREATE_DEBATE_RECORDS_TABLE,
    CREATE_NEWS_HEADLINES_TABLE,
    CREATE_MACRO_INDICATORS_TABLE,
    CREATE_MODEL_EVALUATIONS_TABLE,
    CREATE_STRATEGY_SPECS_TABLE,
    CREATE_STRATEGY_SIGNALS_TABLE,
    CREATE_STRATEGY_SIGNALS_INDEX,
    CREATE_STRATEGY_ADMISSIONS_TABLE,
    CREATE_STRATEGY_ADMISSIONS_INDEX,
    CREATE_BROKER_ORDER_ID_MAP_TABLE,
    CREATE_BROKER_RECON_SNAPSHOTS_TABLE,
    CREATE_BROKER_FREEZE_EVENTS_TABLE,
    CREATE_ACCOUNT_EQUITY_SNAPSHOTS_TABLE,
    CREATE_ACCOUNT_EQUITY_SNAPSHOTS_INDEX,
    CREATE_AI_DAILY_CYCLES_TABLE,
    CREATE_AI_DAILY_CYCLES_INDEX,
    CREATE_AI_COMMITTEE_VOTES_TABLE,
    CREATE_AI_COMMITTEE_VOTES_INDEX,
    CREATE_AI_ORDER_ATTEMPTS_TABLE,
    CREATE_AI_ORDER_ATTEMPTS_INDEX,
    CREATE_AI_DISCIPLINE_CONFIG_TABLE,
)

# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

#: M03-W01: the baseline DDL set becomes migration v1. Table DDL is the
#: transactional unit; index DDL runs idempotently after the commit
#: (DuckDB cannot commit CREATE INDEX inside an explicit transaction when
#: another open connection dropped the same index). Every later schema
#: change appends a new Migration instead of editing these statements.
_TABLE_STATEMENTS: tuple[str, ...] = tuple(
    statement
    for statement in _SCHEMA_STATEMENTS
    if "CREATE INDEX" not in statement
)
_INDEX_STATEMENTS: tuple[str, ...] = tuple(
    statement
    for statement in _SCHEMA_STATEMENTS
    if "CREATE INDEX" in statement
)

MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="baseline-v1",
        statements=_TABLE_STATEMENTS,
        index_statements=_INDEX_STATEMENTS,
    ),
    Migration(
        version=2,
        name="versioned-bar-facts",
        statements=(
            # M03-W02: bars become immutable, versioned facts. The primary
            # key includes data_version and source so different versions of
            # the same symbol+timestamp coexist; fact_id is the
            # content-addressed identity computed by the store. Legacy rows
            # are backfilled with a stable content hash.
            """
            CREATE TABLE bars_v2 (
                symbol          VARCHAR NOT NULL,
                timestamp       TIMESTAMPTZ NOT NULL,
                open            DECIMAL(38, 18) NOT NULL,
                high            DECIMAL(38, 18) NOT NULL,
                low             DECIMAL(38, 18) NOT NULL,
                close           DECIMAL(38, 18) NOT NULL,
                volume          DECIMAL(38, 18) NOT NULL,
                source          VARCHAR NOT NULL,
                data_version    VARCHAR NOT NULL,
                fact_id         VARCHAR NOT NULL,
                ingested_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY     (symbol, timestamp, data_version, source)
            )
            """,
            """
            INSERT INTO bars_v2 (
                symbol, timestamp, open, high, low, close, volume,
                source, data_version, fact_id
            )
            SELECT
                symbol, timestamp, open, high, low, close, volume,
                source, data_version,
                'legacy|' || sha256(
                    concat(
                        CAST(symbol AS VARCHAR), '|',
                        CAST(timestamp AS VARCHAR), '|',
                        CAST(source AS VARCHAR), '|',
                        CAST(data_version AS VARCHAR)
                    )
                )
            FROM bars
            """,
            "DROP TABLE bars",
            "ALTER TABLE bars_v2 RENAME TO bars",
        ),
    ),
    Migration(
        version=3,
        name="instrument-catalog-snapshots",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS instrument_catalog_snapshots (
                snapshot_id     TEXT PRIMARY KEY,
                account_id_hash TEXT NOT NULL,
                content_hash    TEXT NOT NULL,
                diff_json       JSON NOT NULL DEFAULT '{}',
                fetched_at      TIMESTAMPTZ NOT NULL,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS instrument_catalog_rows (
                snapshot_id     TEXT NOT NULL,
                name            TEXT NOT NULL,
                metadata_json   JSON NOT NULL,
                PRIMARY KEY (snapshot_id, name)
            )
            """,
        ),
    ),
    Migration(
        version=4,
        name="market-data-snapshots",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS market_data_snapshots (
                snapshot_id           TEXT PRIMARY KEY,
                manifest_hash         TEXT NOT NULL,
                quality_policy_version TEXT NOT NULL,
                source_ids_json       JSON NOT NULL,
                quality_json          JSON NOT NULL,
                lineage_parent        TEXT,
                created_at            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS market_data_snapshot_facts (
                snapshot_id   TEXT NOT NULL,
                symbol        TEXT NOT NULL,
                fact_kind     TEXT NOT NULL,
                fact_id       TEXT NOT NULL,
                PRIMARY KEY (snapshot_id, symbol, fact_kind)
            )
            """,
        ),
    ),
)

_LATEST_SCHEMA_VERSION = max(migration.version for migration in MIGRATIONS)


def apply_schema(connection: Any) -> None:
    """Migrate the database to the latest schema version.

    Runs the startup compatibility check (a newer or corrupt schema fails
    closed) and then applies every pending migration atomically and
    idempotently (M03-W01).
    """
    check_compatibility(connection, migrations=MIGRATIONS)
    migrate(connection, migrations=MIGRATIONS)


def current_schema_version(connection: Any) -> int:
    """Return the applied schema version (0 for a fresh database)."""
    from alphabrief_api.db.migrations import current_schema_version as _current

    return _current(connection)


def latest_schema_version() -> int:
    """Return the latest version this build knows how to migrate to."""
    return _LATEST_SCHEMA_VERSION


def drop_schema(connection: Any) -> None:
    """Drop all tables (for test isolation).

    The migration ledger is dropped first so a subsequent
    ``apply_schema`` re-applies every migration instead of skipping the
    recorded versions. Indexes are dropped explicitly before their
    tables: a long-lived DuckDB catalog can otherwise keep a deleted
    index dependency that fails the next transactional commit.
    """
    connection.execute("DROP TABLE IF EXISTS schema_migrations")
    connection.execute("DROP INDEX IF EXISTS idx_strategy_signals_strategy_ts")
    connection.execute("DROP INDEX IF EXISTS idx_strategy_admissions_strategy_created")
    connection.execute(
        "DROP INDEX IF EXISTS idx_account_equity_snapshots_account_captured"
    )
    connection.execute("DROP INDEX IF EXISTS idx_ai_daily_cycles_day")
    connection.execute("DROP INDEX IF EXISTS idx_ai_committee_votes_role_created")
    connection.execute("DROP INDEX IF EXISTS idx_ai_order_attempts_cycle")
    connection.execute("DROP TABLE IF EXISTS ai_order_attempts")
    connection.execute("DROP TABLE IF EXISTS ai_committee_votes")
    connection.execute("DROP TABLE IF EXISTS ai_daily_cycles")
    connection.execute("DROP TABLE IF EXISTS ai_discipline_config")
    connection.execute("DROP TABLE IF EXISTS account_equity_snapshots")
    connection.execute("DROP TABLE IF EXISTS strategy_admissions")
    connection.execute("DROP TABLE IF EXISTS broker_freeze_events")
    connection.execute("DROP TABLE IF EXISTS broker_recon_snapshots")
    connection.execute("DROP TABLE IF EXISTS broker_order_id_map")
    connection.execute("DROP TABLE IF EXISTS strategy_signals")
    connection.execute("DROP TABLE IF EXISTS strategy_specs")
    connection.execute("DROP TABLE IF EXISTS model_evaluations")
    connection.execute("DROP TABLE IF EXISTS macro_indicators")
    connection.execute("DROP TABLE IF EXISTS news_headlines")
    connection.execute("DROP TABLE IF EXISTS debate_records")
    connection.execute("DROP TABLE IF EXISTS review_snapshots")
    connection.execute("DROP TABLE IF EXISTS portfolio_snapshot")
    connection.execute("DROP TABLE IF EXISTS audit_events")
    connection.execute("DROP TABLE IF EXISTS briefs")
    connection.execute("DROP TABLE IF EXISTS backtest_reports")
    connection.execute("DROP TABLE IF EXISTS bars")
    connection.execute("DROP TABLE IF EXISTS symbols")


__all__ = [
    "MIGRATIONS",
    "apply_schema",
    "current_schema_version",
    "drop_schema",
    "latest_schema_version",
    "CREATE_ACCOUNT_EQUITY_SNAPSHOTS_INDEX",
    "CREATE_ACCOUNT_EQUITY_SNAPSHOTS_TABLE",
    "CREATE_AI_COMMITTEE_VOTES_INDEX",
    "CREATE_AI_COMMITTEE_VOTES_TABLE",
    "CREATE_AI_DAILY_CYCLES_INDEX",
    "CREATE_AI_DAILY_CYCLES_TABLE",
    "CREATE_AI_DISCIPLINE_CONFIG_TABLE",
    "CREATE_AI_ORDER_ATTEMPTS_INDEX",
    "CREATE_AI_ORDER_ATTEMPTS_TABLE",
    "CREATE_AUDIT_EVENTS_TABLE",
    "CREATE_BACKTEST_REPORTS_TABLE",
    "CREATE_BARS_TABLE",
    "CREATE_BRIEFS_TABLE",
    "CREATE_BROKER_FREEZE_EVENTS_TABLE",
    "CREATE_BROKER_ORDER_ID_MAP_TABLE",
    "CREATE_BROKER_RECON_SNAPSHOTS_TABLE",
    "CREATE_DEBATE_RECORDS_TABLE",
    "CREATE_MACRO_INDICATORS_TABLE",
    "CREATE_MODEL_EVALUATIONS_TABLE",
    "CREATE_NEWS_HEADLINES_TABLE",
    "CREATE_PORTFOLIO_SNAPSHOT_TABLE",
    "CREATE_REVIEW_SNAPSHOTS_TABLE",
    "CREATE_STRATEGY_SIGNALS_TABLE",
    "CREATE_STRATEGY_SIGNALS_INDEX",
    "CREATE_STRATEGY_SPECS_TABLE",
    "CREATE_STRATEGY_ADMISSIONS_INDEX",
    "CREATE_STRATEGY_ADMISSIONS_TABLE",
    "CREATE_SYMBOLS_TABLE",
]
