"""Deterministic spread, liquidity, news, and macro tightening (M08-W05).

Applies versioned spread, liquidity, slippage, news-event, macro-window,
sentiment-coverage, and stale-content rules that can only reduce size or
reject (REQ-RISK-004, REQ-RISK-005). The policy is deterministic and
tighten-only: the verdict's ``size_multiplier`` is always in ``(0, 1]``
and a rejected rule forces ``0``. No model score, narrative, committee
confidence, or external text is accepted anywhere — evidence is strictly
typed structured facts, so no external input can increase size, relax a
rule, or modify its thresholds (AC-M08-W05-02).

Missing or stale critical market or content context yields the
configured reject or a conservative clamp — never a fabricated neutral
score, a disabled rule, fallback content, or a user question
(AC-M08-W05-03).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Conservative multiplier applied when sentiment evidence is missing or
#: stale (tighten-only, never above 1.0).
CONSERVATIVE_CLAMP_MULTIPLIER = Decimal("0.5")


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("market condition decimal values must not be floats")
    return value


class SpreadEvidence(BaseModel):
    """One bid/ask spread observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    bid: Decimal = Field(gt=0)
    ask: Decimal = Field(gt=0)
    captured_at: datetime
    source_id: str = Field(min_length=1)

    @field_validator("bid", "ask", mode="before")
    @classmethod
    def decimals_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid

    @property
    def relative_spread(self) -> Decimal:
        mid = (self.bid + self.ask) / Decimal("2")
        return (self.ask - self.bid) / mid


class LiquidityEvidence(BaseModel):
    """One quoted-liquidity observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    quoted_volume: Decimal | None = None
    captured_at: datetime
    source_id: str = Field(min_length=1)

    @field_validator("quoted_volume", mode="before")
    @classmethod
    def volume_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class SlippageEvidence(BaseModel):
    """One projected-slippage observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    expected_slippage_pct: Decimal | None = None
    captured_at: datetime
    source_id: str = Field(min_length=1)

    @field_validator("expected_slippage_pct", mode="before")
    @classmethod
    def slippage_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


EventSeverity = Literal["high", "medium", "low"]


class EventWindowEvidence(BaseModel):
    """One scheduled high-impact event window."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    affected_symbols: tuple[str, ...] = ()
    affected_currencies: tuple[str, ...] = ()
    affected_categories: tuple[str, ...] = ()
    severity: EventSeverity = "high"
    start_at: datetime
    end_at: datetime
    source_id: str = Field(min_length=1)


class SentimentEvidence(BaseModel):
    """One structured sentiment observation (no free text)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    aggregate_score: Decimal | None = None
    coverage_fraction: Decimal | None = None
    disagreement: Decimal | None = None
    uncertainty: Decimal | None = None
    captured_at: datetime | None = None
    source_id: str = Field(min_length=1)

    @field_validator(
        "aggregate_score",
        "coverage_fraction",
        "disagreement",
        "uncertainty",
        mode="before",
    )
    @classmethod
    def decimals_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)


class MarketConditionLimits(BaseModel):
    """One deterministic tightening limit set (None = unconfigured)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_absolute_spread: Decimal | None = None
    max_relative_spread: Decimal | None = None
    min_liquidity_volume: Decimal | None = None
    max_slippage_pct: Decimal | None = None
    high_impact_event_policy: Literal["reject", "clamp", "off"] = "off"
    event_clamp_multiplier: Decimal = CONSERVATIVE_CLAMP_MULTIPLIER
    max_sentiment_age_seconds: int | None = None
    min_sentiment_coverage: Decimal | None = None
    max_sentiment_disagreement: Decimal | None = None
    max_sentiment_uncertainty: Decimal | None = None
    negative_sentiment_floor: Decimal | None = None

    @field_validator(
        "max_absolute_spread",
        "max_relative_spread",
        "min_liquidity_volume",
        "max_slippage_pct",
        "min_sentiment_coverage",
        "max_sentiment_disagreement",
        "max_sentiment_uncertainty",
        "negative_sentiment_floor",
        "event_clamp_multiplier",
        mode="before",
    )
    @classmethod
    def limits_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)

    @field_validator("event_clamp_multiplier")
    @classmethod
    def clamp_must_be_tighten_only(
        cls, value: Decimal
    ) -> Decimal:
        if not (Decimal("0") < value <= Decimal("1")):
            raise ValueError(
                "event_clamp_multiplier must be in (0, 1]; tightening only"
            )
        return value


class MarketRuleResult(BaseModel):
    """One stable typed market-rule verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule: str = Field(min_length=1)
    passed: bool
    multiplier: Decimal
    value: str
    ceiling: str
    detail: str = ""


class MarketConditionVerdict(BaseModel):
    """One deterministic tighten-only market verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    results: tuple[MarketRuleResult, ...]
    size_multiplier: Decimal
    rejected: bool

    @property
    def tighten_only(self) -> bool:
        """The multiplier is never above 1.0 (limits only tighten); a
        rejected rule is 0, which is still tighten-only."""
        return Decimal("0") <= self.size_multiplier <= Decimal("1")


def evaluate_market_conditions(
    *,
    symbol: str,
    currency: str,
    category: str,
    spread: SpreadEvidence | None,
    liquidity: LiquidityEvidence | None,
    slippage: SlippageEvidence | None,
    events: tuple[EventWindowEvidence, ...] = (),
    sentiment: SentimentEvidence | None = None,
    limits: MarketConditionLimits,
    clock: Any = None,
) -> MarketConditionVerdict:
    """Evaluate every configured market rule against the evidence.

    Critical market evidence (spread, liquidity, slippage) that is
    missing or fails its limit rejects. Content evidence (sentiment)
    that is missing or stale clamps to a conservative multiplier.
    Event windows reject or clamp per ``high_impact_event_policy``.
    """
    now = clock() if clock is not None else datetime.now(UTC)
    results: list[MarketRuleResult] = []
    symbol = symbol.strip().upper()

    def _add(
        rule: str,
        passed: bool,
        multiplier: Decimal,
        value: str,
        ceiling: str,
        detail: str,
    ) -> None:
        results.append(
            MarketRuleResult(
                rule=rule,
                passed=passed,
                multiplier=multiplier,
                value=value,
                ceiling=ceiling,
                detail=detail,
            )
        )

    def _missing_market(rule: str, ceiling: str) -> None:
        _add(rule, False, Decimal("0"), "unknown", ceiling, "critical evidence missing")

    if limits.max_absolute_spread is not None:
        if spread is None:
            _missing_market("spread_absolute", str(limits.max_absolute_spread))
        else:
            _add(
                "spread_absolute",
                spread.spread <= limits.max_absolute_spread,
                Decimal("0")
                if spread.spread > limits.max_absolute_spread
                else Decimal("1"),
                str(spread.spread),
                str(limits.max_absolute_spread),
                "absolute spread within limit"
                if spread.spread <= limits.max_absolute_spread
                else "absolute spread exceeds limit",
            )

    if limits.max_relative_spread is not None:
        if spread is None:
            _missing_market("spread_relative", str(limits.max_relative_spread))
        else:
            relative = spread.relative_spread
            _add(
                "spread_relative",
                relative <= limits.max_relative_spread,
                Decimal("0") if relative > limits.max_relative_spread else Decimal("1"),
                str(relative),
                str(limits.max_relative_spread),
                "relative spread within limit"
                if relative <= limits.max_relative_spread
                else "relative spread exceeds limit",
            )

    if limits.min_liquidity_volume is not None:
        if liquidity is None or liquidity.quoted_volume is None:
            _missing_market("liquidity", str(limits.min_liquidity_volume))
        else:
            _add(
                "liquidity",
                liquidity.quoted_volume >= limits.min_liquidity_volume,
                Decimal("0")
                if liquidity.quoted_volume < limits.min_liquidity_volume
                else Decimal("1"),
                str(liquidity.quoted_volume),
                str(limits.min_liquidity_volume),
                "quoted liquidity within limit"
                if liquidity.quoted_volume >= limits.min_liquidity_volume
                else "quoted liquidity below limit",
            )

    if limits.max_slippage_pct is not None:
        if slippage is None or slippage.expected_slippage_pct is None:
            _missing_market("slippage", str(limits.max_slippage_pct))
        else:
            expected = slippage.expected_slippage_pct
            _add(
                "slippage",
                expected <= limits.max_slippage_pct,
                Decimal("0") if expected > limits.max_slippage_pct else Decimal("1"),
                str(expected),
                str(limits.max_slippage_pct),
                "projected slippage within limit"
                if expected <= limits.max_slippage_pct
                else "projected slippage exceeds limit",
            )

    if limits.high_impact_event_policy != "off":
        if not events:
            _add(
                "event_window",
                False,
                Decimal("0"),
                "unknown",
                limits.high_impact_event_policy,
                "no event calendar; fails closed",
            )
        else:
            affected = False
            for event in events:
                if not (event.start_at <= now < event.end_at):
                    continue
                if (
                    symbol in event.affected_symbols
                    or currency in event.affected_currencies
                    or category in event.affected_categories
                ):
                    affected = True
                    break
            if affected:
                if limits.high_impact_event_policy == "reject":
                    _add(
                        "event_window",
                        False,
                        Decimal("0"),
                        "affected",
                        "reject",
                        "inside a high-impact event window",
                    )
                else:
                    _add(
                        "event_window",
                        False,
                        limits.event_clamp_multiplier,
                        "affected",
                        "clamp",
                        "inside a high-impact event window; clamped",
                    )
            else:
                _add(
                    "event_window",
                    True,
                    Decimal("1"),
                    "not-affected",
                    limits.high_impact_event_policy,
                    "outside all event windows",
                )

    if limits.max_sentiment_age_seconds is not None:
        if sentiment is None or sentiment.captured_at is None:
            _add(
                "sentiment_freshness",
                False,
                CONSERVATIVE_CLAMP_MULTIPLIER,
                "unknown",
                f"{limits.max_sentiment_age_seconds}s",
                "sentiment evidence missing; clamped",
            )
        else:
            age = (now - sentiment.captured_at).total_seconds()
            fresh = age <= limits.max_sentiment_age_seconds
            _add(
                "sentiment_freshness",
                fresh,
                Decimal("1") if fresh else CONSERVATIVE_CLAMP_MULTIPLIER,
                f"{age:.1f}s",
                f"{limits.max_sentiment_age_seconds}s",
                "sentiment evidence fresh"
                if fresh
                else "sentiment evidence stale; clamped",
            )

    if limits.min_sentiment_coverage is not None:
        if sentiment is None or sentiment.coverage_fraction is None:
            _add(
                "sentiment_coverage",
                False,
                CONSERVATIVE_CLAMP_MULTIPLIER,
                "unknown",
                str(limits.min_sentiment_coverage),
                "sentiment coverage missing; clamped",
            )
        else:
            covered = sentiment.coverage_fraction >= limits.min_sentiment_coverage
            _add(
                "sentiment_coverage",
                covered,
                Decimal("1") if covered else CONSERVATIVE_CLAMP_MULTIPLIER,
                str(sentiment.coverage_fraction),
                str(limits.min_sentiment_coverage),
                "sentiment coverage adequate"
                if covered
                else "sentiment coverage inadequate; clamped",
            )

    if limits.max_sentiment_disagreement is not None:
        if sentiment is None or sentiment.disagreement is None:
            _add(
                "sentiment_disagreement",
                False,
                CONSERVATIVE_CLAMP_MULTIPLIER,
                "unknown",
                str(limits.max_sentiment_disagreement),
                "sentiment disagreement missing; clamped",
            )
        else:
            ok = sentiment.disagreement <= limits.max_sentiment_disagreement
            _add(
                "sentiment_disagreement",
                ok,
                Decimal("1") if ok else CONSERVATIVE_CLAMP_MULTIPLIER,
                str(sentiment.disagreement),
                str(limits.max_sentiment_disagreement),
                "sentiment disagreement within limit"
                if ok
                else "sentiment disagreement high; clamped",
            )

    if limits.max_sentiment_uncertainty is not None:
        if sentiment is None or sentiment.uncertainty is None:
            _add(
                "sentiment_uncertainty",
                False,
                CONSERVATIVE_CLAMP_MULTIPLIER,
                "unknown",
                str(limits.max_sentiment_uncertainty),
                "sentiment uncertainty missing; clamped",
            )
        else:
            ok = sentiment.uncertainty <= limits.max_sentiment_uncertainty
            _add(
                "sentiment_uncertainty",
                ok,
                Decimal("1") if ok else CONSERVATIVE_CLAMP_MULTIPLIER,
                str(sentiment.uncertainty),
                str(limits.max_sentiment_uncertainty),
                "sentiment uncertainty within limit"
                if ok
                else "sentiment uncertainty high; clamped",
            )

    if limits.negative_sentiment_floor is not None:
        if sentiment is None or sentiment.aggregate_score is None:
            _add(
                "sentiment_severity",
                False,
                Decimal("0"),
                "unknown",
                str(limits.negative_sentiment_floor),
                "sentiment score missing; rejects",
            )
        else:
            negative = sentiment.aggregate_score < limits.negative_sentiment_floor
            _add(
                "sentiment_severity",
                not negative,
                Decimal("0") if negative else Decimal("1"),
                str(sentiment.aggregate_score),
                str(limits.negative_sentiment_floor),
                "sentiment severity acceptable"
                if not negative
                else "sentiment severity below floor; rejects",
            )

    multiplier = min(
        (result.multiplier for result in results), default=Decimal("1")
    )
    return MarketConditionVerdict(
        results=tuple(results),
        size_multiplier=multiplier,
        rejected=multiplier == 0,
    )


__all__ = [
    "CONSERVATIVE_CLAMP_MULTIPLIER",
    "EventSeverity",
    "EventWindowEvidence",
    "LiquidityEvidence",
    "MarketConditionLimits",
    "MarketConditionVerdict",
    "MarketRuleResult",
    "SentimentEvidence",
    "SlippageEvidence",
    "SpreadEvidence",
    "evaluate_market_conditions",
]
