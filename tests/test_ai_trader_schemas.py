"""Tests for alphabrief-trader schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alphabrief_trader.schemas import (
    CommitteeInput,
    CommitteeVote,
    CycleOutcome,
    DailyCycleRecord,
    MarketSnapshot,
    OrderAttempt,
    TradePlan,
)
from pydantic import ValidationError


def _snapshot(**overrides: object) -> MarketSnapshot:
    defaults: dict[str, object] = {
        "symbol": "SPY",
        "reference_price": Decimal("100"),
        "data_version": "test-v1",
        "captured_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return MarketSnapshot.model_validate(defaults)


def _vote(**overrides: object) -> CommitteeVote:
    defaults: dict[str, object] = {
        "role": "manager",
        "model_name": "fake-1",
        "analysis": "Looks good.",
        "view": "bullish",
        "confidence": 0.6,
        "evidence": ["e1"],
        "risks": ["r1"],
        "suggested_action": "buy",
        "target_position_pct": Decimal("0.10"),
        "veto": False,
        "needs_human_review": False,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return CommitteeVote.model_validate(defaults)


class TestMarketSnapshot:
    def test_minimal(self) -> None:
        s = _snapshot()
        assert s.symbol == "SPY"
        assert s.reference_price == Decimal("100")
        assert s.recent_return_pct is None
        assert s.recent_volume is None
        assert s.news_context is None

    def test_rejects_naive_datetime(self) -> None:
        with pytest.raises(ValidationError):
            MarketSnapshot.model_validate(
                {
                    "symbol": "SPY",
                    "reference_price": Decimal("100"),
                    "captured_at": datetime(2026, 1, 1),
                }
            )

    def test_rejects_float_price(self) -> None:
        with pytest.raises(ValidationError):
            MarketSnapshot.model_validate(
                {
                    "symbol": "SPY",
                    "reference_price": 100.0,
                    "captured_at": datetime(2026, 1, 1, tzinfo=UTC),
                }
            )

    def test_rejects_non_positive_price(self) -> None:
        with pytest.raises(ValidationError):
            MarketSnapshot.model_validate(
                {
                    "symbol": "SPY",
                    "reference_price": Decimal("0"),
                    "captured_at": datetime(2026, 1, 1, tzinfo=UTC),
                }
            )

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            MarketSnapshot.model_validate(
                {
                    "symbol": "SPY",
                    "reference_price": Decimal("100"),
                    "captured_at": datetime(2026, 1, 1, tzinfo=UTC),
                    "extra": "x",
                }
            )


class TestCommitteeVote:
    def test_minimal(self) -> None:
        v = _vote()
        assert v.role == "manager"
        assert v.confidence == 0.6
        assert v.target_position_pct == Decimal("0.10")
        assert v.veto is False

    def test_confidence_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            _vote(confidence=1.5)
        with pytest.raises(ValidationError):
            _vote(confidence=-0.1)

    def test_target_position_pct_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            _vote(target_position_pct=Decimal("1.5"))
        with pytest.raises(ValidationError):
            _vote(target_position_pct=Decimal("-0.1"))

    def test_blank_analysis_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _vote(analysis="   ")

    def test_blank_model_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _vote(model_name="")

    def test_rejects_naive_datetime(self) -> None:
        with pytest.raises(ValidationError):
            _vote(created_at=datetime(2026, 1, 1))

    def test_rejects_float_target_position_pct(self) -> None:
        with pytest.raises(ValidationError):
            _vote(target_position_pct=0.10)


class TestTradePlan:
    def test_ethics_block_forces_zero_target(self) -> None:
        plan = TradePlan(
            symbol="SPY",
            side="buy",
            target_position_pct=Decimal("0.10"),
            confidence=0.6,
            consensus_level="majority",
            rationale="r",
            needs_human_review=True,
            blocked_by_ethics=True,
            ethics_reason="insider trading",
        )
        assert plan.target_position_pct == Decimal("0")
        assert plan.blocked_by_ethics is True

    def test_target_position_pct_range(self) -> None:
        with pytest.raises(ValidationError):
            TradePlan(
                symbol="SPY",
                side="buy",
                target_position_pct=Decimal("1.5"),
                confidence=0.6,
                consensus_level="majority",
                rationale="r",
                needs_human_review=False,
            )


class TestCommitteeInput:
    def test_default_roles(self) -> None:
        payload = CommitteeInput(snapshot=_snapshot())
        assert payload.roles == [
            "technical",
            "news_sentiment",
            "fundamental",
            "risk",
            "manager",
        ]

    def test_roles_unique(self) -> None:
        with pytest.raises(ValidationError):
            CommitteeInput(
                snapshot=_snapshot(),
                roles=["technical", "technical"],
            )

    def test_roles_unknown(self) -> None:
        with pytest.raises(ValidationError):
            CommitteeInput.model_validate(
                {"snapshot": _snapshot(), "roles": ["unknown"]}
            )

    def test_roles_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            CommitteeInput(snapshot=_snapshot(), roles=[])


class TestDailyCycleRecord:
    def test_minimal(self) -> None:
        record = DailyCycleRecord(
            cycle_id="aic_1",
            trading_day="2026-01-01",
            symbols=["SPY"],
            plans=[],
            votes=[],
            attempts=[],
            outcome="skipped_no_intent",
            enabled=False,
            live_trading_enabled=False,
            summary="empty",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert record.cycle_id == "aic_1"
        assert record.outcome == "skipped_no_intent"
        assert isinstance(record.outcome, str)

    def test_blank_cycle_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DailyCycleRecord(
                cycle_id="   ",
                trading_day="2026-01-01",
                symbols=["SPY"],
                outcome="skipped_no_intent",
                enabled=False,
                live_trading_enabled=False,
                summary="x",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )


class TestOrderAttempt:
    def test_minimal(self) -> None:
        attempt = OrderAttempt(
            intent_id="ai_1",
            approved=True,
            reason="ok",
            requires_human_review=False,
            outcome="executed",
            order_intent_json={"intent_id": "ai_1"},
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert attempt.filled is False
        assert attempt.outcome == "executed"
        assert isinstance(attempt.outcome, str)

    def test_cycle_outcome_values_present(self) -> None:
        # Smoke test: every documented outcome is a valid CycleOutcome.
        values: tuple[CycleOutcome, ...] = (
            "executed",
            "skipped_no_consensus",
            "skipped_no_intent",
            "blocked_risk_gate",
            "blocked_human_review",
            "blocked_ethics",
            "blocked_live_trading",
            "blocked_disabled",
            "error",
        )
        for value in values:
            OrderAttempt(
                intent_id=f"ai_{value}",
                approved=False,
                reason="x",
                requires_human_review=False,
                outcome=value,
                order_intent_json={},
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )