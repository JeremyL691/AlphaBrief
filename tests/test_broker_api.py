"""API tests for the /api/v1/broker/* routes.

These tests cover:
- broker status reflects the local recon store
- broker reconcile records a snapshot
- broker freeze / unfreeze round-trip
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alphabrief_api.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    app = create_app()
    return TestClient(app)


def test_broker_status_returns_empty_store(client: TestClient) -> None:
    response = client.get("/api/v1/broker/status")
    assert response.status_code == 200
    body = response.json()
    assert body["latest_snapshot"] is None
    assert body["open_freezes"] == []


def test_broker_reconcile_records_snapshot(client: TestClient) -> None:
    response = client.post("/api/v1/broker/reconcile?scope=eod")
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "eod"
    assert body["all_match"] is True


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


def test_broker_account_returns_null(client: TestClient) -> None:
    response = client.get("/api/v1/broker/account")
    assert response.status_code == 200
    assert response.json() == {"account": None}
