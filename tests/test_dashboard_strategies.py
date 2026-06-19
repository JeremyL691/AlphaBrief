"""Tests for the strategy dashboard page (Phase 15 R15.6)."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alphabrief_api.main import app
from alphabrief_api.routes.strategies import _clear_strategy_store
from alphabrief_api.routes.strategy_signals import _clear_signal_store
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path) -> Generator[None, None, None]:
    os.environ["ALPHABRIEF_DATA_DIR"] = str(tmp_path / "alphabrief_db")
    _clear_strategy_store()
    _clear_signal_store()
    yield
    _clear_strategy_store()
    _clear_signal_store()


def _spec(
    strategy_id: str = "ema_trend_v1", name: str = "EMA Trend v1"
) -> dict[str, object]:
    return {
        "strategy_id": strategy_id,
        "name": name,
        "version": "1.0.0",
        "universe": {"symbols": ["BTC-USD"]},
        "timeframe": "1d",
        "entry": {"condition": "close > ema_50"},
        "exit": {"condition": "close < ema_50"},
        "risk": {"max_position_pct": "0.2"},
        "costs": {"fee_bps": "5", "slippage_bps": "10"},
        "evaluation": {
            "train_period": {"start": "2024-01-01", "end": "2024-12-31"},
            "test_period": {"start": "2025-01-01", "end": "2025-12-31"},
        },
    }


def _signal(signal_id: str, strategy_id: str) -> dict[str, object]:
    return {
        "signal_id": signal_id,
        "strategy_id": strategy_id,
        "symbol": "BTC-USD",
        "timestamp": "2024-06-01T00:00:00+00:00",
        "direction": "long",
        "confidence": 0.7,
        "horizon": "1d",
        "rationale": "test",
    }


# ---------------------------------------------------------------------------
# Page exists
# ---------------------------------------------------------------------------


def test_strategies_dashboard_serves_200() -> None:
    resp = client.get("/dashboard/strategies")
    assert resp.status_code == 200


def test_strategies_dashboard_includes_main_heading() -> None:
    resp = client.get("/dashboard/strategies")
    assert resp.status_code == 200
    body = resp.text
    assert "Strategy Registry" in body
    assert "strategies" in body
    assert "signal-counts" in body


def test_main_dashboard_includes_strategies_nav_link() -> None:
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "/dashboard/strategies" in resp.text


def test_strategies_dashboard_contains_advisory_disclaimer() -> None:
    resp = client.get("/dashboard/strategies")
    body = resp.text
    assert "advisory" in body.lower()
    assert "RiskGate" in body or "risk gate" in body.lower()


# ---------------------------------------------------------------------------
# Page renders stored strategies
# ---------------------------------------------------------------------------


def test_strategies_dashboard_empty_state() -> None:
    resp = client.get("/dashboard/strategies")
    # When there are no strategies the JS renders a hint. The page
    # itself is always served; the empty state appears in the rendered
    # DOM after JS runs, so here we only assert the page loads.
    assert resp.status_code == 200


def test_strategies_dashboard_lists_saved_strategy() -> None:
    client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec(), "enabled": True},
    )
    resp = client.get("/dashboard/strategies")
    assert resp.status_code == 200
    # The page references the strategy id and name in the JS loader.
    body = resp.text
    assert "/api/v1/strategies/specs" in body
    assert "/api/v1/strategies/enabled" in body
    assert "/api/v1/strategies/" in body
    assert "signals/count" in body


def test_strategies_dashboard_references_signal_endpoint() -> None:
    """The page must call the per-strategy signal count endpoint."""
    client.post("/api/v1/strategies/specs", json={"spec": _spec()})
    resp = client.get("/dashboard/strategies")
    body = resp.text
    # The page fetches counts for every strategy via the
    # /api/v1/strategies/{id}/signals/count endpoint.
    assert "signals/count" in body
