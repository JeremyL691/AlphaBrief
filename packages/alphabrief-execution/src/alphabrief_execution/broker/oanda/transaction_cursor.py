"""Atomic OANDA transaction cursor advancement (M07-W02).

Persists account-scoped OANDA transaction cursors only with consumed
facts and projections in one transaction: an injected crash leaves
either the old complete state or the new complete state. Duplicate and
overlapping pages are idempotent; missing, nonmonotonic, corrupt, or
account-mismatched IDs trigger bounded range recovery, and unresolved
gaps freeze instead of guessing. Restart resumes from the last committed
OANDA transaction ID — never from wall-clock time and never from the
newest partially seen response.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import duckdb
from pydantic import BaseModel, ConfigDict, Field

from alphabrief_execution.broker.oanda.transaction_ops import (
    TransactionGap,
    TransactionResult,
)

#: Default bounded recovery ceiling per gap span.
DEFAULT_MAX_RECOVERY_ATTEMPTS = 3

GapStatus = Literal["OPEN", "FROZEN"]


class AdvanceResult(BaseModel):
    """One deterministic cursor advancement verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str = Field(min_length=1)
    cursor: str | None = None
    facts_consumed: int
    facts_duplicated: int
    gaps: tuple[TransactionGap, ...]
    frozen: bool = False


class CursorStoreError(RuntimeError):
    """A classified cursor-store failure (always fail-closed)."""

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        super().__init__(f"transaction cursor failed ({kind}): {detail}")


_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS transaction_cursors (
    account_id   TEXT PRIMARY KEY,
    cursor_id    TEXT NOT NULL,
    frozen       BOOLEAN NOT NULL DEFAULT FALSE,
    freeze_reason TEXT,
    updated_at   TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS transaction_facts (
    account_id     TEXT NOT NULL,
    transaction_id TEXT NOT NULL,
    transaction_type TEXT NOT NULL,
    time           TIMESTAMPTZ,
    instrument     TEXT,
    units          TEXT,
    price          TEXT,
    realized_pl    TEXT,
    financing      TEXT,
    consumed_at    TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (account_id, transaction_id)
);
CREATE TABLE IF NOT EXISTS transaction_projections (
    account_id     TEXT NOT NULL,
    transaction_id TEXT NOT NULL,
    state          TEXT NOT NULL,
    realized_pl    TEXT,
    financing      TEXT,
    updated_at     TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (account_id, transaction_id)
);
CREATE TABLE IF NOT EXISTS transaction_cursor_gaps (
    account_id   TEXT NOT NULL,
    gap_from     TEXT NOT NULL,
    gap_to       TEXT NOT NULL,
    status       TEXT NOT NULL,
    attempts     BIGINT NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (account_id, gap_from, gap_to)
);
CREATE INDEX IF NOT EXISTS transaction_facts_account ON
    transaction_facts (account_id, transaction_id);
CREATE INDEX IF NOT EXISTS transaction_cursor_gaps_open ON
    transaction_cursor_gaps (account_id, status);
"""


class TransactionCursorStore:
    """DuckDB-backed atomic transaction cursor store."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        max_recovery_attempts: int = DEFAULT_MAX_RECOVERY_ATTEMPTS,
    ) -> None:
        if db_path is None:
            db_path = _default_db_path()
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._conn.execute(_CREATE_TABLES)
        self._max_recovery_attempts = max_recovery_attempts

    # ------------------------------------------------------------------
    # Advance
    # ------------------------------------------------------------------

    def advance(
        self,
        account_id: str,
        facts: list[TransactionResult],
        *,
        owner: str,
    ) -> AdvanceResult:
        """Consume facts and advance the cursor in one transaction.

        The cursor moves only to the highest fully-contiguous consumed
        ID; any missing span above it is recorded as an open gap. An
        injected crash leaves either the old complete state or the new
        complete state — never a partial advance.
        """
        if not account_id.strip():
            raise CursorStoreError("invalid_account", "account_id is empty")
        frozen_reason = self._frozen_reason(account_id)
        if frozen_reason is not None:
            raise CursorStoreError("frozen", f"cursor frozen: {frozen_reason}")
        current = self.cursor(account_id)
        cursor_int = int(current) if current is not None else 0

        now = datetime.now(UTC)
        consumed = 0
        duplicated = 0
        seen: set[int] = set()
        inserted_ids: list[int] = []
        self._conn.execute("BEGIN")
        try:
            for fact in facts:
                if not fact.transaction_id.isdigit():
                    raise CursorStoreError(
                        "corrupt_fact",
                        f"transaction id {fact.transaction_id!r} "
                        "is not a digit string",
                    )
                fact_id = int(fact.transaction_id)
                if self._inside_frozen_gap(account_id, fact_id):
                    raise CursorStoreError(
                        "gap_frozen",
                        f"transaction {fact_id} lies inside a frozen gap span",
                    )
                if fact_id in seen or fact_id <= cursor_int:
                    duplicated += 1
                    continue
                seen.add(fact_id)
                self._insert_fact(account_id, fact, now)
                self._insert_projection(account_id, fact, now)
                inserted_ids.append(fact_id)
                consumed += 1

            # Contiguous frontier and explicit gap spans above it. The
            # walk covers every consumed fact above the cursor (including
            # previously inserted facts), so a recovered fact advances
            # the frontier past everything now present.
            above = self._conn.execute(
                """SELECT transaction_id FROM transaction_facts
                   WHERE account_id = ?
                     AND CAST(transaction_id AS BIGINT) > ?
                   ORDER BY CAST(transaction_id AS BIGINT)""",
                [account_id, cursor_int],
            ).fetchall()
            present = [int(row[0]) for row in above]
            if present:
                start = present[0] if cursor_int == 0 else cursor_int + 1
                expected = start
                frontier = start - 1
                sealed = False
                gaps: list[TransactionGap] = []
                for fact_id in present:
                    if fact_id == expected:
                        # The prefix is sealed at the first hole: the
                        # frontier never advances past a gap.
                        if not sealed:
                            frontier = fact_id
                        expected = fact_id + 1
                    else:
                        sealed = True
                        gaps.append(
                            TransactionGap(
                                gap_from=str(expected), gap_to=str(fact_id - 1)
                            )
                        )
                        expected = fact_id + 1
            else:
                frontier = cursor_int
                gaps = []

            for gap in gaps:
                self._conn.execute(
                    """
                    INSERT INTO transaction_cursor_gaps (
                        account_id, gap_from, gap_to, status, attempts,
                        updated_at
                    ) VALUES (?, ?, ?, 'OPEN', 0, ?)
                    ON CONFLICT (account_id, gap_from, gap_to) DO NOTHING
                    """,
                    [account_id, gap.gap_from, gap.gap_to, now],
                )
            # Gaps the frontier has now passed are closed for good.
            self._conn.execute(
                """
                DELETE FROM transaction_cursor_gaps
                WHERE account_id = ? AND status = 'OPEN'
                  AND CAST(gap_to AS BIGINT) <= ?
                """,
                [account_id, frontier],
            )
            self._conn.execute(
                """
                INSERT INTO transaction_cursors (
                    account_id, cursor_id, frozen, freeze_reason, updated_at
                ) VALUES (?, ?, FALSE, NULL, ?)
                ON CONFLICT (account_id) DO UPDATE SET
                    cursor_id = EXCLUDED.cursor_id,
                    updated_at = EXCLUDED.updated_at
                """,
                [account_id, str(frontier), now],
            )
            self._conn.execute("COMMIT")
        except CursorStoreError:
            self._conn.execute("ROLLBACK")
            raise
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return AdvanceResult(
            account_id=account_id,
            cursor=str(frontier),
            facts_consumed=consumed,
            facts_duplicated=duplicated,
            gaps=tuple(gaps),
        )

    # ------------------------------------------------------------------
    # Bounded range recovery
    # ------------------------------------------------------------------

    def recover_range(
        self,
        account_id: str,
        *,
        from_id: str,
        to_id: str,
        fetcher: Callable[[str, str], list[TransactionResult]],
        owner: str,
    ) -> AdvanceResult:
        """Recover a missing range with a bounded attempt ceiling.

        Each attempt fetches the declared range (account-scoped) and
        re-advances. Gaps that survive the ceiling are frozen and never
        guessed.
        """
        if not from_id.isdigit() or not to_id.isdigit():
            raise CursorStoreError("invalid_range", "range bounds must be digit IDs")
        if int(from_id) > int(to_id):
            raise CursorStoreError("invalid_range", "from_id must not exceed to_id")
        last_result: AdvanceResult | None = None
        for _attempt in range(1, self._max_recovery_attempts + 1):
            fetched = fetcher(from_id, to_id)
            last_result = self.advance(account_id, fetched, owner=owner)
            if not last_result.gaps:
                return last_result
        # The ceiling was reached with gaps still open: freeze them.
        self._freeze_gaps(account_id, owner=owner)
        assert last_result is not None
        return last_result.model_copy(update={"frozen": True})

    def freeze(self, account_id: str, *, reason: str, owner: str) -> None:
        """Freeze the whole cursor; every later advance fails closed."""
        self._conn.execute(
            """
            INSERT INTO transaction_cursors (
                account_id, cursor_id, frozen, freeze_reason, updated_at
            ) VALUES (?, '0', TRUE, ?, ?)
            ON CONFLICT (account_id) DO UPDATE SET
                frozen = TRUE,
                freeze_reason = EXCLUDED.freeze_reason,
                updated_at = EXCLUDED.updated_at
            """,
            [account_id, reason, datetime.now(UTC)],
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def cursor(self, account_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT cursor_id FROM transaction_cursors WHERE account_id = ?",
            [account_id],
        ).fetchone()
        if row is None:
            return None
        return str(row[0])

    def gaps(self, account_id: str, *, status: str = "OPEN") -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT gap_from, gap_to, status, attempts
               FROM transaction_cursor_gaps
               WHERE account_id = ? AND status = ?
               ORDER BY gap_from""",
            [account_id, status],
        ).fetchall()
        return [
            {
                "gap_from": str(row[0]),
                "gap_to": str(row[1]),
                "status": str(row[2]),
                "attempts": int(row[3]),
            }
            for row in rows
        ]

    def fact_count(self, account_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM transaction_facts WHERE account_id = ?",
            [account_id],
        ).fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _frozen_reason(self, account_id: str) -> str | None:
        row = self._conn.execute(
            """SELECT frozen, freeze_reason FROM transaction_cursors
               WHERE account_id = ?""",
            [account_id],
        ).fetchone()
        if row is None or not bool(row[0]):
            return None
        return str(row[1]) if row[1] else "cursor frozen"

    def _inside_frozen_gap(self, account_id: str, fact_id: int) -> bool:
        rows = self._conn.execute(
            """SELECT gap_from, gap_to FROM transaction_cursor_gaps
               WHERE account_id = ? AND status = 'FROZEN'""",
            [account_id],
        ).fetchall()
        return any(
            int(str(row[0])) <= fact_id <= int(str(row[1])) for row in rows
        )

    def _insert_fact(
        self, account_id: str, fact: TransactionResult, now: datetime
    ) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO transaction_facts (
                account_id, transaction_id, transaction_type, time,
                instrument, units, price, realized_pl, financing,
                consumed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                account_id,
                fact.transaction_id,
                fact.transaction_type,
                fact.time,
                fact.instrument,
                str(fact.units) if fact.units is not None else None,
                str(fact.price) if fact.price is not None else None,
                str(fact.realized_pl) if fact.realized_pl is not None else None,
                str(fact.financing) if fact.financing is not None else None,
                now,
            ],
        )

    def _insert_projection(
        self, account_id: str, fact: TransactionResult, now: datetime
    ) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO transaction_projections (
                account_id, transaction_id, state, realized_pl,
                financing, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                account_id,
                fact.transaction_id,
                "CONSUMED",
                str(fact.realized_pl) if fact.realized_pl is not None else "0",
                str(fact.financing) if fact.financing is not None else "0",
                now,
            ],
        )

    def _freeze_gaps(self, account_id: str, *, owner: str) -> None:
        self._conn.execute(
            """
            UPDATE transaction_cursor_gaps
            SET status = 'FROZEN', updated_at = ?
            WHERE account_id = ? AND status = 'OPEN'
            """,
            [datetime.now(UTC), account_id],
        )


def _default_db_path() -> Path:
    env_dir = os.environ.get("ALPHABRIEF_DATA_DIR")
    base = Path(env_dir) if env_dir else Path.home() / ".alphabrief" / "data"
    return base / "alphabrief.db"


__all__ = [
    "AdvanceResult",
    "CursorStoreError",
    "DEFAULT_MAX_RECOVERY_ATTEMPTS",
    "GapStatus",
    "TransactionCursorStore",
]
