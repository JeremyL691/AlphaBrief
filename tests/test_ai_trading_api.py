"""Tests for /api/v1/ai/* routes."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from alphabrief_api.main import create_app
from alphabrief_api.routes.ai_trading import _reset_ai_state
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(tmp_path))
    _reset_ai_state()
    yield
    _reset_ai_state()


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    return TestClient(app)


class TestAiStatus:
    def test_returns_flags(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
        res = client.get("/api/v1/ai/status")
        assert res.status_code == 200
        data = res.json()
        assert data["ai_trading_enabled"] is True
        assert "discipline" in data

    def test_disabled_default(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ALPHABRIEF_AI_TRADING_ENABLED", raising=False)
        res = client.get("/api/v1/ai/status")
        assert res.status_code == 200
        data = res.json()
        assert data["ai_trading_enabled"] is False


class TestAiRules:
    def test_returns_discipline(self, client: TestClient) -> None:
        res = client.get("/api/v1/ai/rules")
        assert res.status_code == 200
        data = res.json()
        assert "discipline" in data
        assert data["prompt_version"] == "aitrader-v1"
        assert data["roles"] == [
            "technical",
            "fundamental",
            "risk",
            "manager",
        ]


class TestAiRun:
    def test_disabled_returns_409(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ALPHABRIEF_AI_TRADING_ENABLED", raising=False)
        res = client.post(
            "/api/v1/ai/run", json={"symbols": ["SPY"]}
        )
        assert res.status_code == 409

    def test_live_unlocked_returns_409(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
        monkeypatch.setenv("ALPHABRIEF_LIVE_TRADING_ENABLED", "true")
        res = client.post(
            "/api/v1/ai/run", json={"symbols": ["SPY"]}
        )
        assert res.status_code == 409
        assert "live-trading" in res.json()["detail"].lower()

    def test_run_records_cycle(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
        res = client.post(
            "/api/v1/ai/run",
            json={
                "symbols": ["SPY", "QQQ"],
                "reference_prices": {"SPY": "450", "QQQ": "380"},
            },
        )
        assert res.status_code == 201
        data = res.json()
        assert data["outcome"] in {
            "executed",
            "skipped_no_intent",
            "skipped_no_consensus",
            "blocked_risk_gate",
            "blocked_human_review",
        }
        assert "cycle_id" in data

    def test_empty_symbols_returns_422(self, client: TestClient) -> None:
        res = client.post("/api/v1/ai/run", json={"symbols": []})
        assert res.status_code == 422


class TestAiHistory:
    def test_empty_history(self, client: TestClient) -> None:
        res = client.get("/api/v1/ai/history")
        assert res.status_code == 200
        assert res.json()["cycles"] == []

    def test_history_appears_after_run(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
        client.post("/api/v1/ai/run", json={"symbols": ["SPY"]})
        res = client.get("/api/v1/ai/history")
        assert res.status_code == 200
        data = res.json()
        assert len(data["cycles"]) >= 1
        assert data["cycles"][0]["cycle_id"]

    def test_history_limit_clamped(
        self, client: TestClient
    ) -> None:
        res = client.get("/api/v1/ai/history?limit=999")
        assert res.status_code == 422
        res = client.get("/api/v1/ai/history?limit=0")
        assert res.status_code == 422


class TestAiCycle:
    def test_get_cycle_404_when_missing(self, client: TestClient) -> None:
        res = client.get("/api/v1/ai/cycles/missing")
        assert res.status_code == 404

    def test_get_cycle_after_run(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
        run_res = client.post("/api/v1/ai/run", json={"symbols": ["SPY"]})
        cycle_id = run_res.json()["cycle_id"]
        res = client.get(f"/api/v1/ai/cycles/{cycle_id}")
        assert res.status_code == 200
        data = res.json()
        assert data["cycle_id"] == cycle_id


class TestAiAttempts:
    def test_empty(self, client: TestClient) -> None:
        res = client.get("/api/v1/ai/attempts")
        assert res.status_code == 200
        assert res.json()["attempts"] == []

    def test_limit_clamped(self, client: TestClient) -> None:
        res = client.get("/api/v1/ai/attempts?limit=500")
        assert res.status_code == 422


class TestAiObservationDir:
    """The scheduler exports ai_cycle_*.json files; when
    ALPHABRIEF_AI_OBSERVATION_DIR is set the read-only endpoints serve
    those exports instead of the API's own (separate) DB."""

    def _write_export(
        self, obs_dir: Path, record: dict[str, object]
    ) -> None:
        obs_dir.mkdir(parents=True, exist_ok=True)
        day = record["trading_day"]
        (obs_dir / f"ai_cycle_{day}.json").write_text(
            json.dumps(record), encoding="utf-8"
        )

    def _export_record(self, **overrides: object) -> dict[str, object]:
        record: dict[str, object] = {
            "cycle_id": "aic_obs1",
            "trading_day": "2026-08-12",
            "symbols": ["EUR_USD", "GBP_USD"],
            "plans": [],
            "attempts": [
                {
                    "intent_id": "ai_obs_abc",
                    "outcome": "executed",
                    "approved": True,
                    "requires_human_review": False,
                    "filled": True,
                    "order_id": "o1",
                    "created_at": "2026-08-12T09:00:00Z",
                }
            ],
            "votes": [],
            "outcome": "executed",
            "enabled": True,
            "live_trading_enabled": False,
            "summary": (
                "outcome=executed; plans=0; executed=1; blocked=0; "
                "total_attempts=1"
            ),
            "created_at": "2026-08-12T09:05:56.811847Z",
        }
        record.update(overrides)
        return record

    def test_exports_serve_status_history_cycle_attempts(
        self,
        client: TestClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        obs = tmp_path / "obs"
        self._write_export(obs, self._export_record())
        monkeypatch.setenv("ALPHABRIEF_AI_OBSERVATION_DIR", str(obs))

        res = client.get("/api/v1/ai/status")
        assert res.status_code == 200
        assert res.json()["cycle_count"] == 1

        res = client.get("/api/v1/ai/history?limit=10")
        assert res.status_code == 200
        cycles = res.json()["cycles"]
        assert len(cycles) == 1
        summary = cycles[0]
        assert summary["cycle_id"] == "aic_obs1"
        assert summary["executed_count"] == 1
        assert summary["plan_count"] == 0
        assert summary["symbols"] == ["EUR_USD", "GBP_USD"]

        res = client.get("/api/v1/ai/cycles/aic_obs1")
        assert res.status_code == 200
        assert res.json()["cycle_id"] == "aic_obs1"

        res = client.get("/api/v1/ai/cycles/does-not-exist")
        assert res.status_code == 404

        res = client.get("/api/v1/ai/attempts")
        assert res.status_code == 200
        attempts = res.json()["attempts"]
        assert len(attempts) == 1
        assert attempts[0]["intent_id"] == "ai_obs_abc"
        assert attempts[0]["cycle_id"] == "aic_obs1"
        assert attempts[0]["outcome"] == "executed"

    def test_provider_error_outcome_surfaces_in_history(
        self,
        client: TestClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        obs = tmp_path / "obs"
        self._write_export(
            obs,
            self._export_record(
                outcome="provider_error",
                summary=(
                    "outcome=provider_error; plans=0; executed=0; blocked=0; "
                    "total_attempts=0; roles=[technical: provider_call_failed]"
                ),
            ),
        )
        monkeypatch.setenv("ALPHABRIEF_AI_OBSERVATION_DIR", str(obs))
        res = client.get("/api/v1/ai/history?limit=10")
        assert res.status_code == 200
        assert res.json()["cycles"][0]["outcome"] == "provider_error"

    def test_error_export_files_ignored(
        self,
        client: TestClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        obs = tmp_path / "obs"
        obs.mkdir(parents=True, exist_ok=True)
        (obs / "ai_cycle_error_2026-08-12.json").write_text(
            json.dumps({"error": "boom"}), encoding="utf-8"
        )
        monkeypatch.setenv("ALPHABRIEF_AI_OBSERVATION_DIR", str(obs))
        res = client.get("/api/v1/ai/status")
        assert res.status_code == 200
        assert res.json()["cycle_count"] == 0
        res = client.get("/api/v1/ai/history")
        assert res.status_code == 200
        assert res.json()["cycles"] == []