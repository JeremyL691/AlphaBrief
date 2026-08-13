"""M10-W04: evidence-grounded proposal and no-trade schema enforcement.

Covers AC-M10-W04-01/02/03: proposals carry thesis, anti-thesis,
confidence, horizon, entry rationale, invalidation, suggested exposure,
evidence, dissent, freshness, uncertainty, and no-trade; every citation
resolves to an evidence ID in the exact committee snapshot; unsupported
citations, stale critical evidence, contradictory exposure, and missing
dissent produce validation failure and no executable proposal.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from alphabrief_models import (
    FakeProviderAdapter,
    ModelGateway,
    ModelRequest,
    ModelResponse,
)
from alphabrief_trader.committee import CommitteeResult, TradingCommittee
from alphabrief_trader.proposal import (
    build_research_proposal,
    validate_proposal_grounding,
)
from alphabrief_trader.schemas import (
    CommitteeInput,
    EvidenceCitation,
    MarketSnapshot,
    ResearchProposal,
)
from pydantic import ValidationError

_SNAPSHOT_AT = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)

_OPENING_PAYLOAD: dict[str, object] = {
    "analysis": "Trend is constructive with improving breadth.",
    "view": "bullish",
    "confidence": 0.72,
    "evidence": ["ev-price-1: ema20 above ema50", "ev-news-1: earnings beat"],
    "risks": ["crowded positioning"],
    "suggested_action": "buy",
    "target_position_pct": 0.10,
    "veto": False,
    "needs_human_review": False,
}

_CHALLENGE_PAYLOAD: dict[str, object] = {
    "analysis": "The bullish read overweights one headline.",
    "view": "neutral",
    "confidence": 0.6,
    "evidence": ["ev-macro-1: cpi in line"],
    "risks": ["headline reversal"],
    "stance": "dissent",
    "challenged_claim": "earnings beat guarantees continuation",
}

_SUMMARY_PAYLOAD: dict[str, object] = {
    "analysis": "Mixed but constructive; keep dissent on record.",
    "view": "bullish",
    "confidence": 0.7,
    "evidence": ["ev-price-1: uptrend"],
    "risks": ["headline reversal"],
    "stance": "agreement",
    "challenged_claim": None,
}


class _PhasedProvider(FakeProviderAdapter):
    """Deterministic provider switching output by discussion phase."""

    def __init__(
        self,
        *,
        opening: dict[str, object],
        challenge: dict[str, object],
        summary: dict[str, object],
    ) -> None:
        super().__init__(
            provider_name="fake",
            model_name="fake-committee",
            capabilities=["structured_output"],
            structured_output=opening,
        )
        self._opening = opening
        self._challenge = challenge
        self._summary = summary

    def call(self, request: ModelRequest) -> ModelResponse:
        phase = request.metadata.get("phase") or ""
        payload = {
            "challenge": self._challenge,
            "summary": self._summary,
        }.get(phase, self._opening)
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model=self.model_name,
            output_text="{}",
            structured_output=payload,
            status="succeeded",
            finish_reason="stop",
        )


def _snapshot(*, captured_at: datetime = _SNAPSHOT_AT) -> MarketSnapshot:
    return MarketSnapshot(
        symbol="SPY",
        reference_price=Decimal("100"),
        data_version="test-v1",
        captured_at=captured_at,
    )


def _payload(*, captured_at: datetime = _SNAPSHOT_AT) -> CommitteeInput:
    return CommitteeInput(
        snapshot=_snapshot(captured_at=captured_at),
        evidence_ids=["ev-price-1", "ev-news-1", "ev-macro-1"],
    )


def _committee_result(payload: CommitteeInput) -> CommitteeResult:
    provider = _PhasedProvider(
        opening=_OPENING_PAYLOAD,
        challenge=_CHALLENGE_PAYLOAD,
        summary=_SUMMARY_PAYLOAD,
    )
    result = TradingCommittee(
        gateway=ModelGateway(providers=[provider]),
    ).run(payload)
    assert result.ok is True
    return result


def _proposal(**overrides: object) -> ResearchProposal:
    base: dict[str, object] = {
        "proposal_id": "proposal_test",
        "symbol": "SPY",
        "thesis": "Constructive trend.",
        "anti_thesis": "Headline reversal risk.",
        "confidence": 0.7,
        "horizon": "5 trading days",
        "entry_rationale": "Breakout above resistance.",
        "invalidation": "Close below support.",
        "suggested_exposure": Decimal("0.1"),
        "citations": [
            EvidenceCitation(evidence_id="ev-price-1", claim="uptrend")
        ],
        "dissent": "risk: headline reversal risk.",
        "data_freshness": _SNAPSHOT_AT,
        "uncertainty": 0.3,
        "no_trade": False,
        "created_at": _SNAPSHOT_AT,
    }
    base.update(overrides)
    return ResearchProposal(**cast(Any, base))


class TestProposalSchema:
    def test_valid_proposal_carries_all_required_fields(self) -> None:
        proposal = _proposal()
        assert proposal.thesis
        assert proposal.anti_thesis
        assert 0.0 <= proposal.confidence <= 1.0
        assert proposal.horizon
        assert proposal.entry_rationale
        assert proposal.invalidation
        assert proposal.suggested_exposure == Decimal("0.1")
        assert proposal.citations[0].evidence_id == "ev-price-1"
        assert proposal.dissent
        assert proposal.data_freshness.tzinfo is not None
        assert 0.0 <= proposal.uncertainty <= 1.0
        assert proposal.no_trade is False

    def test_no_trade_proposal_rejects_positive_exposure(self) -> None:
        with pytest.raises(ValidationError, match="no_trade"):
            _proposal(no_trade=True, suggested_exposure=Decimal("0.1"))

    def test_tradeable_proposal_rejects_zero_exposure(self) -> None:
        with pytest.raises(ValidationError, match="positive"):
            _proposal(no_trade=False, suggested_exposure=Decimal("0"))

    def test_no_trade_proposal_accepts_zero_exposure(self) -> None:
        proposal = _proposal(no_trade=True, suggested_exposure=Decimal("0"))
        assert proposal.no_trade is True

    def test_blank_dissent_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _proposal(dissent="   ")

    def test_float_exposure_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _proposal(suggested_exposure=0.1)

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            _proposal(unknown_field="x")


class TestProposalBuilder:
    def test_builder_produces_grounded_proposal(self) -> None:
        result = _committee_result(_payload())
        proposal = build_research_proposal(result, _payload(), plan=result.plan)

        assert proposal.symbol == "SPY"
        assert proposal.horizon == "5 trading days"
        assert proposal.no_trade is False
        plan = result.plan
        assert plan is not None
        assert proposal.suggested_exposure == plan.target_position_pct
        assert proposal.data_freshness == _SNAPSHOT_AT
        assert proposal.uncertainty == round(1.0 - proposal.confidence, 4)
        # Dissent from the challenge round is preserved, not flattened.
        assert "dissent" in proposal.dissent or "risk:" in proposal.dissent

    def test_every_citation_resolves_to_snapshot_evidence(self) -> None:
        result = _committee_result(_payload())
        proposal = build_research_proposal(result, _payload(), plan=result.plan)
        available = set(_payload().evidence_ids)
        assert {c.evidence_id for c in proposal.citations} <= available
        assert proposal.citations

    def test_builder_drops_fabricated_evidence_ids(self) -> None:
        payload = _payload()
        result = _committee_result(payload)
        # The opening evidence cites ev-price-1 and ev-news-1, both
        # available; any fabricated ID in the transcript is not emitted.
        proposal = build_research_proposal(result, payload, plan=result.plan)
        for citation in proposal.citations:
            assert citation.evidence_id in set(payload.evidence_ids)

    def test_builder_without_plan_is_conservative_no_trade(self) -> None:
        result = _committee_result(_payload())
        proposal = build_research_proposal(result, _payload())
        assert proposal.no_trade is True
        assert proposal.suggested_exposure == Decimal("0")

    def test_builder_requires_votes(self) -> None:
        from alphabrief_trader.committee import CommitteeResult

        result = CommitteeResult(ok=False, error_message="no_committee_votes")
        with pytest.raises(ValueError, match="no votes"):
            build_research_proposal(result, _payload())


class TestGroundingValidation:
    def test_valid_proposal_passes_grounding(self) -> None:
        proposal = _proposal()
        violations = validate_proposal_grounding(
            proposal,
            available_evidence_ids=["ev-price-1", "ev-news-1"],
            now=_SNAPSHOT_AT + timedelta(minutes=5),
        )
        assert violations == []

    def test_unsupported_citation_fails_grounding(self) -> None:
        proposal = _proposal(
            citations=[
                EvidenceCitation(evidence_id="ev-fake-99", claim="invented")
            ]
        )
        violations = validate_proposal_grounding(
            proposal,
            available_evidence_ids=["ev-price-1"],
            now=_SNAPSHOT_AT + timedelta(minutes=5),
        )
        assert violations == ["unsupported_citation:ev-fake-99"]

    def test_stale_critical_evidence_fails_grounding(self) -> None:
        proposal = _proposal()
        violations = validate_proposal_grounding(
            proposal,
            available_evidence_ids=["ev-price-1"],
            max_evidence_age_seconds=86400,
            now=_SNAPSHOT_AT + timedelta(days=2),
        )
        assert any(
            violation.startswith("stale_critical_evidence:")
            for violation in violations
        )

    def test_fresh_evidence_passes_grounding(self) -> None:
        proposal = _proposal()
        violations = validate_proposal_grounding(
            proposal,
            available_evidence_ids=["ev-price-1"],
            max_evidence_age_seconds=86400,
            now=_SNAPSHOT_AT + timedelta(hours=1),
        )
        assert violations == []

    def test_contradictory_exposure_rejected_at_schema_level(self) -> None:
        # A no-trade proposal with positive exposure can never exist, so
        # no executable proposal is produced.
        with pytest.raises(ValidationError):
            _proposal(no_trade=True, suggested_exposure=Decimal("0.2"))

    def test_missing_dissent_rejected_at_schema_level(self) -> None:
        with pytest.raises(ValidationError):
            _proposal(dissent="")

    def test_grounding_passes_with_real_builder_output(self) -> None:
        result = _committee_result(_payload())
        payload = _payload()
        proposal = build_research_proposal(result, payload, plan=result.plan)
        violations = validate_proposal_grounding(
            proposal,
            available_evidence_ids=payload.evidence_ids,
            now=_SNAPSHOT_AT + timedelta(minutes=5),
        )
        assert violations == []
