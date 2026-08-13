"""M09-W03: macro release store persistence and restart (AC-M09-W03-02).

A revised observation appends a new version with lineage while the prior
value remains reconstructable; records survive restart.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from alphabrief_news.macro_release import MacroRelease, MacroReleaseStore

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _release(**overrides: object) -> MacroRelease:
    payload: dict[str, object] = {
        "release_id": "fed-rate",
        "indicator": "Fed Funds Target Rate",
        "release_time": NOW,
        "actual": Decimal("5.50"),
        "forecast": Decimal("5.50"),
        "previous": Decimal("5.25"),
        "revision": False,
        "importance": "high",
        "unit": "pct",
        "source": "fixture-calendar",
        "affected_currencies": ("USD",),
        "affected_markets": ("US",),
    }
    payload.update(overrides)
    return MacroRelease.model_validate(payload)


def test_versions_reconstruct_prior_values(tmp_path: Path) -> None:
    store = MacroReleaseStore(db_path=tmp_path / "macro.db")
    try:
        store.ingest(_release())
        store.revise("fed-rate", actual=Decimal("5.25"))
        versions = store.versions("fed-rate")
        assert [v.version for v in versions] == [1, 2]
        assert [v.actual for v in versions] == [Decimal("5.50"), Decimal("5.25")]
        assert versions[0].lineage == ()
        assert versions[1].lineage == ("fed-rate",)
    finally:
        store.close()


def test_store_survives_restart_with_revisions(tmp_path: Path) -> None:
    path = tmp_path / "macro.db"
    store = MacroReleaseStore(db_path=path)
    try:
        store.ingest(_release())
        store.revise("fed-rate", actual=Decimal("5.25"))
    finally:
        store.close()
    reopened = MacroReleaseStore(db_path=path)
    try:
        assert reopened.latest("fed-rate") is not None
        assert reopened.latest("fed-rate").actual == Decimal("5.25")  # type: ignore[union-attr]
        assert len(reopened.versions("fed-rate")) == 2
        assert [v.version for v in reopened.releases()] == [2]
    finally:
        reopened.close()


def test_releases_latest_version_per_release(tmp_path: Path) -> None:
    store = MacroReleaseStore(db_path=tmp_path / "macro.db")
    try:
        store.ingest(_release())
        store.ingest(
            _release(release_id="fed-rate-2", release_time=NOW)
        )
        store.revise("fed-rate", actual=Decimal("5.00"))
        releases = store.releases()
        assert len(releases) == 2
        by_id = {r.release_id: r for r in releases}
        assert by_id["fed-rate"].version == 2
        assert by_id["fed-rate-2"].version == 1
    finally:
        store.close()


def test_indicator_filter_orders_releases(tmp_path: Path) -> None:
    store = MacroReleaseStore(db_path=tmp_path / "macro.db")
    try:
        store.ingest(_release())
        store.ingest(
            _release(release_id="other", indicator="CPI", release_time=NOW)
        )
        releases = store.releases(indicator="CPI")
        assert [r.release_id for r in releases] == ["other"]
    finally:
        store.close()
