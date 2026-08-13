"""M11-W02: API and CLI task status share one persisted runtime truth.

Covers AC-M11-W02-03: the API and CLI status surfaces expose the active
configuration, leader ID, running phase, heartbeat, last outcome, and
next due time from the same persisted authority.
"""

from __future__ import annotations

import json
import os
from collections.abc import Generator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alphabrief_api.main import app
from alphabrief_trader.runtime_truth import RuntimeTruthStore
from fastapi.testclient import TestClient
from typer.testing import CliRunner

client = TestClient(app)
runner = CliRunner()

_T0 = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


@pytest.fixture
def truth(tmp_path: Path) -> Iterator[RuntimeTruthStore]:
    store = RuntimeTruthStore(db_path=tmp_path / "alphabrief.db")
    try:
        yield store
    finally:
        store.close()


@pytest.fixture(autouse=True)
def _isolate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    os.environ["ALPHABRIEF_DATA_DIR"] = str(tmp_path)
    yield


def _seed(store: RuntimeTruthStore) -> None:
    store.update(
        leader_id="scheduler-main",
        active_config={"tasks": ["ai-cycle", "reconcile"], "ttl_seconds": 60},
        running_phase="discuss",
        phase_started_at=_T0,
        last_outcome="no_trade",
        failure_classification="none",
        next_due_at=_T0 + timedelta(minutes=15),
    )
    store.heartbeat(leader_id="scheduler-main", running_phase="discuss")


class TestRuntimeTruthPersistence:
    def test_update_and_read_round_trip(self, truth: RuntimeTruthStore) -> None:
        _seed(truth)
        state = truth.read()
        assert state is not None
        assert state["leader_id"] == "scheduler-main"
        assert state["active_config"]["tasks"] == ["ai-cycle", "reconcile"]
        assert state["running_phase"] == "discuss"
        assert state["phase_started_at"] is not None
        assert state["last_outcome"] == "no_trade"
        assert state["failure_classification"] == "none"
        assert state["next_due_at"] is not None
        assert state["heartbeat_at"] is not None

    def test_phase_timestamps_and_classification_survive_restart(
        self, tmp_path: Path
    ) -> None:
        first = RuntimeTruthStore(db_path=tmp_path / "alphabrief.db")
        _seed(first)
        first.close()

        second = RuntimeTruthStore(db_path=tmp_path / "alphabrief.db")
        try:
            state = second.read()
            assert state is not None
            assert state["phase_started_at"] == _T0
            assert state["failure_classification"] == "none"
        finally:
            second.close()

    def test_runtime_truth_survives_store_restart(
        self, tmp_path: Path
    ) -> None:
        first = RuntimeTruthStore(db_path=tmp_path / "alphabrief.db")
        _seed(first)
        first.close()

        second = RuntimeTruthStore(db_path=tmp_path / "alphabrief.db")
        try:
            state = second.read()
            assert state is not None
            assert state["leader_id"] == "scheduler-main"
            assert state["running_phase"] == "discuss"
        finally:
            second.close()

    def test_heartbeat_updates_only_the_leader(
        self, truth: RuntimeTruthStore
    ) -> None:
        _seed(truth)
        before = truth.read()
        assert before is not None
        truth.heartbeat(leader_id="scheduler-other")
        after = truth.read()
        assert after is not None
        # A non-leader heartbeat must not change the leader's row.
        assert after["leader_id"] == before["leader_id"]

    def test_empty_store_reads_none(self, truth: RuntimeTruthStore) -> None:
        assert truth.read() is None


class TestApiStatusSurface:
    def test_status_exposes_runtime_truth(
        self, truth: RuntimeTruthStore
    ) -> None:
        _seed(truth)
        response = client.get("/api/v1/scheduler/status")
        assert response.status_code == 200
        body = response.json()
        assert body["leader_id"] == "scheduler-main"
        assert body["running_phase"] == "discuss"
        assert body["last_outcome"] == "no_trade"
        assert body["phase_started_at"] is not None
        assert body["failure_classification"] == "none"
        assert body["next_due_at"] is not None
        assert body["heartbeat_at"] is not None
        assert body["active_config"]["tasks"] == ["ai-cycle", "reconcile"]

    def test_status_has_null_runtime_when_absent(self) -> None:
        response = client.get("/api/v1/scheduler/status")
        assert response.status_code == 200
        body = response.json()
        assert body["leader_id"] is None
        assert body["running_phase"] is None
        assert body["last_outcome"] is None
        assert body["active_config"] == {}


class TestCliStatusSurface:
    def test_cli_status_exposes_runtime_truth(self, tmp_path: Path) -> None:
        from alphabrief_cli.scheduler_commands import scheduler_app

        store = RuntimeTruthStore(db_path=tmp_path / "alphabrief.db")
        _seed(store)
        store.close()

        result = runner.invoke(
            scheduler_app, ["status", "--compact"]
        )
        assert result.exit_code == 0, result.stdout
        body = json.loads(result.stdout)
        assert body["leader_id"] == "scheduler-main"
        assert body["running_phase"] == "discuss"
        assert body["phase_started_at"] is not None
        assert body["last_outcome"] == "no_trade"
        assert body["failure_classification"] == "none"
        assert body["next_due_at"] is not None
        assert body["active_config"]["tasks"] == ["ai-cycle", "reconcile"]

    def test_cli_status_matches_api_surface(
        self, truth: RuntimeTruthStore
    ) -> None:
        from alphabrief_cli.scheduler_commands import scheduler_app

        _seed(truth)
        api_body = client.get("/api/v1/scheduler/status").json()

        result = runner.invoke(scheduler_app, ["status", "--compact"])
        assert result.exit_code == 0
        cli_body = json.loads(result.stdout)

        for field in (
            "leader_id",
            "running_phase",
            "last_outcome",
            "next_due_at",
            "heartbeat_at",
        ):
            assert cli_body[field] == api_body[field], field
        assert cli_body["active_config"] == api_body["active_config"]
