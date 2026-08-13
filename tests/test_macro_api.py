"""M09-W03: macro release API (AC-M09-W03-03).

API fixture queries return ordered macro events and expose missing,
stale, partial, and revised states explicitly.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_api.main import create_app
from alphabrief_api.routes.macro import (
    _get_release_store,
    _reset_release_store,
)
from alphabrief_news.macro_release import (
    DEFAULT_STALE_AFTER_SECONDS,
    MacroRelease,
)
from fastapi.testclient import TestClient

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
    _reset_release_store()
    yield
    _reset_release_store()


def test_macro_releases_returns_ordered_events_with_states() -> None:
    store = _get_release_store()
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
    store.ingest(
        _release(
            release_id="gbp-rate",
            actual=Decimal("5.00"),
            release_time=NOW,
        )
    )
    store.revise("gbp-rate", actual=Decimal("4.75"))

    client = TestClient(create_app())
    response = client.get("/api/v1/macro/releases")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4
    ids = [event["release_id"] for event in body["releases"]]
    assert ids == ["stale-cpi", "ecb-rate", "gbp-rate", "us-cpi"]
    states = {event["release_id"]: event["state"] for event in body["releases"]}
    assert states["ecb-rate"] == "fresh"
    assert states["us-cpi"] == "partial"
    assert states["gbp-rate"] == "revised"
    assert states["stale-cpi"] == "stale"


def test_macro_releases_empty_store() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/macro/releases")
    assert response.status_code == 200
    assert response.json() == {"releases": [], "total": 0}


def test_macro_release_revise_appends_version() -> None:
    _get_release_store().ingest(_release())
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/macro/releases/revise",
        json={"release_id": "ecb-rate", "actual": "3.75"},
    )
    assert response.status_code == 200
    release = response.json()["release"]
    assert release["version"] == 2
    assert release["actual"] == "3.75"
    assert release["revision"] is True
    assert release["lineage"] == ["ecb-rate"]
    # The API view now marks it revised.
    events = client.get("/api/v1/macro/releases").json()["releases"]
    assert events[0]["state"] == "revised"


def test_macro_release_revise_unknown_returns_404() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/macro/releases/revise",
        json={"release_id": "missing", "actual": "1.0"},
    )
    assert response.status_code == 404
