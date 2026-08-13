"""M08-W05: spread, liquidity, news, and macro tightening.

Covers:
- boundary tests for spread absolute and relative limits, quoted
  liquidity, projected slippage, high-impact event windows, affected
  currencies and categories, sentiment severity, coverage, disagreement,
  freshness, and uncertainty (AC-M08-W05-01);
- the context policy is deterministic and tighten-only — no model score,
  narrative, committee confidence, or external text can increase size,
  relax a rule, or modify its thresholds (AC-M08-W05-02);
- missing or stale critical market or content context yields the
  configured reject or conservative clamp and never a fabricated
  neutral score, disabled rule, fallback content, or user question
  (AC-M08-W05-03).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest
from alphabrief_risk.market_conditions import (
    CONSERVATIVE_CLAMP_MULTIPLIER,
    EventWindowEvidence,
    LiquidityEvidence,
    MarketConditionLimits,
    MarketConditionVerdict,
    MarketRuleResult,
    SentimentEvidence,
    SlippageEvidence,
    SpreadEvidence,
    evaluate_market_conditions,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
SYMBOL = "EUR_USD"
CURRENCY = "EUR"
CATEGORY = "CURRENCY"


def _spread(*, bid: str = "1.10000", ask: str = "1.10020") -> SpreadEvidence:
    return SpreadEvidence(
        symbol=SYMBOL,
        bid=Decimal(bid),
        ask=Decimal(ask),
        captured_at=NOW,
        source_id="px-1",
    )


def _liquidity(
    volume: str | None = "1000000",
) -> LiquidityEvidence:
    return LiquidityEvidence(
        symbol=SYMBOL,
        quoted_volume=Decimal(volume) if volume is not None else None,
        captured_at=NOW,
        source_id="liq-1",
    )


def _slippage(
    pct: str | None = "0.001",
) -> SlippageEvidence:
    return SlippageEvidence(
        symbol=SYMBOL,
        expected_slippage_pct=Decimal(pct) if pct is not None else None,
        captured_at=NOW,
        source_id="slip-1",
    )


def _sentiment(**overrides: object) -> SentimentEvidence:
    payload: dict[str, object] = {
        "aggregate_score": Decimal("0.2"),
        "coverage_fraction": Decimal("0.8"),
        "disagreement": Decimal("0.2"),
        "uncertainty": Decimal("0.1"),
        "captured_at": NOW,
        "source_id": "sent-1",
    }
    payload.update(overrides)
    return SentimentEvidence.model_validate(payload)


def _limits(**overrides: object) -> MarketConditionLimits:
    return MarketConditionLimits.model_validate(overrides)


_UNSET = object()


def _evaluate(
    *,
    spread: object = _UNSET,
    liquidity: object = _UNSET,
    slippage: object = _UNSET,
    events: tuple[EventWindowEvidence, ...] = (),
    sentiment: SentimentEvidence | None = None,
    limits: MarketConditionLimits | None = None,
    now: datetime = NOW,
) -> tuple[dict[str, MarketRuleResult], MarketConditionVerdict]:
    resolved_spread = cast(
        SpreadEvidence | None, _spread() if spread is _UNSET else spread
    )
    resolved_liquidity = cast(
        LiquidityEvidence | None, _liquidity() if liquidity is _UNSET else liquidity
    )
    resolved_slippage = cast(
        SlippageEvidence | None, _slippage() if slippage is _UNSET else slippage
    )
    verdict = evaluate_market_conditions(
        symbol=SYMBOL,
        currency=CURRENCY,
        category=CATEGORY,
        spread=resolved_spread,
        liquidity=resolved_liquidity,
        slippage=resolved_slippage,
        events=events,
        sentiment=sentiment,
        limits=limits or _limits(),
        clock=lambda: now,
    )
    rules = {result.rule: result for result in verdict.results}
    return rules, verdict


def _rule(
    rules: dict[str, MarketRuleResult], name: str
) -> MarketRuleResult:
    return rules[name]


# ---------------------------------------------------------------------------
# AC-M08-W05-01: boundary tests for every rule
# ---------------------------------------------------------------------------


def test_spread_absolute_boundary() -> None:
    rules, _ = _evaluate(
        limits=_limits(max_absolute_spread=Decimal("0.0003"))
    )
    # spread 0.00020 <= 0.0003.
    assert _rule(rules, "spread_absolute").passed is True
    rules, _ = _evaluate(
        spread=_spread(ask="1.10050"),
        limits=_limits(max_absolute_spread=Decimal("0.0003")),
    )
    assert _rule(rules, "spread_absolute").passed is False


def test_spread_relative_boundary() -> None:
    rules, _ = _evaluate(
        limits=_limits(max_relative_spread=Decimal("0.001"))
    )
    # (0.00020 / ~1.1001) ~ 0.000182 <= 0.001.
    assert _rule(rules, "spread_relative").passed is True
    rules, _ = _evaluate(
        spread=_spread(bid="1.10000", ask="1.11000"),
        limits=_limits(max_relative_spread=Decimal("0.001")),
    )
    assert _rule(rules, "spread_relative").passed is False


def test_liquidity_boundary() -> None:
    rules, _ = _evaluate(
        limits=_limits(min_liquidity_volume=Decimal("1000000"))
    )
    assert _rule(rules, "liquidity").passed is True
    rules, _ = _evaluate(
        liquidity=_liquidity("500000"),
        limits=_limits(min_liquidity_volume=Decimal("1000000")),
    )
    assert _rule(rules, "liquidity").passed is False


def test_slippage_boundary() -> None:
    rules, _ = _evaluate(limits=_limits(max_slippage_pct=Decimal("0.005")))
    assert _rule(rules, "slippage").passed is True
    rules, _ = _evaluate(
        slippage=_slippage("0.01"),
        limits=_limits(max_slippage_pct=Decimal("0.005")),
    )
    assert _rule(rules, "slippage").passed is False


def _event(**overrides: object) -> EventWindowEvidence:
    payload: dict[str, object] = {
        "event_id": "evt-1",
        "affected_currencies": ("EUR",),
        "severity": "high",
        "start_at": NOW - timedelta(minutes=1),
        "end_at": NOW + timedelta(minutes=30),
        "source_id": "cal-1",
    }
    payload.update(overrides)
    return EventWindowEvidence.model_validate(payload)


def test_event_window_rejects_affected_symbol_currency_category() -> None:
    rules, verdict = _evaluate(
        events=(_event(),),
        limits=_limits(high_impact_event_policy="reject"),
    )
    assert _rule(rules, "event_window").passed is False
    assert verdict.rejected is True
    # Currency-affected without symbol match.
    rules, _ = _evaluate(
        events=(_event(affected_currencies=("EUR",)),),
        limits=_limits(high_impact_event_policy="reject"),
    )
    assert _rule(rules, "event_window").passed is False
    # Category-affected.
    rules, _ = _evaluate(
        events=(
            _event(
                affected_symbols=(),
                affected_currencies=(),
                affected_categories=("CURRENCY",),
            ),
        ),
        limits=_limits(high_impact_event_policy="reject"),
    )
    assert _rule(rules, "event_window").passed is False


def test_event_window_passes_outside_window_and_unaffected() -> None:
    rules, _ = _evaluate(
        events=(_event(affected_currencies=("GBP",)),),
        limits=_limits(high_impact_event_policy="reject"),
    )
    assert _rule(rules, "event_window").passed is True
    rules, _ = _evaluate(
        events=(
            _event(
                start_at=NOW - timedelta(hours=2),
                end_at=NOW - timedelta(hours=1),
            ),
        ),
        limits=_limits(high_impact_event_policy="reject"),
    )
    assert _rule(rules, "event_window").passed is True


def test_event_window_clamp_policy_applies_conservative_multiplier() -> None:
    rules, verdict = _evaluate(
        events=(_event(),),
        limits=_limits(
            high_impact_event_policy="clamp",
            event_clamp_multiplier=Decimal("0.5"),
        ),
    )
    assert _rule(rules, "event_window").passed is False
    assert verdict.rejected is False
    assert verdict.size_multiplier == Decimal("0.5")


def test_sentiment_freshness_boundary() -> None:
    rules, verdict = _evaluate(
        sentiment=_sentiment(),
        limits=_limits(max_sentiment_age_seconds=300),
    )
    assert _rule(rules, "sentiment_freshness").passed is True
    assert verdict.size_multiplier == Decimal("1")
    rules, verdict = _evaluate(
        sentiment=_sentiment(captured_at=NOW - timedelta(seconds=600)),
        limits=_limits(max_sentiment_age_seconds=300),
    )
    assert _rule(rules, "sentiment_freshness").passed is False
    assert verdict.size_multiplier == CONSERVATIVE_CLAMP_MULTIPLIER


def test_sentiment_coverage_disagreement_uncertainty_clamp() -> None:
    rules, verdict = _evaluate(
        sentiment=_sentiment(coverage_fraction=Decimal("0.3")),
        limits=_limits(min_sentiment_coverage=Decimal("0.6")),
    )
    assert _rule(rules, "sentiment_coverage").passed is False
    assert verdict.size_multiplier == CONSERVATIVE_CLAMP_MULTIPLIER
    rules, verdict = _evaluate(
        sentiment=_sentiment(disagreement=Decimal("0.9")),
        limits=_limits(max_sentiment_disagreement=Decimal("0.5")),
    )
    assert _rule(rules, "sentiment_disagreement").passed is False
    assert verdict.size_multiplier == CONSERVATIVE_CLAMP_MULTIPLIER
    rules, verdict = _evaluate(
        sentiment=_sentiment(uncertainty=Decimal("0.9")),
        limits=_limits(max_sentiment_uncertainty=Decimal("0.5")),
    )
    assert _rule(rules, "sentiment_uncertainty").passed is False
    assert verdict.size_multiplier == CONSERVATIVE_CLAMP_MULTIPLIER


def test_sentiment_severity_rejects_below_floor() -> None:
    rules, verdict = _evaluate(
        sentiment=_sentiment(aggregate_score=Decimal("-0.3")),
        limits=_limits(negative_sentiment_floor=Decimal("-0.2")),
    )
    assert _rule(rules, "sentiment_severity").passed is False
    assert verdict.rejected is True
    rules, _ = _evaluate(
        sentiment=_sentiment(aggregate_score=Decimal("-0.1")),
        limits=_limits(negative_sentiment_floor=Decimal("-0.2")),
    )
    assert _rule(rules, "sentiment_severity").passed is True


# ---------------------------------------------------------------------------
# AC-M08-W05-02: deterministic, tighten-only, no external text influence
# ---------------------------------------------------------------------------


def test_multiplier_is_always_tighten_only() -> None:
    for limits in (
        _limits(
            max_absolute_spread=Decimal("0.0003"),
            max_relative_spread=Decimal("0.001"),
            min_liquidity_volume=Decimal("1000000"),
            max_slippage_pct=Decimal("0.005"),
            high_impact_event_policy="clamp",
            event_clamp_multiplier=Decimal("0.5"),
            max_sentiment_age_seconds=300,
            min_sentiment_coverage=Decimal("0.6"),
            max_sentiment_disagreement=Decimal("0.5"),
            max_sentiment_uncertainty=Decimal("0.5"),
            negative_sentiment_floor=Decimal("-0.2"),
        ),
        _limits(
            max_absolute_spread=Decimal("0.0001"),
            max_sentiment_age_seconds=60,
            negative_sentiment_floor=Decimal("0"),
        ),
    ):
        rules, verdict = _evaluate(
            sentiment=_sentiment(),
            limits=limits,
        )
        assert verdict.tighten_only is True
        assert verdict.size_multiplier <= Decimal("1")


def test_event_clamp_multiplier_cannot_relax() -> None:
    with pytest.raises(ValueError):
        _limits(
            high_impact_event_policy="clamp",
            event_clamp_multiplier=Decimal("1.5"),
        )
    with pytest.raises(ValueError):
        _limits(
            high_impact_event_policy="clamp",
            event_clamp_multiplier=Decimal("0"),
        )


def test_no_free_text_inputs_exist() -> None:
    """No model score, narrative, or committee confidence field exists in
    the evidence models — external text cannot influence any rule."""
    for model in (
        SpreadEvidence,
        LiquidityEvidence,
        SlippageEvidence,
        SentimentEvidence,
        EventWindowEvidence,
    ):
        fields = model.model_fields
        assert "narrative" not in fields
        assert "text" not in fields
        assert "confidence" not in fields
        assert "commentary" not in fields


# ---------------------------------------------------------------------------
# AC-M08-W05-03: missing/stale evidence fails closed
# ---------------------------------------------------------------------------


def test_missing_critical_market_evidence_rejects() -> None:
    rules, verdict = _evaluate(
        spread=None,
        limits=_limits(max_absolute_spread=Decimal("0.0003")),
    )
    assert _rule(rules, "spread_absolute").passed is False
    assert "missing" in _rule(rules, "spread_absolute").detail
    assert verdict.rejected is True
    rules, _ = _evaluate(
        liquidity=None,
        limits=_limits(min_liquidity_volume=Decimal("1000000")),
    )
    assert _rule(rules, "liquidity").passed is False
    rules, _ = _evaluate(
        slippage=_slippage(None),
        limits=_limits(max_slippage_pct=Decimal("0.005")),
    )
    assert _rule(rules, "slippage").passed is False


def test_missing_event_calendar_fails_closed_when_policy_configured() -> None:
    rules, verdict = _evaluate(
        events=(),
        limits=_limits(high_impact_event_policy="reject"),
    )
    assert _rule(rules, "event_window").passed is False
    assert "fails closed" in _rule(rules, "event_window").detail
    assert verdict.rejected is True


def test_missing_sentiment_evidence_clamps_never_neutral() -> None:
    rules, verdict = _evaluate(
        sentiment=None,
        limits=_limits(
            max_sentiment_age_seconds=300,
            min_sentiment_coverage=Decimal("0.6"),
            negative_sentiment_floor=Decimal("-0.2"),
        ),
    )
    # Missing freshness/coverage clamp; missing severity score rejects.
    assert _rule(rules, "sentiment_freshness").passed is False
    assert (
        _rule(rules, "sentiment_freshness").multiplier
        == CONSERVATIVE_CLAMP_MULTIPLIER
    )
    assert _rule(rules, "sentiment_coverage").passed is False
    assert _rule(rules, "sentiment_severity").passed is False
    # The severity rule rejects outright — no fabricated neutral score.
    assert verdict.rejected is True


def test_unconfigured_limits_emit_no_results() -> None:
    rules, verdict = _evaluate()
    assert rules == {}
    assert verdict.size_multiplier == Decimal("1")
    assert verdict.rejected is False
