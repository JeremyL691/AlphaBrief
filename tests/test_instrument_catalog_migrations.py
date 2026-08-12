"""M04-W03: instrument catalog schema migrations.

The catalog tables are created by migration v3; re-running migrations is
idempotent and the tables survive a clear/reapply cycle.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
from alphabrief_api.db.schema import (
    apply_schema,
    current_schema_version,
    drop_schema,
    latest_schema_version,
)


def test_catalog_tables_exist_after_migration(tmp_path: Path) -> None:
    db_path = tmp_path / "cat.db"
    conn = duckdb.connect(str(db_path))
    apply_schema(conn)
    assert current_schema_version(conn) == latest_schema_version()
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()
    }
    assert "instrument_catalog_snapshots" in tables
    assert "instrument_catalog_rows" in tables
    conn.close()


def test_catalog_migration_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "cat.db"
    conn = duckdb.connect(str(db_path))
    apply_schema(conn)
    apply_schema(conn)
    assert current_schema_version(conn) == latest_schema_version()
    conn.close()


def test_catalog_tables_survive_clear_reapply(tmp_path: Path) -> None:
    db_path = tmp_path / "cat.db"
    conn = duckdb.connect(str(db_path))
    apply_schema(conn)
    drop_schema(conn)
    apply_schema(conn)
    assert current_schema_version(conn) == latest_schema_version()
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()
    }
    assert "instrument_catalog_rows" in tables
    conn.close()
