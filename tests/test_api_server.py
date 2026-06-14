"""Tests for the AlphaBrief API server."""

from __future__ import annotations

from pathlib import Path

import pytest
from alphabrief_api.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health_check_returns_200() -> None:
    response = client.get("/health")

    assert response.status_code == 200


def test_health_check_body() -> None:
    response = client.get("/health")

    assert response.json() == {"status": "healthy", "version": "0.0.0"}


def test_api_status_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHABRIEF_ENV", "test")

    response = client.get("/api/status")

    assert response.status_code == 200


def test_api_status_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHABRIEF_ENV", "test")
    monkeypatch.setenv("ALPHABRIEF_LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", "data/local")
    monkeypatch.setenv("ALPHABRIEF_REPORTS_DIR", "reports/generated")

    response = client.get("/api/status")

    assert response.json() == {
        "version": "0.0.0",
        "environment": "test",
        "live_trading_enabled": False,
        "data_dir": "data/local",
        "reports_dir": "reports/generated",
        "packages_loaded": [
            "alphabrief_core",
            "alphabrief_data",
            "alphabrief_strategy",
            "alphabrief_backtest",
            "alphabrief_models",
            "alphabrief_risk",
            "alphabrief_execution",
            "alphabrief_gym",
            "alphabrief_review",
        ],
    }


def test_api_data_status_returns_200(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "bars.csv").write_text("timestamp,open,high,low,close,volume\n")
    monkeypatch.setenv("ALPHABRIEF_DATA_DIR", str(data_dir))

    response = client.get("/api/data/status")

    assert response.status_code == 200
    assert response.json()["data_dir_exists"] is True
    assert response.json()["data_dir_has_files"] is True
