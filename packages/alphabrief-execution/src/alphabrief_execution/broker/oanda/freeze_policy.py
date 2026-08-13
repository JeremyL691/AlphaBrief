"""Evidence-backed exposure freeze and unfreeze (M07-W05).

Freezes new exposure on unexplained reconciliation or cursor failures
with one deduplicated durable record before any new-exposure submit.
Unfreeze is permitted only after a fresh successful full sync, zero
blocking diffs, matching cursor and projection hashes, resolved alerts,
and an immutable reason and evidence record. Repeated freeze and
unfreeze commands are idempotent, and no API, CLI, scheduler, model, or
fallback path can clear a freeze by omission or confirmation prompt —
``unfreeze`` with explicit evidence is the only way out.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import duckdb
from pydantic import BaseModel, ConfigDict, Field

FreezeReason = Literal[
    "blocking_diff",
    "unresolved_gap",
    "stale_snapshot",
    "resync_failed",
    "corrupt_projection",
    "cursor_failure",
]


class FreezeActiveError(RuntimeError):
    """Raised when a new-exposure submit is attempted while frozen."""


class UnfreezeDeniedError(RuntimeError):
    """Raised when the unfreeze policy checks do not all hold."""

    def __init__(self, failing: list[str]) -> None:
        self.failing = failing
        super().__init__("unfreeze denied: " + "; ".join(failing))


class FreezeRecord(BaseModel):
    """One durable freeze record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    freeze_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    reason: FreezeReason
    detail: str
    status: str  # FROZEN or UNFROZEN
    evidence_refs: tuple[str, ...] = ()
    created_at: datetime


_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS exposure_freezes (
    freeze_id    TEXT PRIMARY KEY,
    account_id   TEXT NOT NULL,
    reason       TEXT NOT NULL,
    detail       TEXT NOT NULL,
    status       TEXT NOT NULL,
    evidence_refs TEXT,
    created_at   TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS exposure_freezes_active ON
    exposure_freezes (account_id, status);
CREATE TABLE IF NOT EXISTS exposure_unfreezes (
    event_id       BIGINT PRIMARY KEY,
    freeze_id      TEXT NOT NULL,
    account_id     TEXT NOT NULL,
    reason         TEXT NOT NULL,
    fresh_sync_ok  BOOLEAN NOT NULL,
    blocking_diffs BIGINT NOT NULL,
    cursor_match   BOOLEAN NOT NULL,
    projection_hash_match BOOLEAN NOT NULL,
    resolved_alerts BOOLEAN NOT NULL,
    unfrozen_at    TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS exposure_unfreezes_account ON
    exposure_unfreezes (account_id);
"""


class ExposureFreezeStore:
    """DuckDB-backed freeze store with deduplicated, evidence-only clears."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = _default_db_path()
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._conn.execute(_CREATE_TABLES)

    # ------------------------------------------------------------------
    # Freeze
    # ------------------------------------------------------------------

    def freeze_new_exposure(
        self,
        account_id: str,
        *,
        reason: FreezeReason,
        detail: str,
        evidence_refs: tuple[str, ...] = (),
    ) -> str:
        """Record one deduplicated durable freeze.

        An identical active freeze already on file is returned as-is;
        the freeze count never grows from repeated alarms.
        """
        if not account_id.strip():
            raise ValueError("account_id must not be empty")
        existing = self._active_freeze(account_id, reason, detail)
        if existing is not None:
            return existing["freeze_id"]
        freeze_id = self._next_freeze_id(account_id, reason, detail)
        self._conn.execute(
            """
            INSERT OR IGNORE INTO exposure_freezes (
                freeze_id, account_id, reason, detail, status,
                evidence_refs, created_at
            ) VALUES (?, ?, ?, ?, 'FROZEN', ?, ?)
            """,
            [
                freeze_id,
                account_id,
                reason,
                detail,
                ",".join(evidence_refs),
                datetime.now(UTC),
            ],
        )
        return freeze_id

    def ensure_new_exposure_allowed(self, account_id: str) -> None:
        """Raise when any active freeze blocks a new-exposure submit."""
        active = self.active_freezes(account_id)
        if active:
            freeze = active[0]
            raise FreezeActiveError(
                f"new exposure frozen for {account_id}: "
                f"{freeze['reason']} ({freeze['detail']})"
            )

    def active_freezes(self, account_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT freeze_id, reason, detail, evidence_refs, created_at
               FROM exposure_freezes
               WHERE account_id = ? AND status = 'FROZEN'
               ORDER BY created_at""",
            [account_id],
        ).fetchall()
        return [
            {
                "freeze_id": str(row[0]),
                "reason": str(row[1]),
                "detail": str(row[2]),
                "evidence_refs": (
                    tuple(str(row[3]).split(",")) if row[3] else ()
                ),
                "created_at": str(row[4]),
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Unfreeze (evidence-backed only)
    # ------------------------------------------------------------------

    def unfreeze(
        self,
        account_id: str,
        *,
        fresh_sync_ok: bool = False,
        blocking_diffs: int | None = None,
        cursor_match: bool = False,
        projection_hash_match: bool = False,
        resolved_alerts: bool = False,
        reason: str,
    ) -> None:
        """Unfreeze only when every policy check holds with evidence.

        Every check defaults to the denying value, so an omitted check
        can never clear a freeze. Idempotent: with no active freeze the
        call is a no-op and writes no history.
        """
        failing: list[str] = []
        if not fresh_sync_ok:
            failing.append("fresh full sync not completed")
        if blocking_diffs is None:
            failing.append("blocking diffs not verified")
        elif blocking_diffs != 0:
            failing.append(f"{blocking_diffs} blocking diffs remain")
        if not cursor_match:
            failing.append("cursor does not match")
        if not projection_hash_match:
            failing.append("projection hash does not match")
        if not resolved_alerts:
            failing.append("alerts not resolved")
        if failing:
            raise UnfreezeDeniedError(failing)
        # A successful check above guarantees a numeric blocking-diff
        # count, and any nonzero count already denied the unfreeze.
        assert blocking_diffs is not None and blocking_diffs == 0
        active = self.active_freezes(account_id)
        if not active:
            return  # idempotent: nothing frozen to unfreeze
        now = datetime.now(UTC)
        for freeze in active:
            self._conn.execute("BEGIN")
            try:
                updated = self._conn.execute(
                    """
                    UPDATE exposure_freezes
                    SET status = 'UNFROZEN'
                    WHERE freeze_id = ? AND status = 'FROZEN'
                    """,
                    [freeze["freeze_id"]],
                ).fetchone()
                if updated is None or updated[0] == 0:
                    self._conn.execute("ROLLBACK")
                    continue
                self._append_unfreeze(
                    freeze["freeze_id"],
                    account_id,
                    reason=reason,
                    fresh_sync_ok=fresh_sync_ok,
                    blocking_diffs=blocking_diffs,
                    cursor_match=cursor_match,
                    projection_hash_match=projection_hash_match,
                    resolved_alerts=resolved_alerts,
                    now=now,
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def unfreeze_history(self, account_id: str) -> list[dict[str, Any]]:
        """Immutable append-only unfreeze evidence."""
        rows = self._conn.execute(
            """SELECT event_id, freeze_id, reason, fresh_sync_ok,
                      blocking_diffs, cursor_match, projection_hash_match,
                      resolved_alerts, unfrozen_at
               FROM exposure_unfreezes
               WHERE account_id = ?
               ORDER BY event_id""",
            [account_id],
        ).fetchall()
        return [
            {
                "event_id": int(row[0]),
                "freeze_id": str(row[1]),
                "reason": str(row[2]),
                "fresh_sync_ok": bool(row[3]),
                "blocking_diffs": int(row[4]),
                "cursor_match": bool(row[5]),
                "projection_hash_match": bool(row[6]),
                "resolved_alerts": bool(row[7]),
                "unfrozen_at": str(row[8]),
            }
            for row in rows
        ]

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _active_freeze(
        self, account_id: str, reason: str, detail: str
    ) -> dict[str, str] | None:
        row = self._conn.execute(
            """SELECT freeze_id FROM exposure_freezes
               WHERE account_id = ? AND reason = ? AND detail = ?
                 AND status = 'FROZEN'""",
            [account_id, reason, detail],
        ).fetchone()
        if row is None:
            return None
        return {"freeze_id": str(row[0])}

    def _next_freeze_id(
        self, account_id: str, reason: str, detail: str
    ) -> str:
        """Deterministic unique id for one distinct alarm occurrence.

        The id combines the account, the reason, a non-reversible digest
        of the detail, and the occurrence sequence. Different details
        never collide on the primary key, and a repeated alarm after an
        unfreeze creates a fresh durable freeze instead of being
        swallowed by ``INSERT OR IGNORE``.
        """
        row = self._conn.execute(
            """SELECT COUNT(*) FROM exposure_freezes
               WHERE account_id = ? AND reason = ?""",
            [account_id, reason],
        ).fetchone()
        seq = int(row[0]) + 1 if row else 1
        digest = hashlib.sha256(detail.encode("utf-8")).hexdigest()[:12]
        return f"freeze-{account_id}-{reason}-{digest}-{seq}"

    def _append_unfreeze(
        self,
        freeze_id: str,
        account_id: str,
        *,
        reason: str,
        fresh_sync_ok: bool,
        blocking_diffs: int,
        cursor_match: bool,
        projection_hash_match: bool,
        resolved_alerts: bool,
        now: datetime,
    ) -> None:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(event_id), 0) + 1 FROM exposure_unfreezes"
        ).fetchone()
        event_id = int(row[0]) if row else 1
        self._conn.execute(
            """
            INSERT INTO exposure_unfreezes (
                event_id, freeze_id, account_id, reason, fresh_sync_ok,
                blocking_diffs, cursor_match, projection_hash_match,
                resolved_alerts, unfrozen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                event_id,
                freeze_id,
                account_id,
                reason,
                fresh_sync_ok,
                blocking_diffs,
                cursor_match,
                projection_hash_match,
                resolved_alerts,
                now,
            ],
        )


def _default_db_path() -> Path:
    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    base = Path(env_dir) if env_dir else Path.home() / ".alphabrief" / "data"
    return base / "alphabrief.db"


__all__ = [
    "ExposureFreezeStore",
    "FreezeActiveError",
    "FreezeReason",
    "FreezeRecord",
    "UnfreezeDeniedError",
]
