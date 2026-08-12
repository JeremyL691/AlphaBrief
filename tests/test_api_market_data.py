"""API market-data route integration tests (M03-W02).

The bars endpoint serves the deduplicated latest version per timestamp
while the versioned facts remain queryable through the store.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_api.main import create_app
from alphabrief_core import Bar
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path: Path) -> Generator[None, None, None]:
    """Point the module-level store at a temporary database."""
    from alphabrief_api.routes.data import _clear_store, _close_store

    os.environ["ALPHABRIEF_DATA_DIR"] = str(tmp_path / "alphabrief_db")
    _close_store()
    _clear_store()
    yield
    _close_store()
    _clear_store()


def test_bars_endpoint_serves_latest_version(tmp_path: Path) -> None:
    """AC-M03-W02-01: the API serves the latest version per timestamp."""
    from alphabrief_api.db.market_data import MarketDataStore

    # The route store resolves its path from ALPHABRIEF_DATA_DIR, which
    # the autouse fixture points at tmp_path/alphabrief_db.
    store = MarketDataStore()
    try:
        timestamp = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
        store.insert_bars(
            [
                Bar(
                    symbol="EUR_USD",
                    timestamp=timestamp,
                    open=Decimal("1.09"),
                    high=Decimal("1.11"),
                    low=Decimal("1.08"),
                    close=Decimal("1.10"),
                    volume=Decimal("1000"),
                    source="test",
                    data_version="v1",
                )
            ],
            source="test",
            data_version="v1",
        )
        store.insert_bars(
            [
                Bar(
                    symbol="EUR_USD",
                    timestamp=timestamp,
                    open=Decimal("1.09"),
                    high=Decimal("1.12"),
                    low=Decimal("1.08"),
                    close=Decimal("1.11"),
                    volume=Decimal("1000"),
                    source="test",
                    data_version="v2",
                )
            ],
            source="test",
            data_version="v2",
        )
    finally:
        store.close()

    client = TestClient(create_app())
    response = client.get("/api/v1/data/EUR_USD/bars")
    assert response.status_code == 200
    bars = response.json()["bars"]
    assert len(bars) == 1
    assert Decimal(bars[0]["close"]) == Decimal("1.11")


def test_symbols_endpoint_lists_loaded_symbol(tmp_path: Path) -> None:
    from alphabrief_api.db.market_data import MarketDataStore

    store = MarketDataStore()
    try:
        store.insert_bars(
            [
                Bar(
                    symbol="GBP_USD",
                    timestamp=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
                    open=Decimal("1.29"),
                    high=Decimal("1.31"),
                    low=Decimal("1.28"),
                    close=Decimal("1.30"),
                    volume=Decimal("500"),
                    source="test",
                    data_version="v1",
                )
            ],
            source="test",
            data_version="v1",
        )
    finally:
        store.close()

    client = TestClient(create_app())
    response = client.get("/api/v1/data/symbols")
    assert response.status_code == 200
    symbols = {item["symbol"] for item in response.json()["symbols"]}
    assert "GBP_USD" in symbols
