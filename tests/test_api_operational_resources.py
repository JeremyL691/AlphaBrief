"""M13-W03: operational API resources from runtime stores.

Covers AC-M13-W03-01: API resources expose account, NAV, margin, PnL,
exposures, positions, pending orders, fills, financing, category
attribution, and their observation timestamps from runtime stores —
with explicit nulls (never fabricated values) for fields the stores
cannot supply.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_api.db.instrument_catalog import InstrumentCatalogStore
from alphabrief_api.db.paper import PaperStore
from alphabrief_api.main import create_app
from alphabrief_execution.broker.oanda.instruments import (
    InstrumentCatalogSnapshot,
    InstrumentMetadata,
)
from alphabrief_execution.broker.recon_store import BrokerReconStore
from fastapi.testclient import TestClient

DATA_DIR = "tmp"


@pytest.fixture(autouse=True)
def _isolate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _db_path(tmp_path: Path) -> Path:
    return tmp_path / "alphabrief.db"


def _seed_portfolio(tmp_path: Path) -> None:
    store = PaperStore(db_path=_db_path(tmp_path))
    try:
        store.save_portfolio_snapshot(
            cash="50000.00",
            realized_pnl="1200.00",
            total_value="61400.00",
            positions={
                "EUR_USD": {"quantity": "10000", "average_price": "1.10000"},
                "XAU_USD": {"quantity": "2", "average_price": "2400.000"},
            },
        )
        store.save_audit_event(
            "order_filled",
            symbol="EUR_USD",
            details={"order_id": "order-1", "fill_id": "fill-1", "message": "filled"},
        )
        store.save_equity_snapshot(
            account_id="account-test",
            captured_at=datetime(2026, 8, 14, 0, 0, tzinfo=UTC),
            equity=Decimal("61400.00"),
            realized_pnl_day=Decimal("200.00"),
        )
    finally:
        store.close()


def _seed_orders(tmp_path: Path) -> None:
    recon = BrokerReconStore(db_path=_db_path(tmp_path))
    try:
        recon.upsert_order_id_map(
            client_order_id="order-1",
            broker_order_id="oanda-1",
            status="FILLED",
        )
        recon.upsert_order_id_map(
            client_order_id="order-2",
            broker_order_id="oanda-2",
            status="SUBMITTED",
        )
    finally:
        recon.close()


def _seed_catalog(tmp_path: Path) -> None:
    store = InstrumentCatalogStore(db_path=_db_path(tmp_path))
    try:
        store.publish_snapshot(
            InstrumentCatalogSnapshot(
                account_id_hash="hash",
                fetched_at=datetime(2026, 8, 14, 0, 0, tzinfo=UTC),
                instruments=(
                    InstrumentMetadata(
                        name="EUR_USD",
                        display_name="EUR/USD",
                        raw_type="CURRENCY",
                        display_precision=5,
                        trade_units_precision=0,
                        minimum_trade_size=Decimal("1"),
                        maximum_order_units=Decimal("10000000"),
                        maximum_position_size=Decimal("20000000"),
                        margin_rate=Decimal("0.05"),
                        pip_location=-4,
                    ),
                    InstrumentMetadata(
                        name="XAU_USD",
                        display_name="Gold",
                        raw_type="METAL",
                        display_precision=3,
                        trade_units_precision=0,
                        minimum_trade_size=Decimal("1"),
                        maximum_order_units=Decimal("100000"),
                        maximum_position_size=Decimal("200000"),
                        margin_rate=Decimal("0.10"),
                        pip_location=-2,
                    ),
                ),
            )
        )
    finally:
        store.close()


class TestPortfolioResource:
    def test_portfolio_exposes_runtime_store_values(
        self, tmp_path: Path, client: TestClient
    ) -> None:
        _seed_portfolio(tmp_path)
        _seed_orders(tmp_path)
        _seed_catalog(tmp_path)
        response = client.get("/api/v1/operational/portfolio")
        assert response.status_code == 200
        body = response.json()
        assert Decimal(body["cash"]) == Decimal("50000.00")
        assert Decimal(body["nav"]) == Decimal("61400.00")
        assert Decimal(body["realized_pnl"]) == Decimal("1200.00")
        # total_value - cash - realized = 10200.00 unrealized.
        assert Decimal(body["unrealized_pnl"]) == Decimal("10200.00")
        assert body["snapshot_id"] is not None
        assert body["observed_at"] is not None
        # Gross = 11000 + 4800 = 15800; net identical (all long).
        assert Decimal(body["exposure"]["gross_exposure"]) == Decimal("15800.00")
        assert Decimal(body["exposure"]["net_exposure"]) == Decimal("15800.00")
        assert len(body["positions"]) == 2
        assert body["pending_orders"] == [
            {
                "client_order_id": "order-2",
                "broker_order_id": "oanda-2",
                "status": "SUBMITTED",
            }
        ]
        assert len(body["fills"]) == 1
        assert body["financing"] is None  # not persisted -> explicit null

    def test_margin_derived_from_shared_catalog(
        self, tmp_path: Path, client: TestClient
    ) -> None:
        _seed_portfolio(tmp_path)
        _seed_catalog(tmp_path)
        body = client.get("/api/v1/operational/portfolio").json()
        # 10000 * 1.10 * 0.05 + 2 * 2400 * 0.10 = 550 + 480 = 1030.
        assert Decimal(body["margin_used"]) == Decimal("1030.00")

    def test_missing_catalog_yields_explicit_null_margin(
        self, tmp_path: Path, client: TestClient
    ) -> None:
        _seed_portfolio(tmp_path)
        body = client.get("/api/v1/operational/portfolio").json()
        assert body["margin_used"] is None
        assert body["category_attribution"] is None

    def test_category_attribution_derived_from_taxonomy(
        self, tmp_path: Path, client: TestClient
    ) -> None:
        _seed_portfolio(tmp_path)
        _seed_catalog(tmp_path)
        body = client.get("/api/v1/operational/portfolio").json()
        categories = {row["category"]: row for row in body["category_attribution"]}
        assert set(categories) == {"CURRENCY", "METAL"}
        assert Decimal(categories["CURRENCY"]["gross_exposure"]) == Decimal("11000.00")
        assert Decimal(categories["METAL"]["gross_exposure"]) == Decimal("4800.00")

    def test_empty_store_returns_explicit_nulls_not_fakes(
        self, tmp_path: Path, client: TestClient
    ) -> None:
        response = client.get("/api/v1/operational/portfolio")
        assert response.status_code == 200
        body = response.json()
        assert body["cash"] is None
        assert body["nav"] is None
        assert body["snapshot_id"] is None
        assert body["observed_at"] is None
        assert body["positions"] == []
        assert body["pending_orders"] == []
        assert body["fills"] == []
        assert body["margin_used"] is None
        assert body["financing"] is None


class TestEquitySeries:
    def test_equity_series_returns_persisted_points(
        self, tmp_path: Path, client: TestClient
    ) -> None:
        _seed_portfolio(tmp_path)
        body = client.get("/api/v1/operational/equity").json()
        assert body["account_id"] == "not-configured"
        assert len(body["points"]) == 1
        point = body["points"][0]
        assert point["equity"] == "61400.00"
        assert point["realized_pnl_day"] == "200.00"
        assert point["captured_at"] is not None

    def test_equity_limit_is_validated(self, client: TestClient) -> None:
        assert client.get("/api/v1/operational/equity?limit=0").status_code == 422
        assert client.get("/api/v1/operational/equity?limit=5000").status_code == 422

    def test_equity_empty_series(self, client: TestClient) -> None:
        body = client.get("/api/v1/operational/equity").json()
        assert body["points"] == []
