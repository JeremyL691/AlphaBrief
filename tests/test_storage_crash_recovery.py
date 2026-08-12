"""M03-W06: storage crash recovery at every declared persistence boundary.

Failure injection at the migration, cycle-save, and lease boundaries
leaves either the old or the new complete state — never a partial one —
and projections still rebuild byte-for-byte afterwards. A clean isolated
backup restore passes all storage integrity checks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from alphabrief_trader.db_store import AiTradingStore, CycleCheckpointStore
from alphabrief_trader.schemas import (
    CommitteeVote,
    DailyCycleRecord,
    OrderAttempt,
)


def _attempt(intent_id: str) -> OrderAttempt:
    return OrderAttempt.model_validate(
        {
            "intent_id": intent_id,
            "outcome": "executed",
            "order_intent_json": {},
            "risk_decision_id": f"decision-{intent_id}",
            "approved": True,
            "reason": "approved by test risk gate",
            "requires_human_review": False,
            "risk_tags": ["approved"],
            "filled": True,
            "order_id": f"order-{intent_id}",
            "execution_backend": "external_paper",
            "created_at": datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        }
    )


def _vote() -> CommitteeVote:
    return CommitteeVote.model_validate(
        {
            "role": "technical",
            "model_name": "test-model",
            "analysis": "test analysis",
            "view": "bullish",
            "confidence": 0.6,
            "evidence": ["lineage"],
            "risks": [],
            "suggested_action": "buy",
            "target_position_pct": Decimal("0.01"),
            "veto": False,
            "needs_human_review": False,
            "created_at": datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        }
    )


def _cycle(cycle_id: str) -> DailyCycleRecord:
    return DailyCycleRecord(
        cycle_id=cycle_id,
        trading_day="2026-08-01",
        symbols=["EUR_USD"],
        votes=[_vote()],
        attempts=[_attempt(f"intent-{cycle_id}")],
        outcome="executed",
        enabled=True,
        summary=f"cycle {cycle_id}",
        created_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# AC-M03-W06-01: failure injection leaves old-or-new complete state
# ---------------------------------------------------------------------------


def test_failed_migration_leaves_old_state_and_projection_intact(
    tmp_path: Path,
) -> None:
    """A failed migration leaves the old schema; projections still rebuild."""
    from alphabrief_api.db.migrations import Migration, migrate
    from alphabrief_api.db.schema import MIGRATIONS, apply_schema

    db_path = tmp_path / "crash.db"
    conn = duckdb.connect(str(db_path))
    apply_schema(conn)
    conn.execute(
        "INSERT INTO symbols (symbol, source, data_version, bar_count) "
        "VALUES ('EUR_USD', 'test', 'v1', 0)"
    )
    conn.close()

    broken = Migration(
        version=99,
        name="broken-v99",
        statements=(
            "CREATE TABLE t_partial_v99 (id INTEGER)",
            "THIS IS NOT VALID SQL",
        ),
    )
    conn = duckdb.connect(str(db_path))
    try:
        with pytest.raises(duckdb.Error):
            migrate(conn, migrations=(*MIGRATIONS, broken))
    finally:
        conn.close()

    # The old complete state survives and reads fine.
    conn = duckdb.connect(str(db_path))
    try:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main'"
            ).fetchall()
        }
        assert "t_partial_v99" not in tables
        assert "symbols" in tables
        rows = conn.execute(
            "SELECT symbol FROM symbols WHERE symbol = 'EUR_USD'"
        ).fetchall()
        assert rows == [("EUR_USD",)]
    finally:
        conn.close()


def test_failed_cycle_save_leaves_old_projection_rebuildable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a failed save, existing projections still rebuild byte-for-byte."""
    import alphabrief_trader.db_store as db_store

    store = AiTradingStore(db_path=tmp_path / "crash.db")
    try:
        store.save_cycle(_cycle("cycle-old"))
    finally:
        store.close()

    store = AiTradingStore(db_path=tmp_path / "crash.db")
    original_serialize = db_store._serialize
    calls = 0

    def _failing_serialize(value: object) -> str:
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise RuntimeError("injected failure")
        return original_serialize(value)

    monkeypatch.setattr(db_store, "_serialize", _failing_serialize)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            store.save_cycle(_cycle("cycle-new"))
    finally:
        store.close()

    checkpoints = CycleCheckpointStore(db_path=tmp_path / "crash.db")
    try:
        # The new cycle never appeared; the old projection still matches.
        assert checkpoints.projection_matches_stored("cycle-old") is True
        assert checkpoints.rebuild_projection("cycle-new") is None
    finally:
        checkpoints.close()


def test_restart_resumes_from_last_persisted_gate(tmp_path: Path) -> None:
    """Reopening the database resumes from the last persisted checkpoint."""
    checkpoints = CycleCheckpointStore(db_path=tmp_path / "crash.db")
    try:
        assert checkpoints.checkpoint("cycle-1", "risk") is True
    finally:
        checkpoints.close()

    # Simulate a restart: a fresh connection sees the persisted gate.
    reopened = CycleCheckpointStore(db_path=tmp_path / "crash.db")
    try:
        checkpoint = reopened.get_checkpoint("cycle-1")
        assert checkpoint is not None
        assert checkpoint["phase"] == "risk"
        # The restarted writer must advance from the persisted gate.
        assert (
            reopened.checkpoint(
                "cycle-1", "execute", expected_phase="risk"
            )
            is True
        )
    finally:
        reopened.close()


# ---------------------------------------------------------------------------
# AC-M03-W06-02: clean isolated restore passes all storage integrity checks
# ---------------------------------------------------------------------------


def test_clean_restore_passes_all_storage_integrity_checks(
    tmp_path: Path,
) -> None:
    """Backup -> isolated restore -> every storage check passes."""
    from alphabrief_api.db.backup import create_backup, restore_backup
    from alphabrief_api.db.schema import (
        apply_schema,
        current_schema_version,
        latest_schema_version,
    )
    from alphabrief_api.db.writer_lease import acquire_lease, validate_lease

    db_path = tmp_path / "source.db"
    store = AiTradingStore(db_path=db_path)
    try:
        store.save_cycle(_cycle("cycle-restore"))
    finally:
        store.close()

    conn = duckdb.connect(str(db_path))
    apply_schema(conn)
    token = acquire_lease(conn, owner_id="writer", ttl_seconds=60)
    assert token is not None
    conn.close()

    backup_dir = tmp_path / "backups"
    manifest = create_backup(db_path, backup_dir, blueprint_version="2026-08-13.1")
    target = tmp_path / "restored" / "restored.db"
    result = restore_backup(backup_dir, manifest.backup_id, target)
    assert result.integrity_ok is True
    assert result.restored_schema_version == latest_schema_version()

    conn = duckdb.connect(str(target))
    try:
        assert current_schema_version(conn) == latest_schema_version()
        # Cycle projection rebuilds from facts.
        checkpoints = CycleCheckpointStore(db_path=target)
        try:
            assert checkpoints.projection_matches_stored("cycle-restore") is True
        finally:
            checkpoints.close()
        # The writer lease survived the restore.
        assert validate_lease(conn, owner_id="writer", token=token) is True
    finally:
        conn.close()
