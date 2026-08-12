"""M03-W03: rebuildable projections (AC-M03-W02-02).

Current cycle projections rebuild from the append-only fact tables and
equal the stored projection byte-for-byte after normalization; later
ingestion of other cycles never changes an earlier projection.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

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


def test_rebuilt_projection_matches_stored_byte_for_byte(
    tmp_path: Path,
) -> None:
    """AC-M03-W03-02: rebuild equals the stored projection after normalization."""
    store = AiTradingStore(db_path=tmp_path / "ai.db")
    try:
        store.save_cycle(_cycle("cycle-a"))
    finally:
        store.close()

    checkpoints = CycleCheckpointStore(db_path=tmp_path / "ai.db")
    try:
        assert checkpoints.projection_matches_stored("cycle-a") is True
        rebuilt = checkpoints.rebuild_projection("cycle-a")
        assert rebuilt is not None
        assert len(rebuilt["votes"]) == 1
        assert len(rebuilt["attempts"]) == 1
        assert rebuilt["attempts"][0]["intent_id"] == "intent-cycle-a"
    finally:
        checkpoints.close()


def test_projection_stable_after_later_ingestion(tmp_path: Path) -> None:
    """Later cycles never change an earlier cycle's projection."""
    store = AiTradingStore(db_path=tmp_path / "ai.db")
    try:
        store.save_cycle(_cycle("cycle-first"))
    finally:
        store.close()

    checkpoints = CycleCheckpointStore(db_path=tmp_path / "ai.db")
    try:
        before = checkpoints.rebuild_projection("cycle-first")
        assert before is not None
    finally:
        checkpoints.close()

    store = AiTradingStore(db_path=tmp_path / "ai.db")
    try:
        store.save_cycle(_cycle("cycle-second"))
        store.save_cycle(_cycle("cycle-third"))
    finally:
        store.close()

    checkpoints = CycleCheckpointStore(db_path=tmp_path / "ai.db")
    try:
        after = checkpoints.rebuild_projection("cycle-first")
        assert after is not None
        # Byte-for-byte identical after normalization.
        assert (
            checkpoints.projection_matches_stored("cycle-first") is True
        )
        assert after == before
    finally:
        checkpoints.close()


def test_missing_cycle_has_no_projection(tmp_path: Path) -> None:
    checkpoints = CycleCheckpointStore(db_path=tmp_path / "ai.db")
    try:
        assert checkpoints.rebuild_projection("cycle-missing") is None
        assert checkpoints.projection_matches_stored("cycle-missing") is False
    finally:
        checkpoints.close()
