"""M09-W03: macro release CLI (AC-M09-W03-03).

CLI fixture queries return the same ordered macro events with explicit
states as the API store.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_cli.macro_commands import macro_app
from alphabrief_news.macro_release import (
    DEFAULT_STALE_AFTER_SECONDS,
    MacroRelease,
    MacroReleaseStore,
)
from typer.testing import CliRunner

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


@pytest.fixture(autouse=True)
def _isolated_macro(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    yield


def test_cli_macro_releases_returns_ordered_events(tmp_path: Path) -> None:
    store = MacroReleaseStore(db_path=tmp_path / "alphabrief.db")
    try:
        store.ingest(_release())
        store.ingest(
            _release(release_id="us-cpi", actual=None, release_time=NOW)
        )
        store.ingest(
            _release(
                release_id="stale-cpi",
                actual=None,
                release_time=datetime.now(UTC)
                - timedelta(seconds=DEFAULT_STALE_AFTER_SECONDS + 60),
            )
        )
    finally:
        store.close()

    runner = CliRunner()
    result = runner.invoke(macro_app, ["releases", "--compact"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["total"] == 3
    ids = [event["release_id"] for event in payload["releases"]]
    assert ids == ["stale-cpi", "ecb-rate", "us-cpi"]
    states = {event["release_id"]: event["state"] for event in payload["releases"]}
    assert states["ecb-rate"] == "fresh"
    assert states["us-cpi"] == "partial"
    assert states["stale-cpi"] == "stale"


def test_cli_macro_releases_empty_store(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(macro_app, ["releases", "--compact"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"releases": [], "total": 0}
