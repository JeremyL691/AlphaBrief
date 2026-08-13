"""M09-W03: macro calendar ingestion (AC-M09-W03-01/02).

Macro fixtures persist release time, actual, forecast, previous,
revision, importance, unit, source, and affected currencies/markets in
UTC; a revised observation appends a new version with lineage while the
prior value remains reconstructable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from alphabrief_news.macro_release import (
    DEFAULT_STALE_AFTER_SECONDS,
    MacroRelease,
    MacroReleaseStore,
    release_state,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _release(**overrides: object) -> MacroRelease:
    payload: dict[str, object] = {
        "release_id": "ecb-rate",
        "indicator": "ECB Main Refinancing Rate",
        "release_time": NOW,
        "actual": Decimal("4.00"),
        "forecast": Decimal("4.00"),
        "previous": Decimal("4.25"),
        "revision": False,
        "importance": "high",
        "unit": "pct",
        "source": "fixture-calendar",
        "affected_currencies": ("EUR",),
        "affected_markets": ("EUROPE",),
    }
    payload.update(overrides)
    return MacroRelease.model_validate(payload)


def test_ingest_persists_every_required_field(tmp_path: Path) -> None:
    store = MacroReleaseStore(db_path=tmp_path / "macro.db")
    try:
        assert store.ingest(_release()) is True
        latest = store.latest("ecb-rate")
        assert latest is not None
        assert latest.release_time == NOW
        assert latest.actual == Decimal("4.00")
        assert latest.forecast == Decimal("4.00")
        assert latest.previous == Decimal("4.25")
        assert latest.revision is False
        assert latest.importance == "high"
        assert latest.unit == "pct"
        assert latest.source == "fixture-calendar"
        assert latest.affected_currencies == ("EUR",)
        assert latest.affected_markets == ("EUROPE",)
        assert latest.version == 1
        assert latest.lineage == ()
    finally:
        store.close()


def test_duplicate_ingest_is_ignored(tmp_path: Path) -> None:
    store = MacroReleaseStore(db_path=tmp_path / "macro.db")
    try:
        assert store.ingest(_release()) is True
        assert store.ingest(_release()) is False
        assert len(store.versions("ecb-rate")) == 1
    finally:
        store.close()


def test_revision_appends_version_with_lineage(tmp_path: Path) -> None:
    store = MacroReleaseStore(db_path=tmp_path / "macro.db")
    try:
        store.ingest(_release())
        revised = store.revise("ecb-rate", actual=Decimal("3.75"))
        assert revised is not None
        assert revised.version == 2
        assert revised.actual == Decimal("3.75")
        assert revised.revision is True
        assert revised.lineage == ("ecb-rate",)
        # The prior value remains reconstructable.
        versions = store.versions("ecb-rate")
        assert len(versions) == 2
        assert versions[0].actual == Decimal("4.00")
        assert versions[0].version == 1
        # Latest resolves to the revised version.
        assert store.latest("ecb-rate") is not None
        assert store.latest("ecb-rate").actual == Decimal("3.75")  # type: ignore[union-attr]
    finally:
        store.close()


def test_revise_unknown_release_returns_none(tmp_path: Path) -> None:
    store = MacroReleaseStore(db_path=tmp_path / "macro.db")
    try:
        assert store.revise("missing") is None
    finally:
        store.close()


def test_release_state_matrix(tmp_path: Path) -> None:
    store = MacroReleaseStore(db_path=tmp_path / "macro.db")
    try:
        # Fresh: complete observation at version 1.
        store.ingest(_release())
        assert release_state(store.latest("ecb-rate"), now=NOW).state == "fresh"
        # Revised: version > 1.
        store.revise("ecb-rate", actual=Decimal("3.75"))
        assert release_state(store.latest("ecb-rate"), now=NOW).state == "revised"
        # Missing: no record.
        assert release_state(None, now=NOW).state == "missing"
        # Partial: released with no actual yet.
        store.ingest(_release(release_id="us-cpi", actual=None))
        partial = store.latest("us-cpi")
        assert partial is not None
        assert release_state(partial, now=NOW).state == "partial"
        # Stale: partial and older than the staleness window.
        old = NOW - timedelta(seconds=DEFAULT_STALE_AFTER_SECONDS + 60)
        store.ingest(
            _release(release_id="stale-cpi", actual=None, release_time=old)
        )
        assert release_state(store.latest("stale-cpi"), now=NOW).state == "stale"
    finally:
        store.close()


def test_releases_ordered_by_time_then_id(tmp_path: Path) -> None:
    store = MacroReleaseStore(db_path=tmp_path / "macro.db")
    try:
        store.ingest(_release(release_id="b", release_time=NOW))
        store.ingest(_release(release_id="a", release_time=NOW - timedelta(hours=1)))
        store.ingest(_release(release_id="c", release_time=NOW + timedelta(hours=1)))
        ids = [release.release_id for release in store.releases()]
        assert ids == ["a", "b", "c"]
    finally:
        store.close()


def test_float_values_rejected() -> None:
    import pytest

    with pytest.raises(ValueError):
        _release(actual=4.0)
