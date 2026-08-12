"""Live-path tests for /api/v1/broker/positions and /account (Phase 20 R20.2).

M01-W02: exercises the API-side ``BrokerAdapter`` singleton against a mock
OANDA practice server (``tests._helpers.MockOandaServer``):

- credentials set + mock seeded -> live ``/positions`` and ``/account``
  return parsed snapshots (Decimals as strings).
- live adapter failure (mock killed / unreachable) -> HTTP 503 with a
  structured ``{"error","kind"}`` detail, never a silent stub.
- no credentials -> null adapter, empty positions / zero account.
- recon-store-backed routes stay unchanged with a live adapter.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from _helpers.mock_oanda_server import MockOandaServer
from alphabrief_api.broker_adapter import (
    ENV_OANDA_BASE_URL,
    _reset_broker_adapter,
)
from alphabrief_api.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def live_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    """Build a TestClient whose broker adapter points at a mock OANDA server.

    Yields the client; the mock server is started/stopped by the caller
    via the returned ``server`` (see individual tests). Credentials are
    injected through env so the factory builds a live adapter.
    """
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ALPHABRIEF_OANDA_TOKEN", "test-token")
    monkeypatch.setenv("ALPHABRIEF_OANDA_ACCOUNT_ID", "test-account")
    _reset_broker_adapter()
    return TestClient(create_app())


def _seed_positions_and_account(server: MockOandaServer) -> None:
    server.on(
        "GET",
        "/v3/accounts/test-account/openPositions",
        status=200,
        body={
            "positions": [
                {
                    "instrument": "EUR_USD",
                    "long": {"units": "3000", "averagePrice": "1.14123"},
                    "short": {"units": "0", "averagePrice": "0"},
                },
                {
                    "instrument": "XAU_USD",
                    "long": {"units": "10", "averagePrice": "4100.50"},
                    "short": {"units": "0", "averagePrice": "0"},
                },
            ]
        },
    )
    server.on(
        "GET",
        "/v3/accounts/test-account",
        status=200,
        body={
            "account": {
                "id": "101-004-1234567-001",
                "balance": "99123.45",
                "NAV": "100000.00",
                "marginAvailable": "90000.00",
                "currency": "USD",
                "status": "ACTIVE",
            }
        },
    )


def test_positions_returns_live_data(
    live_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = MockOandaServer()
    server.start()
    try:
        # Point the adapter at the mock before the first live read.
        monkeypatch.setenv(ENV_OANDA_BASE_URL, server.base_url)
        _reset_broker_adapter()
        _seed_positions_and_account(server)

        response = live_client.get("/api/v1/broker/positions")
        assert response.status_code == 200
        positions = response.json()["positions"]
        assert [p["symbol"] for p in positions] == ["EUR_USD", "XAU_USD"]
        # Decimals are stringified at the response boundary, preserving
        # the input string's trailing zeroes (Decimal("1.14123") -> "1.14123").
        eur = positions[0]
        assert eur["quantity"] == "3000"
        assert Decimal(eur["average_price"]) == Decimal("1.14123")
    finally:
        server.stop()


def test_account_returns_live_snapshot(
    live_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = MockOandaServer()
    server.start()
    try:
        monkeypatch.setenv(ENV_OANDA_BASE_URL, server.base_url)
        _reset_broker_adapter()
        _seed_positions_and_account(server)

        response = live_client.get("/api/v1/broker/account")
        assert response.status_code == 200
        account = response.json()["account"]
        assert account["account_id"] == "101-004-1234567-001"
        assert account["cash"] == "99123.45"
        assert account["equity"] == "100000.00"
        assert account["buying_power"] == "90000.00"
        assert account["currency"] == "USD"
        assert isinstance(account["captured_at"], str) and account["captured_at"]
    finally:
        server.stop()


def test_live_adapter_failure_returns_503(
    live_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Point the adapter at an unreachable port (no server listening).
    monkeypatch.setenv(ENV_OANDA_BASE_URL, "http://127.0.0.1:1")
    _reset_broker_adapter()

    response = live_client.get("/api/v1/broker/account")
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error"] == "broker_adapter_unavailable"
    # Either a BrokerTransientError (after retry exhaustion) or a transport
    # error, depending on how the urllib call surfaces the refused connection.
    assert detail["kind"] in {"BrokerTransientError", "transport"}


def test_no_credentials_returns_null_shapes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    # The auto-load step in ``alphabrief_api.__init__`` may have populated
    # OANDA creds from the developer's local ``.env``; clear them so the
    # null-adapter path is exercised as documented.
    monkeypatch.delenv("ALPHABRIEF_OANDA_TOKEN", raising=False)
    monkeypatch.delenv("ALPHABRIEF_OANDA_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("ALPHABRIEF_OANDA_BASE_URL", raising=False)
    _reset_broker_adapter()
    client = TestClient(create_app())

    positions = client.get("/api/v1/broker/positions")
    assert positions.status_code == 200
    assert positions.json() == {"positions": []}

    account = client.get("/api/v1/broker/account")
    assert account.status_code == 200
    body = account.json()["account"]
    assert body["account_id"] == "null-adapter"
    assert body["cash"] == "0"


def test_recon_routes_unchanged_with_live_adapter(
    live_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The read-only live wiring must not touch the recon-store-backed routes.
    server = MockOandaServer()
    server.start()
    try:
        monkeypatch.setenv(ENV_OANDA_BASE_URL, server.base_url)
        _reset_broker_adapter()

        status = live_client.get("/api/v1/broker/status")
        assert status.status_code == 200
        assert status.json()["latest_snapshot"] is None

        orders = live_client.get("/api/v1/broker/orders")
        assert orders.status_code == 200
        assert orders.json() == {"orders": []}
    finally:
        server.stop()
