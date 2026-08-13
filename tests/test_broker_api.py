"""API tests for the /api/v1/broker/* routes.

These tests cover:
- broker status reflects the local recon store
- broker reconcile records a snapshot
- broker freeze / unfreeze round-trip
- broker /positions and /account null-adapter shape (live reads are
  covered by tests/test_broker_api_live.py against a mock Alpaca server)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alphabrief_api.broker_adapter import _reset_broker_adapter
from alphabrief_api.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    # No OANDA credentials in the default suite -> null adapter.
    # Reset first so a cred-bearing test from elsewhere cannot leak its
    # adapter. Credentials are cleared because the auto-load step in
    # ``alphabrief_api.__init__`` may have populated them from the
    # project's local ``.env`` on developer workstations.
    monkeypatch.delenv("ALPHABRIEF_OANDA_TOKEN", raising=False)
    monkeypatch.delenv("ALPHABRIEF_OANDA_ACCOUNT_ID", raising=False)
    _reset_broker_adapter()
    app = create_app()
    return TestClient(app)


def test_broker_status_returns_empty_store(client: TestClient) -> None:
    response = client.get("/api/v1/broker/status")
    assert response.status_code == 200
    body = response.json()
    assert body["latest_snapshot"] is None
    assert body["open_freezes"] == []


def test_broker_reconcile_fails_closed_without_credentials(
    client: TestClient,
) -> None:
    # With no OANDA practice credentials the shared durable service
    # records an explicitly non-matching snapshot — never a vacuous
    # all-match placeholder (AC-M07-W06-03).
    response = client.post("/api/v1/broker/reconcile?scope=eod")
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "eod"
    assert body["all_match"] is False
    assert body["freeze_raised"] is False  # eod scope never freezes
    status = client.get("/api/v1/broker/status")
    latest = status.json()["latest_snapshot"]
    assert latest is not None
    assert latest["all_match"] is False


def test_broker_reconcile_rejects_invalid_scope(client: TestClient) -> None:
    response = client.post("/api/v1/broker/reconcile?scope=invalid")
    assert response.status_code == 400
    assert "scope must be one of" in response.json()["detail"]


def test_broker_freeze_and_unfreeze_round_trip(client: TestClient) -> None:
    freeze = client.post("/api/v1/broker/freeze", json={"reason": "manual test"})
    assert freeze.status_code == 200
    event_id = freeze.json()["event_id"]

    status = client.get("/api/v1/broker/status")
    assert status.status_code == 200
    assert len(status.json()["open_freezes"]) == 1

    unfreeze = client.post(
        "/api/v1/broker/unfreeze",
        json={"event_id": event_id, "reason": "manual clear"},
    )
    assert unfreeze.status_code == 200
    assert unfreeze.json()["event_id"] == event_id

    final = client.get("/api/v1/broker/status")
    assert final.json()["open_freezes"] == []


def test_broker_unfreeze_unknown_event_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/v1/broker/unfreeze",
        json={"event_id": "missing", "reason": "test"},
    )
    assert response.status_code == 404


def test_broker_orders_returns_mapping(client: TestClient) -> None:
    response = client.get("/api/v1/broker/orders")
    assert response.status_code == 200
    assert response.json() == {"orders": []}


def test_broker_positions_returns_empty_without_credentials(
    client: TestClient,
) -> None:
    # Null adapter (no Alpaca credentials) -> empty positions list.
    response = client.get("/api/v1/broker/positions")
    assert response.status_code == 200
    assert response.json() == {"positions": []}


def test_broker_account_returns_zero_snapshot_without_credentials(
    client: TestClient,
) -> None:
    # Null adapter -> a real zero AccountSnapshot, not the pre-Phase-20
    # {"account": None} stub.
    response = client.get("/api/v1/broker/account")
    assert response.status_code == 200
    account = response.json()["account"]
    assert account["account_id"] == "null-adapter"
    assert account["cash"] == "0"
    assert account["equity"] == "0"
    assert account["buying_power"] == "0"
    assert account["currency"] == "USD"
    # captured_at is an ISO timestamp string.
    assert isinstance(account["captured_at"], str) and account["captured_at"]
