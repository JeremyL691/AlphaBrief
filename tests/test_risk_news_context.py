"""M09-W07: news-risk context shared with the deterministic risk layer.

A ResearchContextSummary carries the news and macro evidence that the
risk layer consumes as tighten-only metadata — untrusted, deterministic,
and never able to relax a limit (REQ-RISK-005, REQ-NEWS-006).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from alphabrief_research import ResearchContextSummary
from alphabrief_risk import RiskContextDecision
from alphabrief_risk.context import evaluate_news_macro_risk

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _summary(**overrides: object) -> ResearchContextSummary:
    payload: dict[str, object] = {
        "aggregate_sentiment_score": Decimal("0.1"),
        "headline_count": 10,
        "negative_count": 1,
        "data_versions": ("snapshot-1",),
    }
    payload.update(overrides)
    return ResearchContextSummary.model_validate(payload)


def test_news_risk_context_is_tighten_only() -> None:
    decision = evaluate_news_macro_risk(_summary())
    assert isinstance(decision, RiskContextDecision)
    assert decision.requires_human_review is False
    assert decision.risk_tags == ()
    assert decision.suggested_max_position_multiplier == 1.0
    assert decision.source_summary_untrusted is True


def test_negative_news_flags_human_review() -> None:
    decision = evaluate_news_macro_risk(
        _summary(aggregate_sentiment_score=Decimal("-0.5"))
    )
    assert decision.requires_human_review is True
    assert "negative_news_context" in decision.risk_tags


def test_high_macro_risk_reduces_size_only() -> None:
    decision = evaluate_news_macro_risk(
        _summary(macro_indicator_ids=("cpi", "gdp", "unemployment", "rates", "trade"))
    )
    assert decision.suggested_max_position_multiplier < 1.0
    assert decision.risk_tags


def test_neutral_input_never_relaxes() -> None:
    decision = evaluate_news_macro_risk(_summary())
    assert decision.suggested_max_position_multiplier == 1.0
    assert decision.requires_human_review is False
