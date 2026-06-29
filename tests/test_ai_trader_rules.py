"""Tests for the deterministic trading-discipline rules."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alphabrief_trader.rules import DisciplineConfig, DisciplineGate
from alphabrief_trader.schemas import CommitteeVote


def _vote(**overrides: object) -> CommitteeVote:
    defaults: dict[str, object] = {
        "role": "manager",
        "model_name": "fake",
        "analysis": "Looks good.",
        "view": "bullish",
        "confidence": 0.7,
        "evidence": ["e"],
        "risks": [],
        "suggested_action": "buy",
        "target_position_pct": Decimal("0.10"),
        "veto": False,
        "needs_human_review": False,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return CommitteeVote.model_validate(defaults)


class TestDisciplineConfig:
    def test_defaults_valid(self) -> None:
        config = DisciplineConfig()
        assert config.max_position_pct == Decimal("0.25")
        assert config.no_trade_below_confidence == 0.45

    def test_invalid_max_position_pct(self) -> None:
        with pytest.raises(ValueError):
            DisciplineConfig(max_position_pct=Decimal("0"))
        with pytest.raises(ValueError):
            DisciplineConfig(max_position_pct=Decimal("1.5"))

    def test_invalid_confidence(self) -> None:
        with pytest.raises(ValueError):
            DisciplineConfig(no_trade_below_confidence=-0.1)
        with pytest.raises(ValueError):
            DisciplineConfig(no_trade_below_confidence=1.5)

    def test_invalid_consensus(self) -> None:
        with pytest.raises(ValueError):
            DisciplineConfig(require_min_consensus="unknown")  # type: ignore[arg-type]

    def test_blank_ethics_keyword(self) -> None:
        with pytest.raises(ValueError):
            DisciplineConfig(ethics_keywords=("insider", "  "))


class TestDisciplineGate:
    def test_buy_plan_under_cap(self) -> None:
        gate = DisciplineGate()
        manager = _vote(
            confidence=0.7,
            suggested_action="buy",
            target_position_pct=Decimal("0.10"),
        )
        plan = gate.synthesize(
            symbol="SPY",
            manager_vote=manager,
            analyst_votes=[
                _vote(role="technical", view="bullish"),
                _vote(role="fundamental", view="bullish"),
                _vote(role="risk", view="bullish"),
            ],
        )
        assert plan.side == "buy"
        assert plan.target_position_pct == Decimal("0.10")
        assert plan.blocked_by_ethics is False
        assert plan.consensus_level == "unanimous"

    def test_buy_plan_clamped_to_cap(self) -> None:
        gate = DisciplineGate(
            config=DisciplineConfig(max_position_pct=Decimal("0.20"))
        )
        manager = _vote(
            confidence=0.8,
            suggested_action="buy",
            target_position_pct=Decimal("0.50"),
        )
        plan = gate.synthesize(
            symbol="SPY",
            manager_vote=manager,
            analyst_votes=[
                _vote(role="technical", view="bullish"),
                _vote(role="fundamental", view="bullish"),
                _vote(role="risk", view="bullish"),
            ],
        )
        assert plan.target_position_pct == Decimal("0.20")

    def test_low_confidence_blocks(self) -> None:
        gate = DisciplineGate()
        manager = _vote(confidence=0.20, suggested_action="buy")
        plan = gate.synthesize(
            symbol="SPY",
            manager_vote=manager,
            analyst_votes=[
                _vote(role="technical", view="bullish"),
                _vote(role="fundamental", view="bullish"),
                _vote(role="risk", view="bullish"),
            ],
        )
        assert plan.target_position_pct == Decimal("0")
        assert plan.needs_human_review is True
        assert "0.20" in plan.rationale

    def test_consensus_split_blocks(self) -> None:
        gate = DisciplineGate(
            config=DisciplineConfig(require_min_consensus="majority")
        )
        manager = _vote(
            confidence=0.7,
            view="bullish",
            suggested_action="buy",
        )
        # Force a real split: 2/3 bullish + manager agrees would be
        # "majority" which the gate would *allow*. Force a "no_consensus"
        # case instead.
        gate.synthesize(
            symbol="SPY",
            manager_vote=manager,
            analyst_votes=[
                _vote(role="technical", view="bullish"),
                _vote(role="fundamental", view="bearish"),
                _vote(role="risk", view="bullish"),
            ],
        )
        plan2 = gate.synthesize(
            symbol="SPY",
            manager_vote=manager,
            analyst_votes=[
                _vote(role="technical", view="bullish"),
                _vote(role="fundamental", view="bearish"),
                _vote(role="risk", view="neutral"),
            ],
        )
        # analyst views: bullish/bearish/neutral (3 distinct).
        # pick requirement: majority.
        assert plan2.target_position_pct == Decimal("0")
        assert plan2.needs_human_review is True

    def test_ethics_keyword_blocks(self) -> None:
        gate = DisciplineGate()
        manager = _vote(
            analysis="There are signs of insider trading; we should not engage.",
            confidence=0.9,
            suggested_action="buy",
            target_position_pct=Decimal("0.20"),
        )
        plan = gate.synthesize(
            symbol="SPY",
            manager_vote=manager,
            analyst_votes=[
                _vote(role="technical", view="bullish"),
                _vote(role="fundamental", view="bullish"),
                _vote(role="risk", view="bullish"),
            ],
        )
        assert plan.blocked_by_ethics is True
        assert plan.target_position_pct == Decimal("0")
        assert plan.ethics_reason is not None
        assert "insider" in plan.ethics_reason

    def test_analyst_veto_sets_human_review(self) -> None:
        gate = DisciplineGate()
        manager = _vote(
            confidence=0.7,
            suggested_action="buy",
            target_position_pct=Decimal("0.10"),
        )
        plan = gate.synthesize(
            symbol="SPY",
            manager_vote=manager,
            analyst_votes=[
                _vote(role="technical", view="bullish"),
                _vote(role="fundamental", view="bullish"),
                _vote(
                    role="risk",
                    view="bearish",
                    veto=True,
                    suggested_action="sell",
                ),
            ],
        )
        assert plan.needs_human_review is True

    def test_hold_action_yields_zero_target(self) -> None:
        gate = DisciplineGate()
        manager = _vote(
            confidence=0.8,
            suggested_action="hold",
            target_position_pct=Decimal("0.10"),
        )
        plan = gate.synthesize(
            symbol="SPY",
            manager_vote=manager,
            analyst_votes=[
                _vote(role="technical", view="bullish"),
                _vote(role="fundamental", view="bullish"),
                _vote(role="risk", view="bullish"),
            ],
        )
        assert plan.target_position_pct == Decimal("0")

    def test_sell_action_emits_sell_side(self) -> None:
        gate = DisciplineGate()
        manager = _vote(
            confidence=0.8,
            view="bearish",
            suggested_action="sell",
            target_position_pct=Decimal("0.10"),
        )
        plan = gate.synthesize(
            symbol="SPY",
            manager_vote=manager,
            analyst_votes=[
                _vote(role="technical", view="bearish"),
                _vote(role="fundamental", view="bearish"),
                _vote(role="risk", view="bearish"),
            ],
        )
        assert plan.side == "sell"
        assert plan.target_position_pct == Decimal("0.10")

    def test_dedup_evidence_and_risks(self) -> None:
        gate = DisciplineGate()
        manager = _vote(
            confidence=0.8,
            suggested_action="buy",
            target_position_pct=Decimal("0.10"),
            evidence=["e1", "e2"],
            risks=["r1"],
        )
        plan = gate.synthesize(
            symbol="SPY",
            manager_vote=manager,
            analyst_votes=[
                _vote(
                    role="technical",
                    view="bullish",
                    evidence=["e1", "e3"],
                    risks=["r1", "r2"],
                ),
                _vote(role="fundamental", view="bullish"),
                _vote(role="risk", view="bullish"),
            ],
        )
        assert "e1" in plan.key_evidence
        assert "r1" in plan.key_risks
        assert "r2" in plan.key_risks
        # No duplicate e1
        assert plan.key_evidence.count("e1") == 1