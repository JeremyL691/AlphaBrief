"""M03-W04: renewable single-writer lease and read-only paths.

Covers:
- only the valid lease owner may write and expired ownership cannot
  commit after a takeover (AC-M03-W04-01);
- read-only API calls work without a writer lease and cannot mutate
  storage (AC-M03-W04-02);
- concurrent-process tests serialize or fail clearly without database
  corruption (AC-M03-W04-03).
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import duckdb
import pytest
from alphabrief_api.db.writer_lease import (
    WriterLeaseError,
    acquire_lease,
    assert_write_authorized,
    open_readonly,
    release_lease,
    renew_lease,
    validate_lease,
)


@pytest.fixture
def shared_db(
    tmp_path: Path,
) -> Generator[tuple[Path, duckdb.DuckDBPyConnection], None, None]:
    """One shared database file with a schema applied once."""
    from alphabrief_api.db.schema import apply_schema

    db_path = tmp_path / "shared.db"
    connection = duckdb.connect(str(db_path))
    apply_schema(connection)
    connection.execute(
        "INSERT INTO symbols (symbol, source, data_version, bar_count) "
        "VALUES ('EUR_USD', 'test', 'v1', 0)"
    )
    yield db_path, connection
    connection.close()


# ---------------------------------------------------------------------------
# AC-M03-W04-01: lease ownership and takeover
# ---------------------------------------------------------------------------


def test_only_one_owner_at_a_time(
    shared_db: tuple[Path, duckdb.DuckDBPyConnection],
) -> None:
    db_path, conn = shared_db
    token_a = acquire_lease(conn, owner_id="owner-a", ttl_seconds=60)
    assert token_a is not None
    # A second owner is denied while the first lease is valid.
    assert acquire_lease(conn, owner_id="owner-b", ttl_seconds=60) is None
    assert validate_lease(conn, owner_id="owner-a", token=token_a) is True


def test_expired_lease_can_be_taken_over(
    shared_db: tuple[Path, duckdb.DuckDBPyConnection],
) -> None:
    db_path, conn = shared_db
    token_a = acquire_lease(conn, owner_id="owner-a", ttl_seconds=1)
    assert token_a is not None

    # Force expiry, then owner-b takes over.
    conn.execute(
        "UPDATE writer_lease SET expires_at = "
        "CURRENT_TIMESTAMP - INTERVAL 1 SECOND"
    )
    token_b = acquire_lease(conn, owner_id="owner-b", ttl_seconds=60)
    assert token_b is not None

    # The old owner's token is no longer valid: its writes are denied.
    assert validate_lease(conn, owner_id="owner-a", token=token_a) is False
    with pytest.raises(WriterLeaseError, match="no valid writer lease"):
        assert_write_authorized(conn, owner_id="owner-a", token=token_a)
    # The new owner writes fine.
    assert_write_authorized(conn, owner_id="owner-b", token=token_b)


def test_renew_extends_only_current_owner(
    shared_db: tuple[Path, duckdb.DuckDBPyConnection],
) -> None:
    db_path, conn = shared_db
    token_a = acquire_lease(conn, owner_id="owner-a", ttl_seconds=60)
    assert token_a is not None
    assert (
        renew_lease(conn, owner_id="owner-a", token=token_a, ttl_seconds=120)
        is True
    )
    # A stale token cannot renew.
    assert (
        renew_lease(conn, owner_id="owner-a", token="stale", ttl_seconds=120)
        is False
    )


def test_release_only_by_matching_owner(
    shared_db: tuple[Path, duckdb.DuckDBPyConnection],
) -> None:
    db_path, conn = shared_db
    token_a = acquire_lease(conn, owner_id="owner-a", ttl_seconds=60)
    assert token_a is not None
    assert release_lease(conn, owner_id="owner-a", token="wrong") is False
    assert validate_lease(conn, owner_id="owner-a", token=token_a) is True
    assert release_lease(conn, owner_id="owner-a", token=token_a) is True
    assert validate_lease(conn, owner_id="owner-a", token=token_a) is False


# ---------------------------------------------------------------------------
# AC-M03-W04-02: read-only paths
# ---------------------------------------------------------------------------


def test_readonly_connection_reads_without_lease(tmp_path: Path) -> None:
    """A read-only connection needs no lease and serves reads."""
    from alphabrief_api.db.schema import apply_schema

    db_path = tmp_path / "ro.db"
    writable = duckdb.connect(str(db_path))
    apply_schema(writable)
    writable.execute(
        "INSERT INTO symbols (symbol, source, data_version, bar_count) "
        "VALUES ('EUR_USD', 'test', 'v1', 0)"
    )
    writable.close()  # read-only requires no other configuration on the file

    readonly = open_readonly(db_path)
    try:
        rows = readonly.execute(
            "SELECT symbol FROM symbols WHERE symbol = 'EUR_USD'"
        ).fetchall()
        assert rows == [("EUR_USD",)]
    finally:
        readonly.close()


def test_readonly_connection_cannot_mutate(tmp_path: Path) -> None:
    from alphabrief_api.db.schema import apply_schema

    db_path = tmp_path / "ro.db"
    writable = duckdb.connect(str(db_path))
    apply_schema(writable)
    writable.close()

    readonly = open_readonly(db_path)
    try:
        with pytest.raises(duckdb.Error):
            readonly.execute(
                "INSERT INTO symbols (symbol, source, data_version, bar_count) "
                "VALUES ('GBP_USD', 'test', 'v1', 0)"
            )
    finally:
        readonly.close()


# ---------------------------------------------------------------------------
# AC-M03-W04-03: concurrent processes serialize without corruption
# ---------------------------------------------------------------------------


def test_concurrent_writers_serialize_without_corruption(
    tmp_path: Path,
) -> None:
    """Two connections (simulating two processes) cannot both hold the lease."""
    from alphabrief_api.db.schema import apply_schema

    db_path = tmp_path / "concurrent.db"
    conn_a = duckdb.connect(str(db_path))
    apply_schema(conn_a)
    conn_a.execute(
        "INSERT INTO symbols (symbol, source, data_version, bar_count) "
        "VALUES ('EUR_USD', 'test', 'v1', 0)"
    )
    conn_b = duckdb.connect(str(db_path))
    try:
        token_a = acquire_lease(conn_a, owner_id="proc-a", ttl_seconds=60)
        assert token_a is not None
        # Process B is denied cleanly; no exception storm and no corruption.
        assert acquire_lease(conn_b, owner_id="proc-b", ttl_seconds=60) is None
        assert validate_lease(conn_b, owner_id="proc-b", token="x") is False

        # Both processes can still read the database intact.
        for conn in (conn_a, conn_b):
            row = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()
            assert row is not None and int(row[0]) >= 1
    finally:
        conn_a.close()
        conn_b.close()
