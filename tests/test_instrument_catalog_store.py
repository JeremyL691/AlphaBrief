"""M04-W03: versioned instrument catalog snapshots and diffs.

Covers:
- a catalog snapshot, its instrument rows, content hash, account
  correlation, fetched_at UTC timestamp, and diff publish atomically or
  not at all under failure injection (AC-M04-W03-01);
- replaying identical content is idempotent while additions, removals,
  and metadata changes create queryable history without overwriting
  prior versions (AC-M04-W03-02);
- the current projection rebuilds from immutable catalog facts and
  exactly matches the latest complete snapshot count and hashes
  (AC-M04-W03-03).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_api.db.instrument_catalog import InstrumentCatalogStore
from alphabrief_execution.broker.oanda.instruments import (
    InstrumentCatalogSnapshot,
    InstrumentMetadata,
)


def _instrument(name: str, margin_rate: str = "0.05") -> InstrumentMetadata:
    return InstrumentMetadata(
        name=name,
        display_name=name.replace("_", "/"),
        raw_type="CURRENCY",
        display_precision=5,
        trade_units_precision=0,
        minimum_trade_size=Decimal("1"),
        maximum_order_units=Decimal("0"),
        maximum_position_size=Decimal("0"),
        margin_rate=Decimal(margin_rate),
        pip_location=-4,
    )


def _snapshot(
    *names: str,
    account: str = "acct-hash",
    margin_rate: str | None = None,
) -> InstrumentCatalogSnapshot:
    return InstrumentCatalogSnapshot(
        account_id_hash=account,
        fetched_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        instruments=tuple(
            _instrument(name, margin_rate or "0.05") for name in names
        ),
    )


# ---------------------------------------------------------------------------
# AC-M04-W03-01: atomic publication
# ---------------------------------------------------------------------------


def test_snapshot_publishes_atomically(tmp_path: Path) -> None:
    store = InstrumentCatalogStore(db_path=tmp_path / "cat.db")
    try:
        snapshot_id = store.publish_snapshot(_snapshot("EUR_USD", "GBP_USD"))
        rows = store.list_snapshots()
        assert len(rows) == 1
        assert rows[0]["snapshot_id"] == snapshot_id
        assert rows[0]["account_id_hash"] == "acct-hash"
        assert rows[0]["content_hash"]
        assert rows[0]["fetched_at"]
        projection = store.current_projection()
        assert projection is not None
        assert {i.name for i in projection.instruments} == {"EUR_USD", "GBP_USD"}
    finally:
        store.close()


def test_failed_publish_rolls_back_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure mid-publish leaves no snapshot or instrument rows."""
    store = InstrumentCatalogStore(db_path=tmp_path / "cat.db")
    original_dump = InstrumentMetadata.model_dump_json
    calls = 0

    def _failing_dump(self: InstrumentMetadata) -> str:
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise RuntimeError("injected row serialization failure")
        return original_dump(self)

    monkeypatch.setattr(InstrumentMetadata, "model_dump_json", _failing_dump)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            store.publish_snapshot(_snapshot("EUR_USD", "GBP_USD", "USD_JPY"))
    finally:
        store.close()

    reopened = InstrumentCatalogStore(db_path=tmp_path / "cat.db")
    try:
        assert reopened.list_snapshots() == []
        assert reopened.current_projection() is None
    finally:
        reopened.close()


# ---------------------------------------------------------------------------
# AC-M04-W03-02: idempotent replay and queryable history
# ---------------------------------------------------------------------------


def test_replaying_identical_content_is_idempotent(tmp_path: Path) -> None:
    store = InstrumentCatalogStore(db_path=tmp_path / "cat.db")
    try:
        first = store.publish_snapshot(_snapshot("EUR_USD"))
        second = store.publish_snapshot(_snapshot("EUR_USD"))
        assert first == second
        assert len(store.list_snapshots()) == 1
    finally:
        store.close()


def test_additions_and_removals_create_queryable_history(tmp_path: Path) -> None:
    store = InstrumentCatalogStore(db_path=tmp_path / "cat.db")
    try:
        store.publish_snapshot(_snapshot("EUR_USD", "GBP_USD"))
        second_id = store.publish_snapshot(_snapshot("EUR_USD", "USD_JPY"))

        history = store.list_snapshots()
        assert len(history) == 2

        diff = store.snapshot_diff(second_id)
        assert diff is not None
        assert diff.added == ("USD_JPY",)
        assert diff.removed == ("GBP_USD",)
        assert diff.metadata_changed == ()
    finally:
        store.close()


def test_metadata_changes_are_recorded_not_overwritten(tmp_path: Path) -> None:
    store = InstrumentCatalogStore(db_path=tmp_path / "cat.db")
    try:
        store.publish_snapshot(_snapshot("EUR_USD", margin_rate="0.05"))
        second_id = store.publish_snapshot(_snapshot("EUR_USD", margin_rate="0.10"))

        diff = store.snapshot_diff(second_id)
        assert diff is not None
        assert diff.metadata_changed == ("EUR_USD",)
        # Both versions remain queryable in history.
        assert len(store.list_snapshots()) == 2
    finally:
        store.close()


# ---------------------------------------------------------------------------
# AC-M04-W03-03: projection rebuild matches the latest snapshot
# ---------------------------------------------------------------------------


def test_projection_rebuilds_and_matches_latest_snapshot(tmp_path: Path) -> None:
    store = InstrumentCatalogStore(db_path=tmp_path / "cat.db")
    try:
        store.publish_snapshot(_snapshot("EUR_USD", "GBP_USD"))
        store.publish_snapshot(_snapshot("EUR_USD", "USD_JPY", "XAU_USD"))

        projection = store.current_projection()
        assert projection is not None
        assert {i.name for i in projection.instruments} == {
            "EUR_USD",
            "USD_JPY",
            "XAU_USD",
        }
        assert store.projection_matches_latest_snapshot() is True
    finally:
        store.close()
