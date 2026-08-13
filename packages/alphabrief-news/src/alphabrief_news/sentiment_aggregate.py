"""Explainable multi-scope sentiment aggregation (M09-W04).

Replaces single-score sentiment with deterministic evidence-backed
aggregates for the whole market, asset classes, currencies, countries,
companies, and instruments (REQ-NEWS-003, REQ-NEWS-005). Every
aggregate exposes direction, intensity, disagreement, sample count,
source coverage, freshness, uncertainty, evidence IDs, and algorithm
version (AC-M09-W04-01). Reordering identical input evidence produces
byte-equivalent normalized output and the same snapshot hash
(AC-M09-W04-02). Sparse, contradictory, stale, and single-source
fixtures produce explicit uncertainty or insufficient-coverage verdicts
instead of confident defaults (AC-M09-W04-03).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

SentimentScope = Literal[
    "market",
    "asset_class",
    "currency",
    "country",
    "company",
    "instrument",
]
Direction = Literal["positive", "negative", "neutral", "mixed"]
SampleDirection = Literal["positive", "negative", "neutral"]

#: The deterministic aggregation algorithm version.
SENTIMENT_ALGORITHM_VERSION = "2026-08-13.1"

#: Minimum samples and distinct sources for a confident coverage verdict.
DEFAULT_MIN_SAMPLES = 3
DEFAULT_MIN_SOURCES = 2

#: Maximum accepted evidence age (seconds) before the aggregate is stale.
DEFAULT_MAX_AGE_SECONDS = 86400

#: Uncertainty floor applied to insufficient-coverage aggregates.
INSUFFICIENT_COVERAGE_UNCERTAINTY = Decimal("0.75")


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("sentiment decimal values must not be floats")
    return value


class SentimentSample(BaseModel):
    """One immutable evidence sample."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(min_length=1)
    scope: SentimentScope
    scope_value: str = Field(min_length=1)
    direction: SampleDirection
    intensity: Decimal = Field(ge=0, le=1)
    source: str = Field(min_length=1)
    captured_at: datetime

    @field_validator("intensity", mode="before")
    @classmethod
    def intensity_must_not_be_float(cls, value: Any) -> Any:
        return _reject_float(value)

    @field_validator("captured_at", mode="before")
    @classmethod
    def time_must_be_utc(cls, value: Any) -> Any:
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif isinstance(value, datetime):
            parsed = value
        else:
            raise ValueError("sample times must be datetimes")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)


class SentimentAggregate(BaseModel):
    """One deterministic multi-scope sentiment aggregate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: SentimentScope
    scope_value: str = Field(min_length=1)
    direction: Direction
    intensity: Decimal
    disagreement: Decimal
    sample_count: int
    source_coverage: Decimal
    freshness_seconds: Decimal | None = None
    uncertainty: Decimal
    coverage_sufficient: bool
    evidence_ids: tuple[str, ...] = ()
    algorithm_version: str = SENTIMENT_ALGORITHM_VERSION
    snapshot_hash: str = Field(min_length=1)


def _signed(direction: SampleDirection, intensity: Decimal) -> Decimal:
    if direction == "positive":
        return intensity
    if direction == "negative":
        return -intensity
    return Decimal("0")


def aggregate_sentiment(
    samples: list[SentimentSample],
    *,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    min_sources: int = DEFAULT_MIN_SOURCES,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    algorithm_version: str = SENTIMENT_ALGORITHM_VERSION,
    now: datetime | None = None,
) -> tuple[SentimentAggregate, ...]:
    """Aggregate sentiment per scope, deterministically.

    Input order never matters: samples are sorted by scope and evidence
    ID before any computation, so reordering identical input produces
    byte-equivalent normalized output and the same snapshot hash
    (AC-M09-W04-02).
    """
    observed_at = now or datetime.now(UTC)
    ordered = sorted(samples, key=lambda s: (s.scope, s.scope_value, s.evidence_id))
    by_scope: dict[tuple[str, str], list[SentimentSample]] = {}
    for sample in ordered:
        by_scope.setdefault((sample.scope, sample.scope_value), []).append(sample)

    aggregates: list[SentimentAggregate] = []
    for (scope, scope_value), group in by_scope.items():
        signed = [_signed(s.direction, s.intensity) for s in group]
        mean_signed = sum(signed, Decimal("0")) / Decimal(len(signed))
        intensity = sum(
            (abs(value) for value in signed), Decimal("0")
        ) / Decimal(len(signed))
        disagreement = Decimal("1") - abs(mean_signed)
        sources = {sample.source for sample in group}
        source_coverage = Decimal(len(sources)) / Decimal(len(group))
        oldest = min(sample.captured_at for sample in group)
        freshness_seconds = (observed_at - oldest).total_seconds()
        stale_ratio = Decimal(
            max(0, freshness_seconds - max_age_seconds)
        ) / Decimal(max_age_seconds)
        stale_ratio = min(Decimal("1"), stale_ratio)
        coverage_sufficient = (
            len(group) >= min_samples
            and len(sources) >= min_sources
            and freshness_seconds <= max_age_seconds
        )
        uncertainty = (
            Decimal("0.5") * disagreement
            + Decimal("0.3") * (Decimal("1") - source_coverage)
            + Decimal("0.2") * stale_ratio
        )
        uncertainty = min(Decimal("1"), max(Decimal("0"), uncertainty))
        if not coverage_sufficient:
            direction: Direction = "mixed"
            uncertainty = max(uncertainty, INSUFFICIENT_COVERAGE_UNCERTAINTY)
        elif abs(mean_signed) <= Decimal("0.4") and disagreement >= Decimal("0.6"):
            direction = "mixed"
        elif mean_signed > Decimal("0"):
            direction = "positive"
        elif mean_signed < Decimal("0"):
            direction = "negative"
        else:
            direction = "neutral"

        aggregate = SentimentAggregate(
            scope=cast(SentimentScope, scope),
            scope_value=scope_value,
            direction=direction,
            intensity=intensity,
            disagreement=disagreement,
            sample_count=len(group),
            source_coverage=source_coverage,
            freshness_seconds=Decimal(str(round(freshness_seconds, 1))),
            uncertainty=uncertainty,
            coverage_sufficient=coverage_sufficient,
            evidence_ids=tuple(sample.evidence_id for sample in group),
            algorithm_version=algorithm_version,
            snapshot_hash="pending",
        )
        aggregates.append(aggregate)

    aggregates = sorted(
        aggregates, key=lambda a: (a.scope, a.scope_value)
    )
    snapshot_hash = _snapshot_hash(aggregates)
    return tuple(
        aggregate.model_copy(update={"snapshot_hash": snapshot_hash})
        for aggregate in aggregates
    )


def _snapshot_hash(aggregates: list[SentimentAggregate]) -> str:
    """One deterministic snapshot hash over the normalized output."""
    normalized = [
        json.dumps(
            aggregate.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        for aggregate in aggregates
    ]
    return hashlib.sha256(
        "\n".join(normalized).encode("utf-8")
    ).hexdigest()


__all__ = [
    "DEFAULT_MAX_AGE_SECONDS",
    "DEFAULT_MIN_SAMPLES",
    "DEFAULT_MIN_SOURCES",
    "INSUFFICIENT_COVERAGE_UNCERTAINTY",
    "SENTIMENT_ALGORITHM_VERSION",
    "SentimentAggregate",
    "SentimentSample",
    "SentimentScope",
    "aggregate_sentiment",
]
