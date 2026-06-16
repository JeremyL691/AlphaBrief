"""News/Macro risk-context layer for AlphaBrief.

This module is a **read-only**, deterministic adapter from
:class:`alphabrief_research.ResearchContextSummary` into audit-friendly
risk metadata. It does **not** call ModelGateway, read from a database,
or invoke any external provider. It does **not** modify
:class:`alphabrief_risk.RiskGate` core semantics.

The output is **advisory metadata only**. Downstream consumers (the
risk API/CLI, the dashboard, or a wrapper around :class:`RiskGate`)
may use the output to *tighten* risk: flip on
``requires_human_review``, add risk tags, or multiply
``max_position_pct`` down. The decision can never relax existing
limits — positive news or empty data return a neutral decision
identical to the no-input default.
"""

from __future__ import annotations

from typing import Final

from alphabrief_research import ResearchContextSummary
from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Aggregate sentiment-score lower bound (inclusive) below which the
#: news context is treated as negative. ``-0.2`` is intentionally
#: conservative so a mildly negative aggregate (e.g. ``(1-2)/4 = -0.25``)
#: still flags for human review.
NEGATIVE_SENTIMENT_FLOOR: Final[float] = -0.2

#: Macro indicator count strictly above which the macro context is
#: treated as "high risk" (many indicators, no concentration).
MACRO_HIGH_RISK_INDICATOR_COUNT: Final[int] = 4

#: Risk tag emitted when the news context is considered negative.
RISK_TAG_NEGATIVE_NEWS: Final[str] = "negative_news_context"

#: Risk tag emitted when the macro context is treated as high risk.
RISK_TAG_MACRO_HIGH_RISK: Final[str] = "macro_high_risk"

#: Risk tag emitted when the decision requires human review.
RISK_TAG_HUMAN_REVIEW: Final[str] = "requires_human_review"

#: Risk tag emitted when the decision suggests a position-size reduction.
RISK_TAG_POSITION_REDUCTION: Final[str] = "suggested_position_reduction"

#: Suggested multiplier when the macro context is treated as high risk.
#: ``0.5`` halves the configured max position. Chosen as a round,
#: moderate tightening that downstream code can choose to apply or
#: surface to a human reviewer.
MACRO_HIGH_RISK_POSITION_MULTIPLIER: Final[float] = 0.5


class NewsMacroRiskContext(BaseModel):
    """Input mirror of the news/macro fields that drive risk tightening.

    Consumers who do not want to import
    :class:`alphabrief_research.ResearchContextSummary` directly can
    construct this lighter Pydantic model and pass it to
    :func:`evaluate_news_macro_risk`. All fields are optional with
    safe defaults so the schema remains backward compatible.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    aggregate_sentiment_score: float | None = Field(default=None, ge=-1.0, le=1.0)
    worst_sentiment: str | None = None
    negative_count: int = Field(default=0, ge=0)
    headline_count: int = Field(default=0, ge=0)
    macro_indicator_count: int = Field(default=0, ge=0)
    data_versions: tuple[str, ...] = Field(default_factory=tuple)


class RiskContextDecision(BaseModel):
    """Deterministic, tighten-only risk metadata output.

    The decision is **advisory** and **never relaxes** existing risk
    limits. Downstream code may use it to flip
    ``requires_human_review=True`` on a :class:`RiskDecision`, to
    surface additional ``risk_tags``, or to multiply
    ``max_position_pct`` down by ``suggested_max_position_multiplier``.

    Invariants
    ----------
    * ``suggested_max_position_multiplier`` is always in ``(0.0, 1.0]``
      and defaults to ``1.0`` (no change). It can never be greater
      than ``1.0`` because the layer must not relax limits.
    * ``requires_human_review`` defaults to ``False`` and is only ever
      flipped to ``True``.
    * ``risk_tags`` is a deterministic tuple ordered by trigger order;
      positive or empty input does not produce any tags.
    * ``source_summary_untrusted`` is always ``True`` so downstream
      surfaces remember that the underlying data is external.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    requires_human_review: bool = False
    risk_tags: tuple[str, ...] = Field(default_factory=tuple)
    suggested_max_position_multiplier: float = Field(
        default=1.0,
        gt=0.0,
        le=1.0,
    )
    notes: tuple[str, ...] = Field(default_factory=tuple)
    source_summary_untrusted: bool = True
    decision_id: str = Field(min_length=1)
    context_id: str = Field(default="", min_length=0)

    @field_validator("risk_tags", "notes")
    @classmethod
    def _items_must_not_be_blank(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            if not isinstance(item, str) or item.strip() == "":
                raise ValueError("risk tag/note entries must be non-empty strings")
        return value


def _to_context(
    source: ResearchContextSummary | NewsMacroRiskContext,
) -> NewsMacroRiskContext:
    """Project a :class:`ResearchContextSummary` (or pre-shaped mirror)
    into the lightweight :class:`NewsMacroRiskContext`.
    """
    if isinstance(source, NewsMacroRiskContext):
        return source
    return NewsMacroRiskContext(
        aggregate_sentiment_score=source.aggregate_sentiment_score,
        worst_sentiment=source.worst_sentiment,
        negative_count=source.negative_count,
        headline_count=source.headline_count,
        macro_indicator_count=len(source.macro_indicator_ids),
        data_versions=tuple(source.data_versions),
    )


def evaluate_news_macro_risk(
    source: ResearchContextSummary | NewsMacroRiskContext,
    *,
    decision_id: str = "rctx_001",
    negative_floor: float = NEGATIVE_SENTIMENT_FLOOR,
    macro_high_risk_indicator_count: int = MACRO_HIGH_RISK_INDICATOR_COUNT,
    macro_position_multiplier: float = MACRO_HIGH_RISK_POSITION_MULTIPLIER,
) -> RiskContextDecision:
    """Evaluate a :class:`ResearchContextSummary` (or its mirror) into
    deterministic, tighten-only risk metadata.

    The function is pure and deterministic. It does not read from a
    database, call ModelGateway, or invoke any provider. It may only
    **tighten** risk:

    * **Negative news** (``aggregate_sentiment_score < negative_floor``
      or ``worst_sentiment == "negative"``) → ``requires_human_review``
      is flipped on, ``RISK_TAG_NEGATIVE_NEWS`` is added, and
      ``RISK_TAG_HUMAN_REVIEW`` is added.
    * **High macro risk** (``macro_indicator_count >
      macro_high_risk_indicator_count``) → ``RISK_TAG_MACRO_HIGH_RISK``
      is added and ``suggested_max_position_multiplier`` is reduced to
      ``macro_position_multiplier``.
    * **Both** → all of the above combine.
    * **Empty / positive / stable input** → returns the identity
      decision (``requires_human_review=False``, no tags, multiplier
      ``1.0``). The function never relaxes existing limits.

    Parameters
    ----------
    source
        The news/macro summary to evaluate. Either the full
        :class:`ResearchContextSummary` from the research layer or a
        pre-shaped :class:`NewsMacroRiskContext`.
    decision_id
        Identifier for the produced decision. Useful for audit logs.
    negative_floor
        Threshold below which the aggregate sentiment score is treated
        as negative. Defaults to :data:`NEGATIVE_SENTIMENT_FLOOR`
        (``-0.2``).
    macro_high_risk_indicator_count
        Indicator count strictly above which the macro context is
        treated as high risk. Defaults to
        :data:`MACRO_HIGH_RISK_INDICATOR_COUNT` (``4``).
    macro_position_multiplier
        Position multiplier suggested when the macro context is high
        risk. Must be in ``(0.0, 1.0]``. Defaults to
        :data:`MACRO_HIGH_RISK_POSITION_MULTIPLIER` (``0.5``).
    """
    if not isinstance(decision_id, str) or decision_id.strip() == "":
        raise ValueError("decision_id must be a non-empty string")
    if not (0.0 < macro_position_multiplier <= 1.0):
        raise ValueError(
            "macro_position_multiplier must be in (0.0, 1.0]; the layer cannot relax"
        )

    context = _to_context(source)

    tags: list[str] = []
    notes: list[str] = []
    requires_human_review = False
    multiplier = 1.0

    # Negative news: prefer the explicit worst_sentiment label, but
    # also flag on aggregate sentiment if it is below the floor. Both
    # conditions combine; either alone is sufficient to flip review.
    is_negative_label = context.worst_sentiment == "negative"
    score = context.aggregate_sentiment_score
    is_negative_score = (
        score is not None and score < negative_floor
    )
    if is_negative_label or is_negative_score:
        requires_human_review = True
        tags.append(RISK_TAG_NEGATIVE_NEWS)
        tags.append(RISK_TAG_HUMAN_REVIEW)
        reasons: list[str] = []
        if is_negative_label:
            reasons.append("worst_sentiment=negative")
        if is_negative_score and score is not None:
            reasons.append(
                f"aggregate_sentiment_score={score:.3f}<{negative_floor:.3f}"
            )
        notes.append(
            "negative news context: " + ", ".join(reasons)
        )

    # High macro risk: many indicators, no concentration.
    if context.macro_indicator_count > macro_high_risk_indicator_count:
        tags.append(RISK_TAG_MACRO_HIGH_RISK)
        tags.append(RISK_TAG_POSITION_REDUCTION)
        multiplier = macro_position_multiplier
        notes.append(
            "macro indicator count "
            f"{context.macro_indicator_count} > "
            f"{macro_high_risk_indicator_count}"
        )

    context_id = (
        context.data_versions[0] if context.data_versions else ""
    )

    return RiskContextDecision(
        requires_human_review=requires_human_review,
        risk_tags=tuple(tags),
        suggested_max_position_multiplier=multiplier,
        notes=tuple(notes),
        source_summary_untrusted=True,
        decision_id=decision_id,
        context_id=context_id,
    )


__all__ = [
    "MACRO_HIGH_RISK_INDICATOR_COUNT",
    "MACRO_HIGH_RISK_POSITION_MULTIPLIER",
    "NEGATIVE_SENTIMENT_FLOOR",
    "NewsMacroRiskContext",
    "RISK_TAG_HUMAN_REVIEW",
    "RISK_TAG_MACRO_HIGH_RISK",
    "RISK_TAG_NEGATIVE_NEWS",
    "RISK_TAG_POSITION_REDUCTION",
    "RiskContextDecision",
    "evaluate_news_macro_risk",
]
