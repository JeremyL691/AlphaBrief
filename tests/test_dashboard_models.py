"""Tests for the dashboard model performance pages (Phase 14 Round 6)."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alphabrief_api.main import app
from alphabrief_api.routes.models import _clear_store
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path) -> Generator[None, None, None]:
    os.environ["ALPHABRIEF_DATA_DIR"] = str(tmp_path / "alphabrief_db")
    _clear_store()
    yield
    _clear_store()


def test_dashboard_main_includes_model_performance_section() -> None:
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    body = resp.text
    assert "Model Performance" in body
    assert "model-performance" in body


def test_dashboard_nav_includes_models_link() -> None:
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "/dashboard/models" in resp.text


def test_dashboard_models_page_serves_200() -> None:
    resp = client.get("/dashboard/models")
    assert resp.status_code == 200
    body = resp.text
    assert "Model Performance" in body
    assert "evaluations" in body
    assert "by-model" in body


def test_dashboard_models_page_handles_empty_state() -> None:
    resp = client.get("/dashboard/models")
    assert resp.status_code == 200
    assert "No evaluations yet" in resp.text or "No model performance" in resp.text


def test_dashboard_main_includes_scheduler_card() -> None:
    """The main dashboard should now surface scheduler state."""
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    body = resp.text
    assert "scheduler-status" in body
    assert "Scheduler" in body


def test_dashboard_main_includes_skeleton_loaders() -> None:
    """Each card should ship a skeleton placeholder while loading."""
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    body = resp.text
    assert body.count('class="skeleton') >= 6


def test_dashboard_main_includes_refresh_indicator() -> None:
    """A visible refresh indicator + 30s auto-refresh must be present."""
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    body = resp.text
    assert "refresh-indicator" in body
    assert "REFRESH_INTERVAL_MS = 30000" in body
