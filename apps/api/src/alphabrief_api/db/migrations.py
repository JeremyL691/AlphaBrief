"""Versioned, transactional, idempotent DuckDB migrations (M03-W01).

Replaces the implicit ``CREATE TABLE IF NOT EXISTS`` startup with an
explicit ordered migration ledger:

- every migration runs inside a transaction and either commits fully or
  rolls back atomically, so an interrupted migration never leaves
  partial schema writes;
- re-running migrations is idempotent (applied versions are skipped and
  data is never touched);
- a newer or corrupt schema fails the startup compatibility check
  instead of being silently accepted (REQ-PLAT-004).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


class SchemaCompatibilityError(RuntimeError):
    """Raised when a database schema is newer or corrupt for this build."""


@dataclass(frozen=True)
class Migration:
    """One ordered, named schema migration.

    ``statements`` run inside one transaction (tables and ledger are the
    atomic unit). ``index_statements`` run after the transaction in
    autocommit: DuckDB's dependency tracking cannot commit a
    ``CREATE INDEX`` in an explicit transaction when the same index was
    dropped by another open connection to the catalog, so index DDL is
    applied idempotently outside the transaction.
    """

    version: int
    name: str
    statements: tuple[str, ...]
    index_statements: tuple[str, ...] = ()


def _applied_versions(connection: Any) -> set[int]:
    rows = connection.execute(
        "SELECT version FROM schema_migrations"
    ).fetchall()
    return {int(row[0]) for row in rows}


def current_schema_version(connection: Any) -> int:
    """Return the highest applied migration version (0 for fresh databases)."""
    row = connection.execute(
        "SELECT MAX(version) FROM schema_migrations"
    ).fetchone()
    if not row or row[0] is None:
        return 0
    return int(row[0])


def migrate(
    connection: Any,
    *,
    migrations: tuple[Migration, ...],
    target_version: int | None = None,
) -> int:
    """Apply every pending migration in version order.

    Table statements and the ledger row commit atomically per migration;
    a failure rolls the migration back completely and re-raises.
    Already-applied versions are skipped, so repeated runs change no
    data. Index statements run idempotently after the commit.
    """
    connection.execute(_CREATE_MIGRATIONS_TABLE)
    applied = _applied_versions(connection)
    ordered = sorted(migrations, key=lambda migration: migration.version)
    if target_version is not None:
        ordered = [
            migration
            for migration in ordered
            if migration.version <= target_version
        ]
    for migration in ordered:
        if migration.version in applied:
            continue
        connection.execute("BEGIN")
        try:
            for statement in migration.statements:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                [migration.version, migration.name],
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        for statement in migration.index_statements:
            connection.execute(statement)
    return current_schema_version(connection)


def check_compatibility(
    connection: Any,
    *,
    migrations: tuple[Migration, ...],
    expected_latest: int | None = None,
) -> None:
    """Fail closed when the database schema is newer or corrupt.

    A database without the migration ledger is treated as a
    pre-migration baseline (version 0) that ``migrate`` upgrades; a
    ledger that references versions unknown to this build, or an applied
    version newer than this build supports, raises
    :class:`SchemaCompatibilityError` before any write.
    """
    row = connection.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name = 'schema_migrations'"
    ).fetchone()
    if not row or int(row[0]) == 0:
        return  # pre-migration database: migrate() brings it up to date

    applied = _applied_versions(connection)
    known = {migration.version for migration in migrations}
    unknown = sorted(applied - known)
    if unknown:
        raise SchemaCompatibilityError(
            f"database schema references versions {unknown} unknown to "
            "this build"
        )
    expected = expected_latest or max(migration.version for migration in migrations)
    if applied and max(applied) > expected:
        raise SchemaCompatibilityError(
            f"database schema version {max(applied)} is newer than this "
            f"build supports ({expected})"
        )


__all__ = [
    "Migration",
    "SchemaCompatibilityError",
    "check_compatibility",
    "current_schema_version",
    "migrate",
]
