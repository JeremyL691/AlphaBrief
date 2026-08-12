"""M03-W03: atomic cycle checkpoints and compare-and-set (AC-01, AC-03).

Covers:
- every cycle transition and its referenced outputs commit together or
  not at all under failure injection (AC-M03-W03-01);
- compare-and-set rejects stale writers and illegal phase transitions
  (AC-M03-W03-03).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_trader.db_store import (
    CYCLE_PHASE_ORDER,
    AiTradingStore,
    CycleCheckpointStore,
)
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


def _cycle(cycle_id: str = "cycle-1") -> DailyCycleRecord:
    return DailyCycleRecord(
        cycle_id=cycle_id,
        trading_day="2026-08-01",
        symbols=["EUR_USD"],
        votes=[_vote()],
        attempts=[_attempt("intent-1")],
        outcome="executed",
        enabled=True,
        summary="test cycle",
        created_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# AC-M03-W03-01: atomic cycle persistence under failure injection
# ---------------------------------------------------------------------------


def test_cycle_facts_commit_together(tmp_path: Path) -> None:
    """A successful save persists the cycle, votes, and attempts."""
    store = AiTradingStore(db_path=tmp_path / "ai.db")
    try:
        store.save_cycle(_cycle("cycle-ok"))
        cycle = store.get_cycle(cycle_id="cycle-ok")
        assert cycle is not None
        assert len(cycle["votes"]) == 1
        assert len(cycle["attempts"]) == 1
    finally:
        store.close()


def test_failed_cycle_save_rolls_back_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure mid-save leaves no cycle, vote, or attempt behind."""
    import alphabrief_trader.db_store as db_store

    store = AiTradingStore(db_path=tmp_path / "ai.db")
    original_serialize = db_store._serialize
    calls = 0

    def _failing_serialize(value: object) -> str:
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise RuntimeError("injected vote serialization failure")
        return original_serialize(value)

    monkeypatch.setattr(db_store, "_serialize", _failing_serialize)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            store.save_cycle(_cycle("cycle-fail"))
    finally:
        store.close()

    reopened = AiTradingStore(db_path=tmp_path / "ai.db")
    try:
        assert reopened.get_cycle(cycle_id="cycle-fail") is None
        assert reopened.list_cycles(limit=10) == []
    finally:
        reopened.close()


# ---------------------------------------------------------------------------
# AC-M03-W03-03: compare-and-set checkpoint semantics
# ---------------------------------------------------------------------------


def test_checkpoint_advances_monotonically(tmp_path: Path) -> None:
    store = CycleCheckpointStore(db_path=tmp_path / "cp.db")
    try:
        for phase in CYCLE_PHASE_ORDER:
            assert store.checkpoint(
                "cycle-1",
                phase,
                output_ids={"fact": f"fact-{phase}"},
            ) is True
        checkpoint = store.get_checkpoint("cycle-1")
        assert checkpoint is not None
        assert checkpoint["phase"] == "record"
        assert checkpoint["output_ids"] == {"fact": "fact-record"}
    finally:
        store.close()


def test_stale_writer_is_rejected(tmp_path: Path) -> None:
    store = CycleCheckpointStore(db_path=tmp_path / "cp.db")
    try:
        assert store.checkpoint("cycle-1", "risk") is True
        # A writer that expects "committee" is stale: the stored phase is
        # "risk", so the advance is rejected and the checkpoint is intact.
        assert (
            store.checkpoint(
                "cycle-1", "execute", expected_phase="committee"
            )
            is False
        )
        checkpoint = store.get_checkpoint("cycle-1")
        assert checkpoint is not None
        assert checkpoint["phase"] == "risk"
    finally:
        store.close()


def test_matching_expected_phase_advances(tmp_path: Path) -> None:
    store = CycleCheckpointStore(db_path=tmp_path / "cp.db")
    try:
        assert store.checkpoint("cycle-1", "risk") is True
        assert (
            store.checkpoint(
                "cycle-1", "execute", expected_phase="risk"
            )
            is True
        )
        checkpoint = store.get_checkpoint("cycle-1")
        assert checkpoint is not None
        assert checkpoint["phase"] == "execute"
    finally:
        store.close()


def test_non_monotonic_transition_is_rejected(tmp_path: Path) -> None:
    store = CycleCheckpointStore(db_path=tmp_path / "cp.db")
    try:
        assert store.checkpoint("cycle-1", "execute") is True
        assert store.checkpoint("cycle-1", "committee") is False
        checkpoint = store.get_checkpoint("cycle-1")
        assert checkpoint is not None
        assert checkpoint["phase"] == "execute"
    finally:
        store.close()


def test_unknown_phase_is_rejected(tmp_path: Path) -> None:
    store = CycleCheckpointStore(db_path=tmp_path / "cp.db")
    try:
        with pytest.raises(ValueError, match="unknown cycle phase"):
            store.checkpoint("cycle-1", "launch")
    finally:
        store.close()
