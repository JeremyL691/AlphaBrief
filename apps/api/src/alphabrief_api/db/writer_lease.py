"""Renewable single-writer lease for the shared DuckDB file (M03-W04).

API, scheduler, and one-shot CLI processes all open connections to the
same DuckDB file. The writer lease ensures only one owner may write at a
time (REQ-PLAT-006, REQ-CYCLE-010):

- ``acquire_lease`` takes the lease or fails while another owner's lease
  is valid; an expired lease is taken over by a new owner;
- ``renew_lease`` extends only the current owner's lease (compare-and-
  set on owner+token), so expired ownership can never commit after a
  takeover;
- ``validate_lease`` gates every write path: without a valid lease the
  writer is denied cleanly instead of corrupting the database;
- :func:`open_readonly` returns a structurally read-only connection:
  reads work without any lease and any mutation attempt fails.
"""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

_CREATE_LEASE_TABLE = """
CREATE TABLE IF NOT EXISTS writer_lease (
    owner_id    TEXT PRIMARY KEY,
    token       TEXT NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL
)
"""


class WriterLeaseError(RuntimeError):
    """Raised when a write is attempted without a valid writer lease."""


def _now() -> datetime:
    return datetime.now(UTC)


def _ensure_lease_table(connection: Any) -> None:
    connection.execute(_CREATE_LEASE_TABLE)


def _lease_row(connection: Any) -> dict[str, Any] | None:
    row = connection.execute(
        """SELECT owner_id, token, acquired_at, expires_at
           FROM writer_lease LIMIT 1"""
    ).fetchone()
    if row is None:
        return None
    return {
        "owner_id": str(row[0]),
        "token": str(row[1]),
        "acquired_at": row[2],
        "expires_at": row[3],
    }


def acquire_lease(
    connection: Any,
    *,
    owner_id: str,
    ttl_seconds: int,
) -> str | None:
    """Take the writer lease for *owner_id*; None while another lease is valid.

    An expired lease is taken over atomically by the new owner; the old
    token is replaced so the previous owner can no longer validate.
    """
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")
    _ensure_lease_table(connection)
    token = secrets.token_hex(16)
    now = _now()
    expires = now + timedelta(seconds=ttl_seconds)

    existing = _lease_row(connection)
    if existing is not None:
        expires_at = existing["expires_at"]
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expires_at > now:
            return None  # another owner's lease is still valid

    connection.execute(
        """
        INSERT INTO writer_lease (owner_id, token, acquired_at, expires_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (owner_id) DO UPDATE SET
            token = EXCLUDED.token,
            acquired_at = EXCLUDED.acquired_at,
            expires_at = EXCLUDED.expires_at
        """,
        [owner_id, token, now, expires],
    )
    return token


def renew_lease(
    connection: Any,
    *,
    owner_id: str,
    token: str,
    ttl_seconds: int,
) -> bool:
    """Extend the lease only when owner+token match and it is still valid."""
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")
    _ensure_lease_table(connection)
    expires = _now() + timedelta(seconds=ttl_seconds)
    result = connection.execute(
        """
        UPDATE writer_lease
        SET expires_at = ?
        WHERE owner_id = ? AND token = ? AND expires_at > ?
        """,
        [expires, owner_id, token, _now()],
    )
    row = result.fetchone()
    if row is None:
        return False
    return int(row[0]) > 0


def validate_lease(
    connection: Any,
    *,
    owner_id: str,
    token: str,
) -> bool:
    """Return True only for the unexpired lease of the matching owner."""
    _ensure_lease_table(connection)
    row = connection.execute(
        """SELECT expires_at FROM writer_lease
           WHERE owner_id = ? AND token = ?""",
        [owner_id, token],
    ).fetchone()
    if row is None:
        return False
    expires_at: datetime = (
        row[0]
        if isinstance(row[0], datetime)
        else datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
    )
    return expires_at > _now()


def assert_write_authorized(
    connection: Any,
    *,
    owner_id: str,
    token: str,
) -> None:
    """Raise :class:`WriterLeaseError` unless the write is authorized.

    Every mutation path calls this gate before writing: an expired or
    taken-over lease denies the stale writer cleanly (REQ-CYCLE-010).
    """
    if not validate_lease(connection, owner_id=owner_id, token=token):
        raise WriterLeaseError(
            f"write denied: owner {owner_id!r} holds no valid writer lease"
        )


def release_lease(
    connection: Any,
    *,
    owner_id: str,
    token: str,
) -> bool:
    """Release the lease when owner and token match."""
    _ensure_lease_table(connection)
    result = connection.execute(
        "DELETE FROM writer_lease WHERE owner_id = ? AND token = ?",
        [owner_id, token],
    )
    row = result.fetchone()
    if row is None:
        return False
    return int(row[0]) > 0


def open_readonly(db_path: Path | str) -> duckdb.DuckDBPyConnection:
    """Open a structurally read-only connection to the shared database.

    Read-only API calls work without any writer lease; every mutation
    through this connection fails at the engine level, so a read-only
    path can never mutate storage (AC-M03-W04-02).
    """
    return duckdb.connect(str(db_path), read_only=True)


def default_db_path() -> Path:
    """Return the shared database path resolved from the environment."""
    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    base = Path(env_dir) if env_dir else Path.home() / ".alphabrief" / "data"
    return base / "alphabrief.db"


__all__ = [
    "WriterLeaseError",
    "acquire_lease",
    "assert_write_authorized",
    "default_db_path",
    "open_readonly",
    "release_lease",
    "renew_lease",
    "validate_lease",
]
