"""Deterministic news/macro summary for risk and reporting consumers.

The summary is a plain, audit-friendly projection over stored headlines
and macro indicators. It carries counts, a count-weighted sentiment
score, the source and data-version provenance, and the observed time
window. It never calls a model, never reads anything but the objects it
is given, and never raises on empty input.

Everything in the summary is derived from untrusted external content, so
``untrusted`` is always ``True`` and consumers must treat the payload as
advisory evidence only.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class _HeadlineLike(Protocol):
    """Structural type for a stored headline.

    Declared with read-only properties so concrete records whose
    ``sentiment`` is a narrower literal type still match.
    """

    @property
    def sentiment(self) -> str | None: ...

    @property
    def published_at(self) -> datetime: ...

    @property
    def data_version(self) -> str: ...

    @property
    def source(self) -> str: ...


class _MacroIndicatorLike(Protocol):
    """Structural type for a stored macro indicator."""

    @property
    def indicator_id(self) -> str: ...

    @property
    def data_version(self) -> str: ...


class NewsMacroSummary(BaseModel):
    """One deterministic summary of news and macro evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    headline_count: int = Field(default=0, ge=0)
    positive_count: int = Field(default=0, ge=0)
    negative_count: int = Field(default=0, ge=0)
    neutral_count: int = Field(default=0, ge=0)
    unknown_count: int = Field(default=0, ge=0)
    aggregate_sentiment_score: float | None = Field(default=None, ge=-1.0, le=1.0)
    worst_sentiment: str | None = None
    macro_indicator_ids: tuple[str, ...] = Field(default_factory=tuple)
    data_versions: tuple[str, ...] = Field(default_factory=tuple)
    news_sources: tuple[str, ...] = Field(default_factory=tuple)
    earliest_published_at: datetime | None = None
    latest_published_at: datetime | None = None
    untrusted: bool = True
    generated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe view of the summary."""
        return {
            "headline_count": self.headline_count,
            "positive_count": self.positive_count,
            "negative_count": self.negative_count,
            "neutral_count": self.neutral_count,
            "unknown_count": self.unknown_count,
            "aggregate_sentiment_score": self.aggregate_sentiment_score,
            "worst_sentiment": self.worst_sentiment,
            "macro_indicator_ids": list(self.macro_indicator_ids),
            "data_versions": list(self.data_versions),
            "news_sources": list(self.news_sources),
            "earliest_published_at": (
                self.earliest_published_at.isoformat()
                if self.earliest_published_at is not None
                else None
            ),
            "latest_published_at": (
                self.latest_published_at.isoformat()
                if self.latest_published_at is not None
                else None
            ),
            "untrusted": self.untrusted,
            "generated_at": self.generated_at.isoformat(),
        }


def _sentiment_stats(headlines: Sequence[_HeadlineLike]) -> dict[str, int]:
    stats: dict[str, int] = {"positive": 0, "negative": 0, "neutral": 0, "unknown": 0}
    for headline in headlines:
        label = headline.sentiment
        if label is None:
            stats["unknown"] += 1
        elif label in stats:
            stats[label] += 1
        else:
            stats["unknown"] += 1
    return stats


def _worst_sentiment_label(stats: dict[str, int]) -> str | None:
    """Return the most negative observed label, or ``None`` if all unknown.

    Priority: negative > neutral > positive. ``unknown`` is ignored so
    that "no information" stays distinct from "neutral".
    """
    if stats.get("negative", 0) > 0:
        return "negative"
    if stats.get("neutral", 0) > 0:
        return "neutral"
    if stats.get("positive", 0) > 0:
        return "positive"
    return None


def _aggregate_sentiment_score(stats: dict[str, int]) -> float | None:
    """Count-weighted score in ``[-1.0, 1.0]``.

    The score is ``(positive - negative) / (positive + negative +
    neutral)``. ``unknown`` is excluded so a flood of unanalysed
    headlines cannot drag the score toward zero. Returns ``None`` when
    no positive, negative, or neutral labels were observed.
    """
    positive = stats.get("positive", 0)
    negative = stats.get("negative", 0)
    neutral = stats.get("neutral", 0)
    total = positive + negative + neutral
    if total == 0:
        return None
    score = (positive - negative) / total
    return max(-1.0, min(1.0, score))


def _unique_ordered(items: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return tuple(out)


def build_news_macro_summary(
    headlines: Sequence[_HeadlineLike],
    indicators: Sequence[_MacroIndicatorLike] | None = None,
    *,
    generated_at: datetime | None = None,
) -> NewsMacroSummary:
    """Build a deterministic summary over headlines and macro indicators.

    Empty inputs return a fully populated empty summary; this function
    never raises on empty data.
    """
    stats = _sentiment_stats(headlines)

    earliest: datetime | None = None
    latest: datetime | None = None
    for headline in headlines:
        if earliest is None or headline.published_at < earliest:
            earliest = headline.published_at
        if latest is None or headline.published_at > latest:
            latest = headline.published_at

    macro_ids: list[str] = []
    macro_versions: list[str] = []
    if indicators:
        macro_ids = [indicator.indicator_id for indicator in indicators]
        macro_versions = [indicator.data_version for indicator in indicators]

    return NewsMacroSummary(
        headline_count=len(headlines),
        positive_count=stats.get("positive", 0),
        negative_count=stats.get("negative", 0),
        neutral_count=stats.get("neutral", 0),
        unknown_count=stats.get("unknown", 0),
        aggregate_sentiment_score=_aggregate_sentiment_score(stats),
        worst_sentiment=_worst_sentiment_label(stats),
        macro_indicator_ids=_unique_ordered(macro_ids),
        data_versions=_unique_ordered(
            [headline.data_version for headline in headlines] + macro_versions
        ),
        news_sources=_unique_ordered([headline.source for headline in headlines]),
        earliest_published_at=earliest,
        latest_published_at=latest,
        untrusted=True,
        generated_at=generated_at or datetime.now(UTC),
    )


__all__ = [
    "NewsMacroSummary",
    "build_news_macro_summary",
]
