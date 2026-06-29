"""Tests for /api/v1/ai/* routes."""

from __future__ import annotations

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