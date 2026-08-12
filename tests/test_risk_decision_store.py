"""M03-W02: OrderIntent and RiskDecision facts are append-only and UTC.

AI trading cycles persist every OrderIntent / RiskDecision attempt as an
immutable, UTC-stamped fact: cycles, votes, and attempts are appended by
their IDs and later cycles never mutate earlier rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from alphabrief_trader.db_store import AiTradingStore
from alphabrief_trader.schemas import (
    CommitteeVote,
    DailyCycleRecord,
    OrderAttempt,
)


def _attempt(intent_id: str = "intent-1") -> OrderAttempt:
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
        summary="test cycle",
        created_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )


def test_cycle_facts_are_append_only_and_utc(tmp_path: Path) -> None:
    """Every cycle is a distinct fact; later cycles never overwrite."""
    store = AiTradingStore(db_path=tmp_path / "ai.db")
    try:
        store.save_cycle(_cycle("cycle-1"))
        store.save_cycle(_cycle("cycle-2"))

        first = store.get_cycle(cycle_id="cycle-1")
        second = store.get_cycle(cycle_id="cycle-2")
        assert first is not None and second is not None
        assert first["cycle_id"] == "cycle-1"
        assert second["cycle_id"] == "cycle-2"
        # Order attempts (OrderIntent + RiskDecision facts) are preserved.
        assert len(first["attempts"]) == 1
        assert first["attempts"][0]["intent_id"] == "intent-cycle-1"
        assert second["attempts"][0]["intent_id"] == "intent-cycle-2"
    finally:
        store.close()


def test_attempt_facts_are_utc_stamped(tmp_path: Path) -> None:
    store = AiTradingStore(db_path=tmp_path / "ai.db")
    try:
        store.save_cycle(_cycle("cycle-utc"))
        latest = store.get_latest_cycle()
        assert latest is not None
        for attempt in latest["attempts"]:
            # Attempt timestamps are UTC ISO-8601 strings in the cycle JSON.
            created_at = attempt["created_at"]
            assert created_at.endswith("Z") or "+00:00" in created_at
    finally:
        store.close()
