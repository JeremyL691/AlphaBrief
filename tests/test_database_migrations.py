"""M03-W01: versioned, transactional, idempotent database migrations.

Covers:
- empty, current-baseline, and fixture schemas migrate to the same
  latest version (AC-M03-W01-01);
- re-running migrations changes no data and an interrupted migration
  rolls back atomically (AC-M03-W01-02);
- a newer or corrupt schema fails startup without partial writes
  (AC-M03-W01-03).
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import duckdb
import pytest
from alphabrief_api.db.migrations import (
    Migration,
    SchemaCompatibilityError,
    check_compatibility,
    current_schema_version,
    migrate,
)
from alphabrief_api.db.schema import (
    apply_schema,
    drop_schema,
    latest_schema_version,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_GOOD_V1 = Migration(
    version=1,
    name="test-v1",
    statements=("CREATE TABLE IF NOT EXISTS t_v1 (id INTEGER PRIMARY KEY)",),
)
_GOOD_V2 = Migration(
    version=2,
    name="test-v2",
    statements=("CREATE TABLE IF NOT EXISTS t_v2 (id INTEGER PRIMARY KEY)",),
)


@pytest.fixture
def connection() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    conn = duckdb.connect()
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# AC-M03-W01-01: same latest version from every starting point
# ---------------------------------------------------------------------------


def test_empty_database_migrates_to_latest(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    apply_schema(connection)
    assert current_schema_version(connection) == latest_schema_version()
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()
    }
    assert "symbols" in tables
    assert "bars" in tables
    assert "schema_migrations" in tables


def test_current_baseline_schema_migrates_to_latest(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """A pre-migration database (tables without a ledger) upgrades cleanly."""
    from alphabrief_api.db.schema import _SCHEMA_STATEMENTS

    for statement in _SCHEMA_STATEMENTS:
        connection.execute(statement)
    connection.execute(
        "INSERT INTO symbols (symbol, source, data_version, bar_count) "
        "VALUES ('EUR_USD', 'test', 'v1', 0)"
    )

    apply_schema(connection)

    assert current_schema_version(connection) == latest_schema_version()
    rows = connection.execute(
        "SELECT symbol FROM symbols WHERE symbol = 'EUR_USD'"
    ).fetchall()
    assert rows == [("EUR_USD",)]


def test_fixture_schema_migrates_to_latest(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """A store fixture (apply + drop + apply) converges to the same version."""
    apply_schema(connection)
    drop_schema(connection)
    apply_schema(connection)
    assert current_schema_version(connection) == latest_schema_version()


def test_custom_migrations_apply_in_version_order(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    migrate(connection, migrations=(_GOOD_V1, _GOOD_V2))
    assert current_schema_version(connection) == 2


# ---------------------------------------------------------------------------
# AC-M03-W01-02: idempotent re-runs and atomic rollback
# ---------------------------------------------------------------------------


def test_re_running_migrations_changes_no_data(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    apply_schema(connection)
    connection.execute(
        "INSERT INTO symbols (symbol, source, data_version, bar_count) "
        "VALUES ('USD_JPY', 'test', 'v1', 7)"
    )
    before = connection.execute(
        "SELECT symbol, bar_count FROM symbols WHERE symbol = 'USD_JPY'"
    ).fetchall()

    apply_schema(connection)
    apply_schema(connection)

    after = connection.execute(
        "SELECT symbol, bar_count FROM symbols WHERE symbol = 'USD_JPY'"
    ).fetchall()
    assert before == after == [("USD_JPY", 7)]
    assert current_schema_version(connection) == latest_schema_version()


def test_interrupted_migration_rolls_back_atomically(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """A failing migration leaves no partial writes behind."""
    broken = Migration(
        version=7,
        name="broken-v7",
        statements=(
            "CREATE TABLE t_partial (id INTEGER)",
            "THIS IS NOT VALID SQL",
        ),
    )

    with pytest.raises(duckdb.Error):
        migrate(connection, migrations=(_GOOD_V1, broken))

    assert current_schema_version(connection) == 1
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()
    }
    assert "t_partial" not in tables
    assert "t_v1" in tables


# ---------------------------------------------------------------------------
# AC-M03-W01-03: newer or corrupt schema fails startup
# ---------------------------------------------------------------------------


def test_newer_schema_fails_startup(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """A database migrated past this build's latest version fails closed."""
    migrate(connection, migrations=(_GOOD_V1, _GOOD_V2))

    # A build that only knows v1 sees v2 as an unknown applied version.
    with pytest.raises(SchemaCompatibilityError, match="unknown to this build"):
        check_compatibility(connection, migrations=(_GOOD_V1,))

    # A build that knows v1..v3 but only supports v2 rejects the newer v3.
    v3 = Migration(
        version=3,
        name="test-v3",
        statements=("CREATE TABLE IF NOT EXISTS t_v3 (id INTEGER PRIMARY KEY)",),
    )
    migrate(connection, migrations=(_GOOD_V1, _GOOD_V2, v3))
    with pytest.raises(SchemaCompatibilityError, match="newer"):
        check_compatibility(
            connection,
            migrations=(_GOOD_V1, _GOOD_V2, v3),
            expected_latest=2,
        )

    # The startup path (apply_schema with the real v1-only build) also
    # fails closed before any write.
    with pytest.raises(SchemaCompatibilityError):
        apply_schema(connection)
    assert current_schema_version(connection) == 3


def test_corrupt_schema_fails_startup(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Unknown applied versions in the ledger fail the startup check."""
    migrate(connection, migrations=(_GOOD_V1,))
    connection.execute(
        "INSERT INTO schema_migrations (version, name) VALUES (99, 'ghost')"
    )

    with pytest.raises(SchemaCompatibilityError, match="unknown to this build"):
        check_compatibility(connection, migrations=(_GOOD_V1,))


def test_compatibility_passes_for_matching_schema(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    migrate(connection, migrations=(_GOOD_V1, _GOOD_V2))
    check_compatibility(connection, migrations=(_GOOD_V1, _GOOD_V2))
    assert current_schema_version(connection) == 2
