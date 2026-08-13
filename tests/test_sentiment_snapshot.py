"""M09-W04: explainable multi-scope sentiment aggregation.

- every sentiment aggregate exposes direction, intensity, disagreement,
  sample count, source coverage, freshness, uncertainty, evidence IDs,
  and algorithm version (AC-M09-W04-01);
- reordering identical input evidence produces byte-equivalent
  normalized output and the same snapshot hash (AC-M09-W04-02);
- sparse, contradictory, stale, and single-source fixtures produce
  explicit uncertainty or insufficient-coverage verdicts instead of
  confident defaults (AC-M09-W04-03).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from alphabrief_news.sentiment_aggregate import (
    INSUFFICIENT_COVERAGE_UNCERTAINTY,
    SENTIMENT_ALGORITHM_VERSION,
    SentimentSample,
    aggregate_sentiment,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _sample(**overrides: object) -> SentimentSample:
    payload: dict[str, object] = {
        "evidence_id": "h-1",
        "scope": "instrument",
        "scope_value": "EUR_USD",
        "direction": "positive",
        "intensity": Decimal("0.8"),
        "source": "news-a",
        "captured_at": NOW,
    }
    payload.update(overrides)
    return SentimentSample.model_validate(payload)


def _fixture() -> list[SentimentSample]:
    """Three sources, three samples, one instrument scope."""
    return [
        _sample(evidence_id="h-1", direction="positive", source="news-a"),
        _sample(evidence_id="h-2", direction="positive", source="news-b"),
        _sample(evidence_id="h-3", direction="neutral", source="news-c"),
    ]


# ---------------------------------------------------------------------------
# AC-M09-W04-01: every aggregate exposes the full evidence surface
# ---------------------------------------------------------------------------


def test_aggregate_exposes_every_required_field() -> None:
    aggregates = aggregate_sentiment(_fixture(), now=NOW)
    assert len(aggregates) == 1
    aggregate = aggregates[0]
    assert aggregate.scope == "instrument"
    assert aggregate.scope_value == "EUR_USD"
    assert aggregate.direction == "positive"
    assert aggregate.intensity == Decimal("0.5333333333333333333333333333")
    assert aggregate.disagreement == Decimal("0.4666666666666666666666666667")
    assert aggregate.sample_count == 3
    assert aggregate.source_coverage == Decimal("1")
    assert aggregate.freshness_seconds == Decimal("0.0")
    assert aggregate.uncertainty <= Decimal("1")
    assert aggregate.coverage_sufficient is True
    assert aggregate.evidence_ids == ("h-1", "h-2", "h-3")
    assert aggregate.algorithm_version == SENTIMENT_ALGORITHM_VERSION
    assert len(aggregate.snapshot_hash) == 64


def test_multi_scope_aggregates() -> None:
    samples = [
        _sample(
            evidence_id="m-1",
            scope="market",
            scope_value="GLOBAL",
            direction="negative",
            source="news-a",
        ),
        _sample(
            evidence_id="m-2",
            scope="market",
            scope_value="GLOBAL",
            direction="negative",
            source="news-b",
        ),
        _sample(
            evidence_id="m-3",
            scope="market",
            scope_value="GLOBAL",
            direction="negative",
            source="news-c",
        ),
        _sample(
            evidence_id="c-1",
            scope="currency",
            scope_value="EUR",
            direction="negative",
        ),
        _sample(
            evidence_id="a-1",
            scope="asset_class",
            scope_value="FX",
            direction="positive",
        ),
    ]
    aggregates = aggregate_sentiment(samples, now=NOW)
    scopes = {(a.scope, a.scope_value) for a in aggregates}
    assert scopes == {
        ("market", "GLOBAL"),
        ("currency", "EUR"),
        ("asset_class", "FX"),
    }
    by_scope = {a.scope: a for a in aggregates}
    assert by_scope["market"].direction == "negative"


# ---------------------------------------------------------------------------
# AC-M09-W04-02: reordering identical evidence is byte-equivalent
# ---------------------------------------------------------------------------


def test_reordering_produces_byte_equivalent_output() -> None:
    original = _fixture()
    shuffled = [original[2], original[0], original[1]]
    first = aggregate_sentiment(original, now=NOW)
    second = aggregate_sentiment(shuffled, now=NOW)
    assert first == second
    assert first[0].snapshot_hash == second[0].snapshot_hash
    assert json.dumps(
        [a.model_dump(mode="json") for a in first], sort_keys=True
    ) == json.dumps(
        [a.model_dump(mode="json") for a in second], sort_keys=True
    )


def test_snapshot_hash_changes_when_evidence_changes() -> None:
    first = aggregate_sentiment(_fixture(), now=NOW)
    changed = _fixture()
    changed[0] = changed[0].model_copy(update={"direction": "negative"})
    second = aggregate_sentiment(changed, now=NOW)
    assert first[0].snapshot_hash != second[0].snapshot_hash


# ---------------------------------------------------------------------------
# AC-M09-W04-03: sparse/contradictory/stale/single-source -> explicit verdicts
# ---------------------------------------------------------------------------


def test_sparse_samples_are_insufficient_coverage() -> None:
    aggregates = aggregate_sentiment(
        [_sample(evidence_id="only-one")], now=NOW
    )
    aggregate = aggregates[0]
    assert aggregate.coverage_sufficient is False
    assert aggregate.direction == "mixed"
    assert aggregate.uncertainty >= INSUFFICIENT_COVERAGE_UNCERTAINTY


def test_single_source_never_confident() -> None:
    samples = [
        _sample(evidence_id="h-1", source="news-a"),
        _sample(evidence_id="h-2", source="news-a"),
        _sample(evidence_id="h-3", source="news-a"),
    ]
    aggregate = aggregate_sentiment(samples, now=NOW)[0]
    assert aggregate.coverage_sufficient is False  # min_sources=2
    assert aggregate.direction == "mixed"
    assert aggregate.uncertainty >= INSUFFICIENT_COVERAGE_UNCERTAINTY


def test_contradictory_samples_are_mixed_with_high_disagreement() -> None:
    samples = [
        _sample(
            evidence_id="h-1",
            direction="positive",
            intensity=Decimal("1"),
            source="news-a",
        ),
        _sample(
            evidence_id="h-2",
            direction="negative",
            intensity=Decimal("1"),
            source="news-b",
        ),
        _sample(
            evidence_id="h-3",
            direction="positive",
            intensity=Decimal("1"),
            source="news-c",
        ),
    ]
    aggregate = aggregate_sentiment(samples, now=NOW)[0]
    assert aggregate.coverage_sufficient is True
    assert aggregate.disagreement >= Decimal("0.6")
    assert aggregate.direction == "mixed"


def test_stale_samples_are_explicitly_stale() -> None:
    old = NOW - timedelta(seconds=172800)  # 2 days old
    samples = [
        _sample(evidence_id="h-1", captured_at=old),
        _sample(evidence_id="h-2", captured_at=old),
        _sample(evidence_id="h-3", captured_at=old),
    ]
    aggregate = aggregate_sentiment(samples, now=NOW)[0]
    assert aggregate.coverage_sufficient is False
    assert aggregate.direction == "mixed"
    assert aggregate.freshness_seconds == Decimal("172800.0")
    assert aggregate.uncertainty >= INSUFFICIENT_COVERAGE_UNCERTAINTY


def test_float_intensity_rejected() -> None:
    import pytest

    with pytest.raises(ValueError):
        _sample(intensity=0.8)
