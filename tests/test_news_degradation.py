"""M09-W06: deterministic degradation for partial-source failure and
stale critical coverage (AC-M09-W06-02).

Partial-source failure and stale critical coverage produce deterministic
degraded or blocked verdicts with missing-source reasons — never
synthesized replacement facts.
"""

from __future__ import annotations

from datetime import UTC, datetime

from alphabrief_news.regime_snapshot import (
    DegradationPolicy,
    FreshnessVerdict,
    QualityVerdict,
    RegimeSnapshotInput,
    SourceStatus,
    build_regime_snapshot,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _inputs(**overrides: object) -> RegimeSnapshotInput:
    payload: dict[str, object] = {
        "news_ids": ("n-1",),
        "macro_ids": (),
        "sentiment_ids": (),
        "entity_link_ids": (),
        "quality_verdicts": (
            QualityVerdict(dimension="coverage", passed=True, detail="ok"),
        ),
        "freshness_verdicts": (
            FreshnessVerdict(
                input_kind="news", age_seconds=60, max_age_seconds=300, fresh=True
            ),
        ),
        "source_statuses": (
            SourceStatus(source="news-a", ok=True, version="v3"),
        ),
    }
    payload.update(overrides)
    return RegimeSnapshotInput.model_validate(payload)


def test_healthy_when_all_sources_ok() -> None:
    snapshot = build_regime_snapshot(
        _inputs(),
        policy=DegradationPolicy(critical_sources=("news-a",)),
        now=NOW,
    )
    assert snapshot.degradation == "healthy"
    assert snapshot.missing_source_reasons == ()


def test_partial_source_failure_is_degraded_with_reason() -> None:
    snapshot = build_regime_snapshot(
        _inputs(
            source_statuses=(
                SourceStatus(source="news-a", ok=True, version="v3"),
                SourceStatus(source="macro-b", ok=False, detail="timeout"),
            ),
        ),
        policy=DegradationPolicy(critical_sources=("news-a",)),
        now=NOW,
    )
    assert snapshot.degradation == "degraded"
    assert snapshot.missing_source_reasons == (
        "macro-b: fetch failed, missing, or stale",
    )
    # No replacement facts are synthesized.
    assert snapshot.news_ids == ("n-1",)


def test_stale_critical_coverage_is_blocked_with_reason() -> None:
    snapshot = build_regime_snapshot(
        _inputs(
            freshness_verdicts=(
                FreshnessVerdict(
                    input_kind="news", age_seconds=500, max_age_seconds=300, fresh=False
                ),
            ),
        ),
        policy=DegradationPolicy(
            critical_sources=("news-a",),
            critical_input_kinds=("news",),
        ),
        now=NOW,
    )
    assert snapshot.degradation == "blocked"
    assert snapshot.missing_source_reasons == (
        "news (stale): fetch failed, missing, or stale",
    )


def test_non_critical_stale_source_is_degraded_not_blocked() -> None:
    snapshot = build_regime_snapshot(
        _inputs(
            source_statuses=(
                SourceStatus(source="news-a", ok=True, version="v3"),
                SourceStatus(source="macro-b", ok=False, detail="rate limited"),
            ),
        ),
        policy=DegradationPolicy(critical_sources=("news-a",)),
        now=NOW,
    )
    assert snapshot.degradation == "degraded"
    assert snapshot.missing_source_reasons == (
        "macro-b: fetch failed, missing, or stale",
    )


def test_critical_source_failure_blocks_even_with_other_sources_ok() -> None:
    snapshot = build_regime_snapshot(
        _inputs(
            source_statuses=(
                SourceStatus(source="news-a", ok=False, detail="unreachable"),
                SourceStatus(source="macro-b", ok=True, version="v1"),
            ),
        ),
        policy=DegradationPolicy(
            critical_sources=("news-a",),
            critical_input_kinds=("news",),
        ),
        now=NOW,
    )
    assert snapshot.degradation == "blocked"
    assert snapshot.missing_source_reasons == (
        "news-a: fetch failed, missing, or stale",
    )


def test_identical_inputs_yield_identical_verdicts() -> None:
    inputs = _inputs(
        source_statuses=(
            SourceStatus(source="news-a", ok=False, detail="timeout"),
        ),
    )
    policy = DegradationPolicy(critical_sources=("news-a",))
    first = build_regime_snapshot(inputs, policy=policy, now=NOW)
    second = build_regime_snapshot(inputs, policy=policy, now=NOW)
    assert first.degradation == second.degradation == "blocked"
    assert first.missing_source_reasons == second.missing_source_reasons
    assert first.content_hash == second.content_hash
