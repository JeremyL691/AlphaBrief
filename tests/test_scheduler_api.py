"""API tests for the /api/v1/scheduler/* routes.

These tests cover:
- scheduler status reflects the local HeartbeatStore + recon store
- heartbeats / alerts / tasks / freezes routes return the right shape
- limit query param clamping on /alerts
- aggregate counts on /status
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alphabrief_api.main import create_app
from alphabrief_execution.broker.recon_store import BrokerReconStore
from alphabrief_execution.operations.scheduler import HeartbeatStore
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    app = create_app()
    return TestClient(app)


def test_scheduler_status_returns_zero_counts_when_empty(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/scheduler/status")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "heartbeat_count": 0,
        "open_freeze_count": 0,
        "alerts_total": 0,
        "running": False,
    }


def test_scheduler_heartbeats_empty_when_no_tasks_have_run(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/scheduler/heartbeats")
    assert response.status_code == 200
    assert response.json() == {"heartbeats": []}


def test_scheduler_heartbeats_lists_each_task_after_record_run(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Seed the heartbeat store directly; the API only reads from it.
    store = HeartbeatStore(db_path=tmp_path / "alphabrief.db")
    store.record_run(task_name="reconcile", status="ok", error=None)
    store.record_run(task_name="other", status="error", error="boom")
    store.close()

    response = client.get("/api/v1/scheduler/heartbeats")
    assert response.status_code == 200
    body = response.json()
    assert len(body["heartbeats"]) == 2
    by_name = {row["task_name"]: row for row in body["heartbeats"]}
    assert by_name["reconcile"]["last_status"] == "ok"
    assert by_name["other"]["last_error"] == "boom"


def test_scheduler_alerts_returns_recent_alerts(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = HeartbeatStore(db_path=tmp_path / "alphabrief.db")
    import asyncio

    async def _emit_two() -> None:
        from alphabrief_execution.operations.scheduler import AlertSink

        sink = AlertSink(heartbeat_store=store)
        await sink.emit(
            severity="warning",
            source="scheduler",
            message="first",
        )
        await sink.emit(
            severity="critical",
            source="scheduler",
            message="second",
            task_name="reconcile",
        )

    asyncio.run(_emit_two())
    store.close()

    response = client.get("/api/v1/scheduler/alerts?limit=10")
    assert response.status_code == 200
    body = response.json()
    assert len(body["alerts"]) == 2
    messages = {row["message"] for row in body["alerts"]}
    assert messages == {"first", "second"}


def test_scheduler_alerts_limit_query_param_respected(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = HeartbeatStore(db_path=tmp_path / "alphabrief.db")
    import asyncio

    async def _emit_three() -> None:
        from alphabrief_execution.operations.scheduler import AlertSink

        sink = AlertSink(heartbeat_store=store)
        for i in range(3):
            await sink.emit(
                severity="info",
                source="scheduler",
                message=f"msg-{i}",
            )

    asyncio.run(_emit_three())
    store.close()

    response = client.get("/api/v1/scheduler/alerts?limit=2")
    assert response.status_code == 200
    assert len(response.json()["alerts"]) == 2


def test_scheduler_alerts_limit_below_min_returns_422(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/scheduler/alerts?limit=0")
    assert response.status_code == 422


def test_scheduler_alerts_limit_above_max_returns_422(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/scheduler/alerts?limit=501")
    assert response.status_code == 422


def test_scheduler_tasks_returns_default_task_set(client: TestClient) -> None:
    response = client.get("/api/v1/scheduler/tasks")
    assert response.status_code == 200
    body = response.json()
    assert len(body["tasks"]) == 1
    task = body["tasks"][0]
    assert task["name"] == "reconcile"
    assert task["interval_seconds"] == 300.0
    assert task["enabled"] is True


def test_scheduler_freezes_returns_open_freeze(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = BrokerReconStore(db_path=tmp_path / "alphabrief.db")
    store.raise_freeze(reason="manual test", source="test")
    store.close()

    response = client.get("/api/v1/scheduler/freezes")
    assert response.status_code == 200
    body = response.json()
    assert len(body["open_freezes"]) == 1
    assert body["open_freezes"][0]["reason"] == "manual test"


def test_scheduler_status_aggregates_counts_from_multiple_stores(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    heartbeats = HeartbeatStore(db_path=tmp_path / "alphabrief.db")
    heartbeats.record_run(task_name="reconcile", status="ok", error=None)
    heartbeats.record_run(task_name="other", status="ok", error=None)
    heartbeats.close()
    recon = BrokerReconStore(db_path=tmp_path / "alphabrief.db")
    recon.raise_freeze(reason="r1", source="t")
    recon.raise_freeze(reason="r2", source="t")
    recon.close()

    response = client.get("/api/v1/scheduler/status")
    assert response.status_code == 200
    body = response.json()
    assert body["heartbeat_count"] == 2
    assert body["open_freeze_count"] == 2
    assert body["alerts_total"] == 0
    assert body["running"] is False


# ---------------------------------------------------------------------------
# Graceful degradation: writer-lock collisions must return 503 with a
# structured "scheduler_writer_locked" payload, not a 500 that breaks
# the dashboard. Phase 30 task #2.
# ---------------------------------------------------------------------------


def test_scheduler_status_returns_503_when_writer_locked(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alphabrief_api.routes import scheduler as scheduler_routes

    def _explode() -> dict[str, object]:
        raise OSError("IO Error: Could not set lock on file")

    monkeypatch.setattr(
        scheduler_routes, "_heartbeat_store", _explode, raising=True
    )
    response = client.get("/api/v1/scheduler/status")
    assert response.status_code == 503
    body = response.json()
    assert body["kind"] == "scheduler_writer_locked"
    assert body["error"] == "scheduler_writer_locked"


def test_scheduler_heartbeats_returns_503_when_writer_locked(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alphabrief_api.routes import scheduler as scheduler_routes

    def _explode() -> dict[str, object]:
        raise OSError("database is locked by another process")

    monkeypatch.setattr(
        scheduler_routes, "_heartbeat_store", _explode, raising=True
    )
    response = client.get("/api/v1/scheduler/heartbeats")
    assert response.status_code == 503
    assert response.json()["kind"] == "scheduler_writer_locked"


def test_scheduler_alerts_returns_503_when_writer_locked(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alphabrief_api.routes import scheduler as scheduler_routes

    def _explode() -> dict[str, object]:
        raise RuntimeError("Could not set lock")

    monkeypatch.setattr(
        scheduler_routes, "_heartbeat_store", _explode, raising=True
    )
    response = client.get("/api/v1/scheduler/alerts?limit=5")
    assert response.status_code == 503
    assert response.json()["kind"] == "scheduler_writer_locked"


def test_scheduler_freezes_returns_503_when_writer_locked(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alphabrief_api.routes import scheduler as scheduler_routes

    def _explode() -> dict[str, object]:
        raise OSError("IO Error: Could not set lock on file")

    monkeypatch.setattr(
        scheduler_routes, "_recon_store", _explode, raising=True
    )
    response = client.get("/api/v1/scheduler/freezes")
    assert response.status_code == 503
    assert response.json()["kind"] == "scheduler_writer_locked"


def test_scheduler_status_propagates_non_lock_errors(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unrelated failures must still surface as 500 (no silent 503)."""
    from alphabrief_api.routes import scheduler as scheduler_routes

    def _explode() -> dict[str, object]:
        raise ValueError("something else broke")

    monkeypatch.setattr(
        scheduler_routes, "_heartbeat_store", _explode, raising=True
    )
    with pytest.raises(ValueError, match="something else broke"):
        client.get("/api/v1/scheduler/status")
    # Non-lock errors must NOT be silently swallowed by the writer-lock
    # handler. TestClient re-raises in-test exceptions; the contract
    # is that the error surfaces, not that it's a specific status code.
