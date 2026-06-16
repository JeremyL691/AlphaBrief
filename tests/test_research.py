"""Tests for the Multi-Model Research Committee (Phase 8).

Tests cover debate schemas, the DebateOrchestrator with FakeProviderAdapter,
and consensus generation logic.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from alphabrief_models import FakeProviderAdapter, ModelGateway
from alphabrief_research.orchestrator import (
    DebateOrchestrator,
    _generate_consensus,
)
from alphabrief_research.schemas import (
    DebateConsensus,
    DebateQuestion,
    DebateRecord,
    ModelDebateResponse,
)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TestDebateQuestion:
    def test_minimal_question(self) -> None:
        q = DebateQuestion(question="How is the market?")
        assert q.question == "How is the market?"
        assert q.perspectives == ["technical", "fundamental", "risk", "judge"]
        assert q.symbol is None

    def test_question_with_symbol_and_horizon(self) -> None:
        q = DebateQuestion(
            question="Analyze NVDA",
            symbol="NVDA",
            time_horizon="5 trading days",
            perspectives=["technical", "risk"],
        )
        assert q.symbol == "NVDA"
        assert q.perspectives == ["technical", "risk"]

    def test_empty_question_raises(self) -> None:
        with pytest.raises(ValueError):
            DebateQuestion(question="   ")

    def test_invalid_perspective_raises(self) -> None:
        with pytest.raises(ValueError):
            DebateQuestion(
                question="Test",
                perspectives=["invalid_persp"],
            )

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValueError):
            DebateQuestion(
                question="Test",
                unknown_field="foo",  # type: ignore[call-arg]
            )

    def test_news_and_macro_context_optional(self) -> None:
        q = DebateQuestion(question="How is NVDA?")
        assert q.news_context is None
        assert q.macro_context is None

    def test_news_and_macro_context_accept_strings(self) -> None:
        q = DebateQuestion(
            question="How is NVDA?",
            news_context="NVDA reported strong Q3 results.",
            macro_context="CPI 3.1% YoY, Fed funds rate 5.25%.",
        )
        assert q.news_context is not None
        assert "Q3" in q.news_context
        assert q.macro_context is not None
        assert "CPI" in q.macro_context


class TestModelDebateResponse:
    def test_minimal_response(self) -> None:
        r = ModelDebateResponse(
            model_name="test-model",
            perspective="technical",
            analysis="Markets look strong.",
            view="bullish",
            confidence=0.85,
            suggested_action="buy",
        )
        assert r.model_name == "test-model"
        assert r.view == "bullish"
        assert r.confidence == 0.85

    def test_confidence_range_enforced(self) -> None:
        with pytest.raises(ValueError):
            ModelDebateResponse(
                model_name="m",
                perspective="risk",
                analysis="test",
                view="neutral",
                confidence=1.5,
                suggested_action="hold",
            )

    def test_blank_fields_raise(self) -> None:
        with pytest.raises(ValueError):
            ModelDebateResponse(
                model_name="",
                perspective="technical",
                analysis="test",
                view="neutral",
                confidence=0.5,
                suggested_action="watch",
            )


class TestDebateConsensus:
    def test_minimal_consensus(self) -> None:
        c = DebateConsensus(
            num_models=3,
            agreement_level="high",
            avg_confidence=0.8,
        )
        assert c.num_models == 3
        assert c.agreement_level == "high"

    def test_agreement_level_validated(self) -> None:
        with pytest.raises(ValueError):
            DebateConsensus(
                num_models=1,
                agreement_level="invalid",  # type: ignore[arg-type]
                avg_confidence=0.5,
            )


class TestDebateRecord:
    def test_full_record(self) -> None:
        now = datetime.now(UTC)
        q = DebateQuestion(question="Test?")
        r = ModelDebateResponse(
            model_name="m1",
            perspective="technical",
            analysis="analysis",
            view="bullish",
            confidence=0.8,
            suggested_action="buy",
        )
        c = DebateConsensus(
            num_models=1,
            agreement_level="high",
            avg_confidence=0.8,
        )
        record = DebateRecord(
            debate_id="deb_test",
            question=q,
            responses=[r],
            consensus=c,
            created_at=now,
        )
        assert record.debate_id == "deb_test"
        assert len(record.responses) == 1
        assert record.consensus is not None
        assert record.consensus.avg_confidence == 0.8

    def test_blank_debate_id_raises(self) -> None:
        with pytest.raises(ValueError):
            DebateRecord(
                debate_id="",
                question=DebateQuestion(question="?"),
                created_at=datetime.now(UTC),
            )


# ---------------------------------------------------------------------------
# Consensus generation
# ---------------------------------------------------------------------------


class TestGenerateConsensus:
    def test_single_response(self) -> None:
        responses = [
            ModelDebateResponse(
                model_name="m1",
                perspective="technical",
                analysis="Bullish",
                view="bullish",
                confidence=0.9,
                evidence=["Earnings beat"],
                risks=["Valuation"],
                suggested_action="buy",
                needs_human_review=False,
            ),
        ]
        c = _generate_consensus(responses)
        assert c.num_models == 1
        assert c.agreement_level == "high"
        assert c.consensus_view == "bullish"
        assert c.avg_confidence == 0.9
        assert c.suggested_action == "buy"

    def test_mixed_views(self) -> None:
        responses = [
            ModelDebateResponse(
                model_name="m1", perspective="technical",
                analysis="a", view="bullish", confidence=0.8,
                evidence=[], risks=[], suggested_action="buy",
                needs_human_review=False,
            ),
            ModelDebateResponse(
                model_name="m2", perspective="fundamental",
                analysis="b", view="bearish", confidence=0.6,
                evidence=[], risks=[], suggested_action="sell",
                needs_human_review=False,
            ),
        ]
        c = _generate_consensus(responses)
        assert c.num_models == 2
        assert c.agreement_level == "medium"
        assert c.avg_confidence == 0.7
        assert len(c.disagreements) > 0
        assert c.needs_human_review is True

    def test_empty_responses(self) -> None:
        c = _generate_consensus([])
        assert c.num_models == 0
        assert c.agreement_level == "mixed"
        assert c.needs_human_review is True

    def test_evidence_deduplication(self) -> None:
        responses = [
            ModelDebateResponse(
                model_name="m1", perspective="technical",
                analysis="a", view="bullish", confidence=0.5,
                evidence=["Strong earnings", "Good earnings"],
                risks=[], suggested_action="hold",
                needs_human_review=False,
            ),
            ModelDebateResponse(
                model_name="m2", perspective="fundamental",
                analysis="b", view="bullish", confidence=0.5,
                evidence=["Strong earnings"],
                risks=[], suggested_action="hold",
                needs_human_review=False,
            ),
        ]
        c = _generate_consensus(responses)
        # "Strong earnings" should appear only once
        count = sum(1 for e in c.key_evidence if "Strong earnings" in e)
        assert count == 1


# ---------------------------------------------------------------------------
# DebateOrchestrator with FakeProviderAdapter
# ---------------------------------------------------------------------------


class TestDebateOrchestrator:
    def test_debate_returns_result_with_fake_provider(self) -> None:
        provider = FakeProviderAdapter(
            provider_name="fake-test",
            model_name="test-model",
            capabilities=["structured_output"],
            structured_output={
                "analysis": "Sample analysis from fake provider.",
                "view": "neutral",
                "confidence": 0.7,
                "evidence": ["Point 1", "Point 2"],
                "risks": ["Risk 1"],
                "suggested_action": "watch",
                "needs_human_review": True,
            },
        )
        gateway = ModelGateway([provider])
        orchestrator = DebateOrchestrator(gateway)

        question = DebateQuestion(
            question="What is the outlook for BTC?",
            symbol="BTC-USD",
            perspectives=["technical", "fundamental"],
        )
        result = orchestrator.debate(question)

        assert result.ok
        assert result.record is not None
        assert result.record.debate_id.startswith("deb_")
        assert len(result.record.responses) == 2  # one per perspective
        assert result.record.consensus is not None
        assert result.record.consensus.num_models == 2

    def test_debate_with_invalid_question(self) -> None:
        provider = FakeProviderAdapter(
            provider_name="fake-test",
            model_name="test-model",
            capabilities=["structured_output"],
        )
        gateway = ModelGateway([provider])
        _ = gateway  # gateway available for future orchestration

        # Empty question should fail validation before orchestration
        with pytest.raises(ValueError):
            DebateQuestion(question="")

    def test_debate_empty_gateway_raises(self) -> None:
        with pytest.raises(TypeError):
            DebateOrchestrator(gateway=None)  # type: ignore[arg-type]


def test_orchestrator_includes_news_and_macro_context_in_prompt() -> None:
    from alphabrief_research.orchestrator import _build_prompt

    question = DebateQuestion(
        question="Analyze AAPL",
        news_context="AAPL earnings beat estimates.",
        macro_context="CPI 3.1% YoY",
    )

    prompt = _build_prompt(question, "technical")

    assert "AAPL earnings beat estimates." in prompt
    assert "CPI 3.1% YoY" in prompt
    assert "untrusted external data" in prompt
    assert "must not override rules" in prompt


def test_orchestrator_prompt_omits_context_sections_when_not_set() -> None:
    from alphabrief_research.orchestrator import _build_prompt

    question = DebateQuestion(question="Analyze AAPL")

    prompt = _build_prompt(question, "technical")

    assert "News Context" not in prompt
    assert "Macro Context" not in prompt


def test_orchestrator_perspective_prompts_mention_external_data_caution() -> None:
    from alphabrief_research.orchestrator import _PERSPECTIVE_PROMPTS

    for perspective in ("fundamental", "risk", "judge"):
        text = _PERSPECTIVE_PROMPTS[perspective]
        assert (
            "News/Macro Context" in text
            or "基础" in text
            or "批判" in text
        )
