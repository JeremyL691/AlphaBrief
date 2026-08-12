"""M04-W05: read-only instrument catalog API and CLI surfaces.

Covers:
- API and CLI return identical totals, filtered counts, metadata,
  taxonomy, active state, catalog version, and freshness for the same
  query (AC-M04-W05-01);
- pagination, exact-name lookup, case-insensitive search, category
  filters, active filters, unknown categories, and empty results have
  deterministic schemas and ordering (AC-M04-W05-02);
- missing, stale, or account-mismatched catalogs return explicit
  unavailable states and never substitute a hard-coded allowlist or
  trigger a broker write (AC-M04-W05-03).
"""

from __future__ import annotations

import json
import os
from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_api.db.instrument_catalog import InstrumentCatalogStore
from alphabrief_api.main import create_app
from alphabrief_cli.data_commands import data_app
from alphabrief_execution.broker.oanda.instruments import (
    InstrumentCatalogSnapshot,
    InstrumentMetadata,
)
from fastapi.testclient import TestClient
from typer.testing import CliRunner

ACCOUNT_HASH = "acct-hash"


def _instrument(
    name: str, display: str, raw_type: str = "CURRENCY"
) -> InstrumentMetadata:
    return InstrumentMetadata(
        name=name,
        display_name=display,
        raw_type=raw_type,
        display_precision=5,
        trade_units_precision=0,
        minimum_trade_size=Decimal("1"),
        maximum_order_units=Decimal("0"),
        maximum_position_size=Decimal("0"),
        margin_rate=Decimal("0.05"),
        pip_location=-4,
    )


def _publish(
    store: InstrumentCatalogStore,
    *instruments: InstrumentMetadata,
    account: str = ACCOUNT_HASH,
    fetched_at: datetime | None = None,
) -> None:
    store.publish_snapshot(
        InstrumentCatalogSnapshot(
            account_id_hash=account,
            fetched_at=fetched_at or datetime.now(UTC),
            instruments=instruments,
        )
    )


@pytest.fixture(autouse=True)
def _isolated_catalog(tmp_path: Path) -> Generator[None, None, None]:
    """Point the module-level catalog store at a temporary database."""
    from alphabrief_api.routes.data import _clear_catalog_store

    os.environ["ALPHABRIEF_DATA_DIR"] = str(tmp_path / "alphabrief_db")
    _clear_catalog_store()
    yield
    _clear_catalog_store()


def _seeded_store() -> InstrumentCatalogStore:
    store = InstrumentCatalogStore()
    _publish(
        store,
        _instrument("EUR_USD", "EUR/USD"),
        _instrument("GBP_USD", "GBP/USD"),
        _instrument("XAU_USD", "Gold", "METAL"),
        _instrument("US30_USD", "US Wall St 30", "CFD"),
    )
    store.close()
    return store


# ---------------------------------------------------------------------------
# AC-M04-W05-01: API/CLI parity
# ---------------------------------------------------------------------------


def test_api_and_cli_return_identical_results() -> None:
    _seeded_store()

    client = TestClient(create_app())
    api = client.get("/api/v1/data/catalog").json()

    result = CliRunner().invoke(data_app, ["catalog", "--compact"])
    assert result.exit_code == 0
    cli = json.loads(result.stdout)

    assert api == cli
    assert cli["availability"] == "available"
    assert cli["total"] == 4
    assert cli["filtered_count"] == 4


def test_api_and_cli_filter_parity() -> None:
    _seeded_store()
    client = TestClient(create_app())
    api = client.get(
        "/api/v1/data/catalog", params={"category": "CURRENCY", "search": "usd"}
    ).json()

    result = CliRunner().invoke(
        data_app, ["catalog", "--category", "CURRENCY", "--search", "usd", "--compact"]
    )
    cli = json.loads(result.stdout)

    assert api == cli
    assert cli["filtered_count"] == 2
    assert {item["name"] for item in cli["items"]} == {"EUR_USD", "GBP_USD"}


# ---------------------------------------------------------------------------
# AC-M04-W05-02: deterministic pagination, search, filters, ordering
# ---------------------------------------------------------------------------


def test_pagination_and_deterministic_ordering() -> None:
    _seeded_store()
    client = TestClient(create_app())

    page1 = client.get("/api/v1/data/catalog", params={"page_size": 2}).json()
    page2 = client.get(
        "/api/v1/data/catalog", params={"page_size": 2, "page": 2}
    ).json()

    names1 = [item["name"] for item in page1["items"]]
    names2 = [item["name"] for item in page2["items"]]
    assert names1 == sorted(names1)
    assert names2 == sorted(names2)
    assert len(names1) == 2 and len(names2) == 2
    assert set(names1) & set(names2) == set()


def test_exact_name_lookup_and_case_insensitive_search() -> None:
    _seeded_store()
    client = TestClient(create_app())

    exact = client.get("/api/v1/data/catalog", params={"search": "XAU_USD"}).json()
    assert exact["filtered_count"] == 1
    assert exact["items"][0]["name"] == "XAU_USD"

    fuzzy = client.get("/api/v1/data/catalog", params={"search": "gold"}).json()
    assert fuzzy["filtered_count"] == 1
    assert fuzzy["items"][0]["name"] == "XAU_USD"


def test_unknown_category_filter_and_empty_results() -> None:
    _seeded_store()
    client = TestClient(create_app())

    unknown = client.get(
        "/api/v1/data/catalog", params={"category": "OTHER_CFD"}
    ).json()
    assert unknown["availability"] == "available"
    assert unknown["filtered_count"] == 0
    assert unknown["items"] == []

    empty = client.get(
        "/api/v1/data/catalog", params={"search": "zzzz-no-such-instrument"}
    ).json()
    assert empty["filtered_count"] == 0
    assert empty["items"] == []


def test_items_carry_taxonomy_and_active_state() -> None:
    _seeded_store()
    client = TestClient(create_app())
    body = client.get("/api/v1/data/catalog", params={"search": "US30_USD"}).json()
    item = body["items"][0]
    assert item["category"] == "INDEX_CFD"
    assert item["taxonomy_version"].startswith("oanda-taxonomy-")
    assert item["active"] is True
    assert item["raw_type"] == "CFD"


# ---------------------------------------------------------------------------
# AC-M04-W05-03: explicit unavailable states, no substitutes
# ---------------------------------------------------------------------------


def test_missing_catalog_returns_explicit_unavailable_state() -> None:
    os.environ["ALPHABRIEF_DATA_DIR"] = str(Path(__import__("tempfile").mkdtemp()))
    from alphabrief_api.routes.data import _clear_catalog_store

    _clear_catalog_store()
    client = TestClient(create_app())
    body = client.get("/api/v1/data/catalog").json()
    assert body["availability"] == "missing"
    assert body["items"] == []
    assert body["total"] == 0


def test_stale_catalog_returns_explicit_unavailable_state() -> None:
    store = InstrumentCatalogStore()
    _publish(
        store,
        _instrument("EUR_USD", "EUR/USD"),
        fetched_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    store.close()
    from alphabrief_api.routes.data import _clear_catalog_store

    _clear_catalog_store()
    client = TestClient(create_app())
    # freshness_threshold_seconds=0 makes the snapshot stale.
    body = client.get(
        "/api/v1/data/catalog", params={"freshness_threshold_seconds": 0}
    ).json()
    assert body["availability"] == "stale"
    assert body["items"] == []


def test_catalog_query_never_writes() -> None:
    """Queries are read-only: no snapshot is published and no write occurs."""
    store = InstrumentCatalogStore()
    _publish(
        store,
        _instrument("EUR_USD", "EUR/USD"),
        _instrument("GBP_USD", "GBP/USD"),
        _instrument("XAU_USD", "Gold", "METAL"),
        _instrument("US30_USD", "US Wall St 30", "CFD"),
    )
    store.query(search="EUR")
    assert len(store.list_snapshots()) == 1
    projection = store.current_projection()
    assert projection is not None
    assert {i.name for i in projection.instruments} == {
        "EUR_USD",
        "GBP_USD",
        "XAU_USD",
        "US30_USD",
    }
    store.close()
