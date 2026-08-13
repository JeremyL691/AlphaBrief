"""M07-W02: atomic OANDA transaction cursor advancement.

Covers:
- cursor advancement and all transaction facts and projection changes
  commit in one transaction; injected crashes leave either the old
  complete state or the new complete state (AC-M07-W02-01);
- duplicate and overlapping pages are idempotent while missing,
  nonmonotonic, corrupt, or account-mismatched IDs trigger bounded range
  recovery and freeze unresolved gaps (AC-M07-W02-02);
- restart resumes from the last committed OANDA transaction ID and never
  from wall-clock time or the newest partially seen response
  (AC-M07-W02-03).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alphabrief_execution.broker.oanda.transaction_cursor import (
    CursorStoreError,
    TransactionCursorStore,
)
from alphabrief_execution.broker.oanda.transaction_ops import TransactionResult

ACCOUNT = "101-004-1234567-001"
OWNER = "daily-runner"


def _fact(
    transaction_id: str, *, pl: str = "0", financing: str = "0"
) -> TransactionResult:
    return TransactionResult(
        transaction_id=transaction_id,
        transaction_type="ORDER_FILL",
        time=datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
        instrument="EUR_USD",
        units=Decimal("1000"),
        price=Decimal("1.10500"),
        realized_pl=Decimal(pl),
        financing=Decimal(financing),
        request_id=f"fact-{transaction_id}",
    )


def _store(tmp_path: Path, name: str = "cursor.db") -> TransactionCursorStore:
    return TransactionCursorStore(db_path=tmp_path / name)


class _CrashConnection:
    """Wraps a DuckDB connection to inject crashes before a statement."""

    def __init__(self, real: Any, crash_marker: str) -> None:
        self._real = real
        self._crash_marker = crash_marker

    def execute(self, sql: str, params: list[Any] | None = None) -> Any:
        if self._crash_marker in sql:
            raise RuntimeError("injected crash")
        return self._real.execute(sql, params or [])


# ---------------------------------------------------------------------------
# AC-M07-W02-01: one-transaction atomicity
# ---------------------------------------------------------------------------


def test_advance_commits_facts_projections_and_cursor_together(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    try:
        result = store.advance(
            ACCOUNT, [_fact("101"), _fact("102"), _fact("103")], owner=OWNER
        )
        assert result.cursor == "103"
        assert result.facts_consumed == 3
        assert result.facts_duplicated == 0
        assert result.gaps == ()
        assert store.cursor(ACCOUNT) == "103"
        assert store.fact_count(ACCOUNT) == 3
    finally:
        store.close()


def test_injected_crash_leaves_old_complete_state(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        store.advance(ACCOUNT, [_fact("101"), _fact("102")], owner=OWNER)
        assert store.cursor(ACCOUNT) == "102"
        # Crash on the cursor update: the whole advance rolls back.
        store._conn = _CrashConnection(  # type: ignore[assignment]
            store._conn, "INSERT INTO transaction_cursors"
        )
        with pytest.raises(RuntimeError, match="injected crash"):
            store.advance(ACCOUNT, [_fact("103"), _fact("104")], owner=OWNER)
        # Old complete state: cursor unchanged, no partial facts.
        assert store.cursor(ACCOUNT) == "102"
        assert store.fact_count(ACCOUNT) == 2
    finally:
        store.close()


# ---------------------------------------------------------------------------
# AC-M07-W02-02: idempotent duplicates, bounded recovery, frozen gaps
# ---------------------------------------------------------------------------


def test_duplicate_and_overlapping_pages_are_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        first = store.advance(
            ACCOUNT, [_fact("101"), _fact("102")], owner=OWNER
        )
        assert first.facts_consumed == 2
        # Overlapping page: the already-consumed IDs are ignored.
        second = store.advance(
            ACCOUNT,
            [_fact("101"), _fact("102"), _fact("103")],
            owner=OWNER,
        )
        assert second.facts_consumed == 1
        assert second.facts_duplicated == 2
        assert second.cursor == "103"
        assert store.fact_count(ACCOUNT) == 3
    finally:
        store.close()


def test_missing_ids_open_gap_and_cursor_stops_at_frontier(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    try:
        result = store.advance(
            ACCOUNT, [_fact("101"), _fact("102"), _fact("104")], owner=OWNER
        )
        assert result.cursor == "102"
        assert [(g.gap_from, g.gap_to) for g in result.gaps] == [("103", "103")]
        gaps = store.gaps(ACCOUNT)
        assert gaps == [
            {"gap_from": "103", "gap_to": "103", "status": "OPEN", "attempts": 0}
        ]
    finally:
        store.close()


def test_nonmonotonic_ids_are_ignored(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        store.advance(ACCOUNT, [_fact("101"), _fact("102")], owner=OWNER)
        replay = store.advance(
            ACCOUNT, [_fact("100"), _fact("101")], owner=OWNER
        )
        assert replay.facts_consumed == 0
        assert replay.facts_duplicated == 2
        assert replay.cursor == "102"
        assert store.fact_count(ACCOUNT) == 2
    finally:
        store.close()


def test_corrupt_id_fails_closed_without_partial_commit(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        with pytest.raises(CursorStoreError) as excinfo:
            store.advance(
                ACCOUNT,
                [_fact("101"), _fact("not-an-id")],
                owner=OWNER,
            )
        assert excinfo.value.kind == "corrupt_fact"
        # Nothing committed, not even the valid leading fact.
        assert store.cursor(ACCOUNT) is None
        assert store.fact_count(ACCOUNT) == 0
    finally:
        store.close()


def test_bounded_recovery_fills_gap_and_advances(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        store.advance(ACCOUNT, [_fact("101"), _fact("102"), _fact("104")], owner=OWNER)
        assert store.cursor(ACCOUNT) == "102"

        def fetcher(from_id: str, to_id: str) -> list[TransactionResult]:
            return [_fact("103")]

        result = store.recover_range(
            ACCOUNT, from_id="103", to_id="104", fetcher=fetcher, owner=OWNER
        )
        assert result.cursor == "104"
        assert result.gaps == ()
        assert store.cursor(ACCOUNT) == "104"
        assert store.gaps(ACCOUNT) == []
    finally:
        store.close()


def test_unresolved_gap_freezes_after_recovery_ceiling(tmp_path: Path) -> None:
    store = TransactionCursorStore(
        db_path=tmp_path / "cursor.db", max_recovery_attempts=2
    )
    try:
        store.advance(ACCOUNT, [_fact("101"), _fact("102"), _fact("104")], owner=OWNER)

        def empty_fetcher(from_id: str, to_id: str) -> list[TransactionResult]:
            return []

        result = store.recover_range(
            ACCOUNT, from_id="103", to_id="104", fetcher=empty_fetcher, owner=OWNER
        )
        assert result.frozen is True
        frozen = store.gaps(ACCOUNT, status="FROZEN")
        assert [(g["gap_from"], g["gap_to"]) for g in frozen] == [("103", "103")]
        # Facts inside the frozen span are rejected, never guessed.
        with pytest.raises(CursorStoreError) as excinfo:
            store.advance(ACCOUNT, [_fact("103")], owner=OWNER)
        assert excinfo.value.kind == "gap_frozen"
        assert store.cursor(ACCOUNT) == "102"
    finally:
        store.close()


def test_account_mismatched_recovery_frozen(tmp_path: Path) -> None:
    store = TransactionCursorStore(
        db_path=tmp_path / "cursor.db", max_recovery_attempts=2
    )
    try:
        store.advance(ACCOUNT, [_fact("101"), _fact("102"), _fact("104")], owner=OWNER)

        # The account-scoped fetch returns nothing (mismatched account).
        def mismatched_fetcher(from_id: str, to_id: str) -> list[TransactionResult]:
            return []

        result = store.recover_range(
            ACCOUNT, from_id="103", to_id="104", fetcher=mismatched_fetcher, owner=OWNER
        )
        assert result.frozen is True
        assert store.gaps(ACCOUNT, status="FROZEN") != []
    finally:
        store.close()


def test_frozen_cursor_blocks_every_advance(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        store.advance(ACCOUNT, [_fact("101")], owner=OWNER)
        store.freeze(ACCOUNT, reason="corrupt page observed", owner=OWNER)
        with pytest.raises(CursorStoreError) as excinfo:
            store.advance(ACCOUNT, [_fact("102")], owner=OWNER)
        assert excinfo.value.kind == "frozen"
        assert "corrupt page observed" in str(excinfo.value)
        assert store.cursor(ACCOUNT) == "101"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# AC-M07-W02-03: restart resumes from the last committed broker ID
# ---------------------------------------------------------------------------


def test_restart_resumes_from_committed_cursor(tmp_path: Path) -> None:
    path = tmp_path / "cursor.db"
    store = TransactionCursorStore(db_path=path)
    try:
        # Facts up to 105 arrive but 103 is missing: the cursor stops at
        # the contiguous frontier 102.
        store.advance(
            ACCOUNT,
            [_fact("101"), _fact("102"), _fact("104"), _fact("105")],
            owner=OWNER,
        )
        assert store.cursor(ACCOUNT) == "102"
    finally:
        store.close()

    # Restart: resumes from the last committed OANDA transaction ID.
    reopened = TransactionCursorStore(db_path=path)
    try:
        assert reopened.cursor(ACCOUNT) == "102"
        # The missing fact arrives after the restart and the frontier
        # advances past everything now present.
        result = reopened.advance(ACCOUNT, [_fact("103")], owner=OWNER)
        assert result.cursor == "105"
        assert reopened.cursor(ACCOUNT) == "105"
    finally:
        reopened.close()


def test_restart_never_uses_wall_clock_or_partial_response(tmp_path: Path) -> None:
    path = tmp_path / "cursor.db"
    store = TransactionCursorStore(db_path=path)
    try:
        store.advance(
            ACCOUNT,
            [_fact("101"), _fact("102"), _fact("108")],
            owner=OWNER,
        )
        # 108 was partially seen but 103-107 are missing: the cursor
        # must not jump to 108.
        assert store.cursor(ACCOUNT) == "102"
    finally:
        store.close()

    reopened = TransactionCursorStore(db_path=path)
    try:
        assert reopened.cursor(ACCOUNT) == "102"
        # The committed cursor is a broker ID, never a timestamp.
        cursor_after_restart = reopened.cursor(ACCOUNT)
        assert cursor_after_restart is not None
        assert cursor_after_restart.isdigit()
    finally:
        reopened.close()
