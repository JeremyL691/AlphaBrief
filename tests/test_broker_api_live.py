"""Live-path tests for /api/v1/broker/positions and /account (Phase 20 R20.2).

Exercises the API-side ``BrokerAdapter`` singleton against a mock Alpaca
Paper server (``tests._helpers.MockAlpacaServer``):

- credentials set + mock seeded -> live ``/positions`` and ``/account``
  return parsed snapshots (Decimals as strings).
- live adapter failure (mock killed / unreachable) -> HTTP 503 with a
  structured ``{"error","kind"}`` detail, never a silent stub.
- no credentials -> null adapter, empty positions / zero account.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from _helpers.mock_alpaca_server import MockAlpacaServer
from alphabrief_api.broker_adapter import (
    ENV_ALPACA_BASE_URL,
    _reset_broker_adapter,
)
from alphabrief_api.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def live_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    """Build a TestClient whose broker adapter points at a mock Alpaca server.

    Yields the client; the mock server is started/stopped by the caller
    via the returned ``server`` (see individual tests). Credentials are
    injected through env so the factory builds a live adapter.
    """
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ALPHABRIEF_ALPACA_KEY", "test-key")
    monkeypatch.setenv("ALPHABRIEF_ALPACA_SECRET", "test-secret")
    # The auto-load step in ``alphabrief_api.__init__`` may have
    # populated OANDA creds from the developer's local ``.env``; clear
    # them so the broker factory picks the mock Alpaca adapter (OANDA
    # is preferred when both credential sets are present).
    monkeypatch.delenv("ALPHABRIEF_OANDA_TOKEN", raising=False)
    monkeypatch.delenv("ALPHABRIEF_OANDA_ACCOUNT_ID", raising=False)
    _reset_broker_adapter()
    return TestClient(create_app())


def _seed_positions_and_account(server: MockAlpacaServer) -> None:
    server.on(
        "GET",
        "/v2/positions",
        status=200,
        body=[
            {
                "symbol": "SPY",
                "qty": "3",
                "avg_entry_price": "412.50",
            },
            {
                "symbol": "QQQ",
                "qty": "1",
                "avg_entry_price": "398.00",
            },
        ],
    )
    server.on(
        "GET",
        "/v2/account",
        status=200,
        body={
            "account_number": "PA-0001",
            "cash": "99123.45",
            "equity": "100000.00",
            "buying_power": "200000.00",
            "currency": "USD",
            "status": "ACTIVE",
        },
    )


def test_positions_returns_live_data(
    live_client: TestClient,
) -> None:
    server = MockAlpacaServer()
    server.start()
    try:
        # Point the adapter at the mock before the first live read.
        import os

        os.environ[ENV_ALPACA_BASE_URL] = server.base_url
        _reset_broker_adapter()
        _seed_positions_and_account(server)

        response = live_client.get("/api/v1/broker/positions")
        assert response.status_code == 200
        positions = response.json()["positions"]
        assert [p["symbol"] for p in positions] == ["SPY", "QQQ"]
        # Decimals are stringified at the response boundary, preserving
        # the input string's trailing zeroes (Decimal("412.50") -> "412.50").
        spy = positions[0]
        assert spy["quantity"] == "3"
        assert Decimal(spy["average_price"]) == Decimal("412.50")
    finally:
        server.stop()


def test_account_returns_live_snapshot(
    live_client: TestClient,
) -> None:
    server = MockAlpacaServer()
    server.start()
    try:
        import os

        os.environ[ENV_ALPACA_BASE_URL] = server.base_url
        _reset_broker_adapter()
        _seed_positions_and_account(server)

        response = live_client.get("/api/v1/broker/account")
        assert response.status_code == 200
        account = response.json()["account"]
        assert account["account_id"] == "PA-0001"
        assert account["cash"] == "99123.45"
        assert account["equity"] == "100000.00"
        assert account["buying_power"] == "200000.00"
        assert account["currency"] == "USD"
        assert isinstance(account["captured_at"], str) and account["captured_at"]
    finally:
        server.stop()


def test_live_adapter_failure_returns_503(
    live_client: TestClient,
) -> None:
    # Point the adapter at an unreachable port (no server listening).
    import os

    os.environ[ENV_ALPACA_BASE_URL] = "http://127.0.0.1:1"
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
    monkeypatch.delenv("ALPHABRIEF_ALPACA_KEY", raising=False)
    monkeypatch.delenv("ALPHABRIEF_ALPACA_SECRET", raising=False)
    monkeypatch.delenv("ALPHABRIEF_ALPACA_BASE_URL", raising=False)
    # The auto-load step in ``alphabrief_api.__init__`` may have populated
    # OANDA creds from the developer's local ``.env``; clear them too so
    # the null-adapter path is exercised as documented.
    monkeypatch.delenv("ALPHABRIEF_OANDA_TOKEN", raising=False)
    monkeypatch.delenv("ALPHABRIEF_OANDA_ACCOUNT_ID", raising=False)
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


def test_other_broker_routes_unchanged_with_live_adapter(
    live_client: TestClient,
) -> None:
    # The read-only live wiring must not touch the recon-store-backed routes.
    server = MockAlpacaServer()
    server.start()
    try:
        import os

        os.environ[ENV_ALPACA_BASE_URL] = server.base_url
        _reset_broker_adapter()

        status = live_client.get("/api/v1/broker/status")
        assert status.status_code == 200
        assert status.json()["latest_snapshot"] is None

        orders = live_client.get("/api/v1/broker/orders")
        assert orders.status_code == 200
        assert orders.json() == {"orders": []}
    finally:
        server.stop()
