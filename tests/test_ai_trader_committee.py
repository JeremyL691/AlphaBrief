"""Tests for the AI Trading Committee orchestrator."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alphabrief_models import FakeProviderAdapter, ModelGateway
from alphabrief_trader.committee import (
    TradingCommittee,
    _PartialCommitteeVote,
)
from alphabrief_trader.schemas import CommitteeInput, MarketSnapshot
from pydantic import ValidationError


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        symbol="SPY",
        reference_price=Decimal("100"),
        data_version="test-v1",
        captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _build_provider(payload: dict[str, object]) -> FakeProviderAdapter:
    return FakeProviderAdapter(
        provider_name="fake",
        model_name="fake-1",
        capabilities=["structured_output"],
        structured_output=payload,
    )


def _build_committee(provider: FakeProviderAdapter) -> TradingCommittee:
    return TradingCommittee(gateway=ModelGateway(providers=[provider]))


class TestTradingCommittee:
    def test_all_four_roles_succeed(self) -> None:
        payload = {
            "analysis": "Bullish setup with trend continuation.",
            "view": "bullish",
            "confidence": 0.65,
            "evidence": ["e1"],
            "risks": ["r1"],
            "suggested_action": "buy",
            "target_position_pct": 0.10,
            "veto": False,
            "needs_human_review": False,
        }
        committee = _build_committee(_build_provider(payload))
        result = committee.run(CommitteeInput(snapshot=_snapshot()))
        assert result.ok is True
        assert result.plan is not None
        assert result.plan.target_position_pct > 0
        assert len(result.votes) == 4
        roles = {v.role for v in result.votes}
        assert roles == {"technical", "fundamental", "risk", "manager"}

    def test_fake_provider_failure_yields_no_votes(self) -> None:
        # A failing provider returns no successful responses → no votes
        # and a stable error code.
        provider = FakeProviderAdapter(
            provider_name="fake",
            model_name="fake-1",
            capabilities=["structured_output"],
            fail=True,
        )
        committee = _build_committee(provider)
        result = committee.run(CommitteeInput(snapshot=_snapshot()))
        assert result.ok is False
        assert result.error_message == "no_committee_votes"
        assert result.plan is None

    def test_invalid_structured_output_skipped(self) -> None:
        provider = FakeProviderAdapter(
            provider_name="fake",
            model_name="fake-1",
            capabilities=["structured_output"],
            structured_output={"bogus": "field"},
        )
        committee = _build_committee(provider)
        result = committee.run(CommitteeInput(snapshot=_snapshot()))
        # No vote passes validation → ok=False
        assert result.ok is False

    def test_ethics_keyword_in_manager_blocks(self) -> None:
        payload = {
            "analysis": "Suspected insider trading activity.",
            "view": "bullish",
            "confidence": 0.95,
            "evidence": ["e1"],
            "risks": [],
            "suggested_action": "buy",
            "target_position_pct": 0.30,
            "veto": False,
            "needs_human_review": False,
        }
        committee = _build_committee(_build_provider(payload))
        result = committee.run(CommitteeInput(snapshot=_snapshot()))
        assert result.ok is True
        assert result.plan is not None
        assert result.plan.blocked_by_ethics is True
        assert result.plan.target_position_pct == Decimal("0")

    def test_custom_role_order(self) -> None:
        payload = {
            "analysis": "x",
            "view": "bullish",
            "confidence": 0.7,
            "evidence": [],
            "risks": [],
            "suggested_action": "buy",
            "target_position_pct": 0.10,
            "veto": False,
            "needs_human_review": False,
        }
        committee = TradingCommittee(
            gateway=ModelGateway(providers=[_build_provider(payload)]),
            roles=("manager",),
        )
        result = committee.run(
            CommitteeInput(snapshot=_snapshot(), roles=["manager"])
        )
        assert result.ok is True
        assert len(result.votes) == 1
        assert result.votes[0].role == "manager"

    def test_none_gateway_raises(self) -> None:
        with pytest.raises(TypeError):
            TradingCommittee(gateway=None)  # type: ignore[arg-type]


class TestPartialSchema:
    def test_minimal(self) -> None:
        v = _PartialCommitteeVote(
            analysis="a",
            view="bullish",
            confidence=0.5,
            suggested_action="buy",
            target_position_pct=0.1,
        )
        assert v.veto is False
        assert v.needs_human_review is False

    def test_confidence_range(self) -> None:
        with pytest.raises(ValidationError):
            _PartialCommitteeVote(
                analysis="a",
                view="bullish",
                confidence=1.5,
                suggested_action="buy",
                target_position_pct=0.1,
            )

    def test_action_literal(self) -> None:
        with pytest.raises(ValidationError):
            _PartialCommitteeVote(
                analysis="a",
                view="bullish",
                confidence=0.5,
                suggested_action="liquidate",  # type: ignore[arg-type]
                target_position_pct=0.1,
            )

    def test_target_position_pct_range(self) -> None:
        with pytest.raises(ValidationError):
            _PartialCommitteeVote(
                analysis="a",
                view="bullish",
                confidence=0.5,
                suggested_action="buy",
                target_position_pct=2.0,
            )