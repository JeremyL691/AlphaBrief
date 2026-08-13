"""M09-W06: immutable daily regime and sentiment snapshots.

- a snapshot records its news, macro, sentiment, entity-link, quality,
  freshness, and source-version IDs under one immutable version ID and
  hash (AC-M09-W06-01);
- research context and news-risk context loaded by the same snapshot ID
  resolve identical evidence and quality verdicts (AC-M09-W06-03).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from alphabrief_news.regime_snapshot import (
    FreshnessVerdict,
    QualityVerdict,
    RegimeSnapshotInput,
    RegimeSnapshotStore,
    SourceStatus,
    build_regime_snapshot,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _inputs(**overrides: object) -> RegimeSnapshotInput:
    payload: dict[str, object] = {
        "news_ids": ("n-1", "n-2"),
        "macro_ids": ("m-1",),
        "sentiment_ids": ("s-1",),
        "entity_link_ids": ("e-1",),
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
            SourceStatus(source="macro-b", ok=True, version="v1"),
        ),
    }
    payload.update(overrides)
    return RegimeSnapshotInput.model_validate(payload)


def test_snapshot_records_every_input_id_under_one_version_and_hash() -> None:
    snapshot = build_regime_snapshot(_inputs(), now=NOW)
    assert snapshot.snapshot_id == snapshot.version_id
    assert snapshot.snapshot_id.startswith("regime-v1-")
    assert len(snapshot.content_hash) == 64
    assert snapshot.news_ids == ("n-1", "n-2")
    assert snapshot.macro_ids == ("m-1",)
    assert snapshot.sentiment_ids == ("s-1",)
    assert snapshot.entity_link_ids == ("e-1",)
    assert snapshot.quality_verdicts[0].passed is True
    assert snapshot.freshness_verdicts[0].fresh is True
    assert snapshot.source_versions == (
        ("macro-b", "v1"),
        ("news-a", "v3"),
    )
    assert snapshot.degradation == "healthy"
    assert snapshot.missing_source_reasons == ()


def test_snapshot_is_deterministic_for_identical_inputs() -> None:
    first = build_regime_snapshot(_inputs(), now=NOW)
    second = build_regime_snapshot(_inputs(), now=NOW)
    assert first.snapshot_id == second.snapshot_id
    assert first.content_hash == second.content_hash
    assert first == second


def test_snapshot_id_changes_when_inputs_change() -> None:
    first = build_regime_snapshot(_inputs(), now=NOW)
    changed = build_regime_snapshot(
        _inputs(news_ids=("n-3",)), now=NOW
    )
    assert first.snapshot_id != changed.snapshot_id


def test_store_resolves_identical_snapshot_for_any_consumer(
    tmp_path: Path,
) -> None:
    store = RegimeSnapshotStore(db_path=tmp_path / "regime.db")
    try:
        snapshot = build_regime_snapshot(_inputs(), now=NOW)
        assert store.persist(snapshot) is True
        assert store.persist(snapshot) is False  # immutable: duplicate ignored
        # The shared authority: the same ID resolves the same snapshot.
        research_view = store.get(snapshot.snapshot_id)
        risk_view = store.get(snapshot.snapshot_id)
        assert research_view is not None and risk_view is not None
        assert research_view == risk_view
        assert research_view.quality_verdicts == risk_view.quality_verdicts
        assert research_view.degradation == risk_view.degradation
        assert research_view.content_hash == risk_view.content_hash
    finally:
        store.close()


def test_store_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "regime.db"
    store = RegimeSnapshotStore(db_path=path)
    try:
        snapshot = build_regime_snapshot(_inputs(), now=NOW)
        store.persist(snapshot)
    finally:
        store.close()
    reopened = RegimeSnapshotStore(db_path=path)
    try:
        assert reopened.get(snapshot.snapshot_id) == snapshot
    finally:
        reopened.close()
