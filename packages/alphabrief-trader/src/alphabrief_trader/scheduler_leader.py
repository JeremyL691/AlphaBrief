"""Renewable scheduler leader lease (M11-W02).

Exactly one scheduler process may act as leader at any moment. The
lease is persisted and renewable: only the current holder can renew
before expiry, a lost or expired lease makes every further renewal and
leadership assertion fail, and a competing process can take over only
after expiry. The former leader therefore cannot start another phase or
broker submission before a new leader has taken over.

The compare-and-set semantics use post-commit re-reads because DuckDB
does not report UPDATE rowcounts.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from alphabrief_trader.db_schema import apply_ai_trading_schema

_DEFAULT_TTL_SECONDS = 60


def _default_db_dir() -> Path:
    import os

    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    return Path.home() / ".alphabrief" / "data"


def _default_db_path() -> Path:
    db_dir = _default_db_dir()
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "alphabrief.db"


class SchedulerLeaderLease:
    """Persisted, renewable single-leader lease for the scheduler.

    The store owns no mutable state; every verdict derives from the
    persisted row and the injected clock.
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if db_path is None:
            db_path = _default_db_path()
        self._db_path = Path(db_path)
        self._conn = duckdb.connect(str(self._db_path))
        apply_ai_trading_schema(self._conn)
        self._clock = clock or (lambda: datetime.now(UTC))

    def acquire(self, holder_id: str, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> bool:
        """Become leader; False when an unexpired lease belongs to another."""
        if not holder_id.strip():
            raise ValueError("holder_id must not be blank")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        now = self._clock()
        expires = now + timedelta(seconds=ttl_seconds)
        self._conn.execute("BEGIN")
        try:
            row = self._conn.execute(
                "SELECT holder_id, expires_at FROM scheduler_lease LIMIT 1"
            ).fetchone()
            if row is not None:
                holder = str(row[0])
                expires_at = row[1]
                if expires_at is not None and expires_at > now and holder != holder_id:
                    self._conn.execute("ROLLBACK")
                    return False
            self._conn.execute(
                """
                DELETE FROM scheduler_lease
                """,
            )
            self._conn.execute(
                """
                INSERT INTO scheduler_lease (
                    holder_id, acquired_at, expires_at, version
                )
                VALUES (?, ?, ?, 1)
                """,
                [holder_id, now, expires],
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return True

    def renew(self, holder_id: str, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> bool:
        """Extend the lease; False when lost, expired, or not the holder."""
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        now = self._clock()
        expires = now + timedelta(seconds=ttl_seconds)
        self._conn.execute("BEGIN")
        try:
            self._conn.execute(
                """
                UPDATE scheduler_lease
                SET expires_at = ?, version = version + 1
                WHERE holder_id = ? AND expires_at > ?
                """,
                [expires, holder_id, now],
            )
            # Verify the renewal actually took effect: the expiry must now
            # be the new value (DuckDB reports no UPDATE rowcounts).
            verify = self._conn.execute(
                "SELECT holder_id, expires_at FROM scheduler_lease LIMIT 1"
            ).fetchone()
            if (
                verify is None
                or str(verify[0]) != holder_id
                or verify[1] is None
                or verify[1] != expires
            ):
                self._conn.execute("ROLLBACK")
                return False
            self._conn.execute("COMMIT")
            return True
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def is_leader(self, holder_id: str) -> bool:
        """True when *holder_id* currently holds an unexpired lease."""
        row = self._conn.execute(
            "SELECT holder_id, expires_at FROM scheduler_lease LIMIT 1"
        ).fetchone()
        if row is None:
            return False
        holder = str(row[0])
        expires_at = row[1]
        if holder != holder_id:
            return False
        if expires_at is None:
            return False
        return bool(expires_at > self._clock())

    def leader(self) -> dict[str, Any] | None:
        """Return the current lease row, or ``None`` when free/expired."""
        row = self._conn.execute(
            "SELECT holder_id, acquired_at, expires_at, version "
            "FROM scheduler_lease LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        expires_at = row[2]
        if expires_at is None or expires_at <= self._clock():
            return None
        return {
            "holder_id": str(row[0]),
            "acquired_at": row[1],
            "expires_at": expires_at,
            "version": int(row[3]),
        }

    def release(self, holder_id: str) -> bool:
        """Release the lease; only the current holder may do so."""
        self._conn.execute("BEGIN")
        try:
            row = self._conn.execute(
                "SELECT holder_id FROM scheduler_lease LIMIT 1"
            ).fetchone()
            if row is None or str(row[0]) != holder_id:
                self._conn.execute("ROLLBACK")
                return False
            self._conn.execute("DELETE FROM scheduler_lease")
            self._conn.execute("COMMIT")
            return True
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


__all__ = ["SchedulerLeaderLease"]
