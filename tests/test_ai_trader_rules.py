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
        # PROJECT_GUIDE 5.4: below 0.55 confidence the committee is no_trade.
        assert config.no_trade_below_confidence == 0.55
        assert config.min_analysts_supporting_direction == 2
        assert config.honour_risk_role_veto is True

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
                _vote(role="intermarket", view="bullish"),
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
                _vote(role="intermarket", view="bullish"),
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
                _vote(role="intermarket", view="bullish"),
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
                _vote(role="intermarket", view="bearish"),
                _vote(role="risk", view="bullish"),
            ],
        )
        plan2 = gate.synthesize(
            symbol="SPY",
            manager_vote=manager,
            analyst_votes=[
                _vote(role="technical", view="bullish"),
                _vote(role="intermarket", view="bearish"),
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
                _vote(role="intermarket", view="bullish"),
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
                _vote(role="intermarket", view="bullish"),
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
                _vote(role="intermarket", view="bullish"),
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
                _vote(role="intermarket", view="bearish"),
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
                _vote(role="intermarket", view="bullish"),
                _vote(role="risk", view="bullish"),
            ],
        )
        assert "e1" in plan.key_evidence
        assert "r1" in plan.key_risks
        assert "r2" in plan.key_risks
        # No duplicate e1
        assert plan.key_evidence.count("e1") == 1

class TestRiskRoleVeto:
    """PROJECT_GUIDE 5.4: the risk role's veto forces no_trade."""

    def _analysts(self, *, risk_veto: bool) -> list[CommitteeVote]:
        return [
            _vote(role="technical", view="bullish", confidence=0.8),
            _vote(role="macro_news", view="bullish", confidence=0.7),
            _vote(
                role="risk",
                view="bullish" if not risk_veto else "uncertain",
                confidence=0.9,
                veto=risk_veto,
            ),
        ]

    def test_without_a_veto_the_trade_is_planned(self) -> None:
        plan = DisciplineGate().synthesize(
            symbol="EUR_USD",
            manager_vote=_vote(confidence=0.8),
            analyst_votes=self._analysts(risk_veto=False),
        )

        assert plan.target_position_pct > 0

    def test_a_risk_veto_blocks_new_exposure(self) -> None:
        plan = DisciplineGate().synthesize(
            symbol="EUR_USD",
            manager_vote=_vote(confidence=0.8),
            analyst_votes=self._analysts(risk_veto=True),
        )

        assert plan.target_position_pct == Decimal("0")
        assert plan.needs_human_review is True
        assert "risk role vetoed" in plan.rationale

    def test_the_veto_can_be_disabled_only_by_configuration(self) -> None:
        gate = DisciplineGate(config=DisciplineConfig(honour_risk_role_veto=False))

        plan = gate.synthesize(
            symbol="EUR_USD",
            manager_vote=_vote(confidence=0.8),
            analyst_votes=self._analysts(risk_veto=True),
        )

        assert plan.target_position_pct > 0


class TestDirectionAgreement:
    """PROJECT_GUIDE 5.4: an opening needs at least two supporting analysts."""

    def test_two_supporting_analysts_allow_the_opening(self) -> None:
        plan = DisciplineGate().synthesize(
            symbol="EUR_USD",
            manager_vote=_vote(confidence=0.8),
            analyst_votes=[
                _vote(role="technical", view="bullish", confidence=0.8),
                _vote(role="intermarket", view="bullish", confidence=0.7),
                _vote(role="risk", view="uncertain", confidence=0.9),
            ],
        )

        assert plan.target_position_pct > 0

    def test_a_lone_supporter_is_not_a_mandate(self) -> None:
        plan = DisciplineGate().synthesize(
            symbol="EUR_USD",
            manager_vote=_vote(confidence=0.8),
            analyst_votes=[
                _vote(role="technical", view="bullish", confidence=0.8),
                _vote(role="intermarket", view="uncertain", confidence=0.4),
                _vote(role="risk", view="uncertain", confidence=0.9),
            ],
        )

        assert plan.target_position_pct == Decimal("0")
        assert "required" in plan.rationale

    def test_low_confidence_still_forces_no_trade_first(self) -> None:
        plan = DisciplineGate().synthesize(
            symbol="EUR_USD",
            manager_vote=_vote(confidence=0.5),
            analyst_votes=[
                _vote(role="technical", view="bullish", confidence=0.8),
                _vote(role="intermarket", view="bullish", confidence=0.7),
            ],
        )

        assert plan.target_position_pct == Decimal("0")
        assert "below no_trade_below_confidence" in plan.rationale


class TestReviewedDisciplineOverrides:
    """The configured thresholds must actually take effect.

    Two hard floors used to override the reviewed config whenever the manager
    emitted a native action (which production always does): the confidence
    floor became ``max(config, 0.55)`` and the risk veto was honoured even with
    ``honour_risk_role_veto=False``. A config that cannot take effect is worse
    than no config: it reads as reviewed while the code silently ignores it.
    The safety net for a low-confidence plan is now the RiskGate, not a
    constant that overrides the operator's reviewed decision.
    """

    def test_zero_floor_lets_a_low_confidence_plan_through(self) -> None:
        """Production always carries a native manager action, so the floor
        must be tested with one: that is the branch where ``max(config, 0.55)``
        used to override the reviewed value."""
        gate = DisciplineGate(
            config=DisciplineConfig(
                no_trade_below_confidence=0.0,
                min_analysts_supporting_direction=0,
                require_min_consensus="no_consensus",
            )
        )
        plan = gate.synthesize(
            symbol="EUR_USD",
            manager_vote=_vote(confidence=0.10, manager_action="open_long"),
            analyst_votes=[
                _vote(role="technical", view="bullish", confidence=0.2),
            ],
        )

        assert plan.target_position_pct > 0
        assert plan.confidence == 0.10

    def test_risk_veto_is_releasable_by_config(self) -> None:
        gate = DisciplineGate(
            config=DisciplineConfig(
                honour_risk_role_veto=False,
                min_analysts_supporting_direction=0,
                require_min_consensus="no_consensus",
            )
        )
        plan = gate.synthesize(
            symbol="EUR_USD",
            manager_vote=_vote(confidence=0.8, manager_action="open_long"),
            analyst_votes=[
                _vote(role="technical", view="bullish", confidence=0.8),
                _vote(role="risk", view="uncertain", confidence=0.9, veto=True),
            ],
        )

        assert plan.target_position_pct > 0
        assert "risk role vetoed" not in plan.rationale

    def test_risk_veto_still_blocks_by_default(self) -> None:
        """The guide default is unchanged: a veto blocks new exposure."""
        plan = DisciplineGate().synthesize(
            symbol="EUR_USD",
            manager_vote=_vote(confidence=0.8, manager_action="open_long"),
            analyst_votes=[
                _vote(role="technical", view="bullish", confidence=0.8),
                _vote(role="risk", view="uncertain", confidence=0.9, veto=True),
            ],
        )

        assert plan.target_position_pct == Decimal("0")
        assert "risk role vetoed" in plan.rationale

    def test_default_floor_still_blocks_low_confidence_with_native_action(
        self,
    ) -> None:
        """With the guide default, a native-action plan below 0.55 stays flat."""
        plan = DisciplineGate().synthesize(
            symbol="EUR_USD",
            manager_vote=_vote(confidence=0.20, manager_action="open_long"),
            analyst_votes=[
                _vote(role="technical", view="bullish", confidence=0.8),
                _vote(role="intermarket", view="bullish", confidence=0.7),
            ],
        )

        assert plan.target_position_pct == Decimal("0")
        assert "below no_trade_below_confidence" in plan.rationale
