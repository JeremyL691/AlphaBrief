"""Tests for the news/macro risk-context layer.

These tests verify the deterministic, tighten-only behaviour of
:mod:`alphabrief_risk.context`. They do **not** touch :class:`RiskGate`
or :class:`KillSwitch` core semantics; the context layer is a thin,
read-only adapter.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alphabrief_news import MacroIndicator, NewsHeadline
from alphabrief_research import build_structured_summary
from alphabrief_risk import (
    MACRO_HIGH_RISK_INDICATOR_COUNT,
    MACRO_HIGH_RISK_POSITION_MULTIPLIER,
    NEGATIVE_SENTIMENT_FLOOR,
    RISK_TAG_HUMAN_REVIEW,
    RISK_TAG_MACRO_HIGH_RISK,
    RISK_TAG_NEGATIVE_NEWS,
    RISK_TAG_POSITION_REDUCTION,
    NewsMacroRiskContext,
    RiskContextDecision,
    evaluate_news_macro_risk,
)
from pydantic import ValidationError

NOW = datetime(2026, 6, 14, 9, 30, tzinfo=UTC)


def _headline(
    headline_id: str,
    sentiment: str | None,
    data_version: str = "news-v1",
) -> NewsHeadline:
    return NewsHeadline(
        headline_id=headline_id,
        published_at=NOW,
        symbols=["AAPL"],
        category="earnings",
        source="test",
        title=f"headline {headline_id}",
        sentiment=sentiment,  # type: ignore[arg-type]
        data_version=data_version,
    )


def _indicator(indicator_id: str) -> MacroIndicator:
    return MacroIndicator(
        indicator_id=indicator_id,
        name=indicator_id,
        country="US",
        released_at=NOW,
        period="2026-05",
        value=Decimal("1"),
        unit="index",
        source="test",
        data_version="macro-v1",
    )


def test_empty_inputs_return_neutral_decision() -> None:
    summary = build_structured_summary([], [])

    decision = evaluate_news_macro_risk(summary, decision_id="rctx_empty")

    assert decision.requires_human_review is False
    assert decision.risk_tags == ()
    assert decision.suggested_max_position_multiplier == 1.0
    assert decision.notes == ()
    assert decision.source_summary_untrusted is True
    assert decision.decision_id == "rctx_empty"


def test_positive_news_does_not_relax_risk() -> None:
    headlines = [
        _headline("h1", "positive"),
        _headline("h2", "positive"),
        _headline("h3", "positive"),
    ]
    summary = build_structured_summary(headlines, [])

    decision = evaluate_news_macro_risk(summary, decision_id="rctx_pos")

    # Positive news is the default; the layer must never relax.
    assert decision.requires_human_review is False
    assert decision.risk_tags == ()
    assert decision.suggested_max_position_multiplier == 1.0


def test_negative_worst_sentiment_flips_human_review() -> None:
    headlines = [
        _headline("h1", "negative"),
        _headline("h2", "neutral"),
    ]
    summary = build_structured_summary(headlines, [])

    decision = evaluate_news_macro_risk(summary, decision_id="rctx_neg_label")

    assert decision.requires_human_review is True
    assert RISK_TAG_NEGATIVE_NEWS in decision.risk_tags
    assert RISK_TAG_HUMAN_REVIEW in decision.risk_tags
    assert decision.suggested_max_position_multiplier == 1.0
    assert any("worst_sentiment=negative" in note for note in decision.notes)


def test_low_aggregate_sentiment_flips_human_review() -> None:
    # (0 positive - 3 negative) / 3 = -1.0, well below the default floor.
    headlines = [
        _headline("h1", "negative"),
        _headline("h2", "negative"),
        _headline("h3", "negative"),
    ]
    summary = build_structured_summary(headlines, [])

    decision = evaluate_news_macro_risk(summary, decision_id="rctx_neg_score")

    assert decision.requires_human_review is True
    assert RISK_TAG_NEGATIVE_NEWS in decision.risk_tags
    assert RISK_TAG_HUMAN_REVIEW in decision.risk_tags


def test_macro_high_risk_suggests_position_reduction() -> None:
    # Exactly MACRO_HIGH_RISK_INDICATOR_COUNT should NOT trigger.
    indicators = [
        _indicator(f"fred:I{i}") for i in range(MACRO_HIGH_RISK_INDICATOR_COUNT)
    ]
    summary = build_structured_summary([], indicators)

    decision = evaluate_news_macro_risk(summary, decision_id="rctx_macro_low")

    assert RISK_TAG_MACRO_HIGH_RISK not in decision.risk_tags
    assert decision.suggested_max_position_multiplier == 1.0

    # Above the threshold should trigger and reduce the multiplier.
    extra = [_indicator(f"fred:I{MACRO_HIGH_RISK_INDICATOR_COUNT}")]
    summary2 = build_structured_summary([], indicators + extra)

    decision2 = evaluate_news_macro_risk(summary2, decision_id="rctx_macro_hi")

    assert RISK_TAG_MACRO_HIGH_RISK in decision2.risk_tags
    assert RISK_TAG_POSITION_REDUCTION in decision2.risk_tags
    assert decision2.suggested_max_position_multiplier == (
        MACRO_HIGH_RISK_POSITION_MULTIPLIER
    )
    assert decision2.suggested_max_position_multiplier <= 1.0


def test_negative_news_and_high_macro_combine() -> None:
    headlines = [_headline("h1", "negative"), _headline("h2", "negative")]
    indicators = [
        _indicator(f"fred:I{i}") for i in range(MACRO_HIGH_RISK_INDICATOR_COUNT + 1)
    ]
    summary = build_structured_summary(headlines, indicators)

    decision = evaluate_news_macro_risk(summary, decision_id="rctx_both")

    assert decision.requires_human_review is True
    assert RISK_TAG_NEGATIVE_NEWS in decision.risk_tags
    assert RISK_TAG_HUMAN_REVIEW in decision.risk_tags
    assert RISK_TAG_MACRO_HIGH_RISK in decision.risk_tags
    assert RISK_TAG_POSITION_REDUCTION in decision.risk_tags
    assert decision.suggested_max_position_multiplier == (
        MACRO_HIGH_RISK_POSITION_MULTIPLIER
    )


def test_decision_can_only_tighten_position_multiplier() -> None:
    # Confirm the layer rejects multipliers that would relax the limit.
    with pytest.raises(ValueError, match=r"\(0\.0, 1\.0\]"):
        evaluate_news_macro_risk(
            build_structured_summary([], []),
            decision_id="rctx_bad",
            macro_position_multiplier=1.5,
        )
    with pytest.raises(ValueError, match=r"\(0\.0, 1\.0\]"):
        evaluate_news_macro_risk(
            build_structured_summary([], []),
            decision_id="rctx_bad",
            macro_position_multiplier=0.0,
        )


def test_decision_id_must_be_non_blank() -> None:
    with pytest.raises(ValueError, match="decision_id"):
        evaluate_news_macro_risk(
            build_structured_summary([], []),
            decision_id=" ",
        )


def test_accepts_pre_shaped_context() -> None:
    context = NewsMacroRiskContext(
        aggregate_sentiment_score=-0.5,
        worst_sentiment="negative",
        negative_count=2,
        headline_count=3,
        macro_indicator_count=1,
        data_versions=("news-v1",),
    )

    decision = evaluate_news_macro_risk(context, decision_id="rctx_mirror")

    assert decision.requires_human_review is True
    assert RISK_TAG_NEGATIVE_NEWS in decision.risk_tags
    assert decision.suggested_max_position_multiplier == 1.0
    assert decision.context_id == "news-v1"


def test_default_thresholds_match_published_constants() -> None:
    assert NEGATIVE_SENTIMENT_FLOOR == -0.2
    assert MACRO_HIGH_RISK_INDICATOR_COUNT == 4
    assert 0.0 < MACRO_HIGH_RISK_POSITION_MULTIPLIER <= 1.0


def test_decision_is_immutable_and_frozen() -> None:
    decision = evaluate_news_macro_risk(
        build_structured_summary([], []),
        decision_id="rctx_imm",
    )

    with pytest.raises(ValidationError):
        decision.requires_human_review = True


def test_decision_rejects_blank_decision_id_in_constructor() -> None:
    with pytest.raises(ValidationError):
        RiskContextDecision(decision_id="")


def test_decision_rejects_blank_tag_entry() -> None:
    with pytest.raises(ValidationError):
        RiskContextDecision(decision_id="rctx_x", risk_tags=("",))


def test_decision_multiplier_above_one_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RiskContextDecision(
            decision_id="rctx_x",
            suggested_max_position_multiplier=1.5,
        )


def test_decision_multiplier_zero_or_negative_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RiskContextDecision(
            decision_id="rctx_x",
            suggested_max_position_multiplier=0.0,
        )


def test_context_mirror_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        NewsMacroRiskContext.model_validate(
            {"negative_count": 0, "unknown_field": True},
        )


def test_decision_context_id_uses_first_data_version() -> None:
    summary = build_structured_summary(
        [_headline("h1", "neutral", data_version="v9")],
        [_indicator("fred:CPI")],
    )

    decision = evaluate_news_macro_risk(summary, decision_id="rctx_v9")

    assert decision.context_id == "v9"


def test_decision_for_unknown_only_sentiment_is_neutral() -> None:
    # All unknown → no aggregate score, no worst sentiment; layer is
    # conservative and treats unknown as not-negative.
    summary = build_structured_summary(
        [_headline("h1", None), _headline("h2", None)],
        [],
    )

    decision = evaluate_news_macro_risk(summary, decision_id="rctx_unknown")

    assert decision.requires_human_review is False
    assert decision.risk_tags == ()
    assert decision.suggested_max_position_multiplier == 1.0
