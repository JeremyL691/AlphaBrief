"""Fail-closed behavior when no model provider is configured.

Covers AC-M10-W01-02/03: a missing provider must never be replaced by a
production fake, and the trading path must produce a durable blocked or
no-trade result without a proposal, OrderIntent, or broker submission.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alphabrief_api.main import app
from alphabrief_api.routes.ai_trading import _reset_ai_state
from alphabrief_trader import (
    ModelProviderUnavailableError,
    build_ai_trading_committee,
)
from fastapi.testclient import TestClient

client = TestClient(app)

_PROVIDER_ENV_VARS = (
    "ALPHABRIEF_AI_MODEL_PROVIDER",
    "ALPHABRIEF_AI_MODEL_NAME",
    "ALPHABRIEF_AI_MODEL_BASE_URL",
    "ALPHABRIEF_AI_MODEL_TIMEOUT_SECONDS",
    "OPENAI_API_KEY",
)


@pytest.fixture(autouse=True)
def _isolate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    os.environ["ALPHABRIEF_DATA_DIR"] = str(tmp_path / "alphabrief_db")
    monkeypatch.delenv("ALPHABRIEF_AI_TRADING_ENABLED", raising=False)
    for name in _PROVIDER_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    _reset_ai_state()
    yield
    _reset_ai_state()


def test_factory_without_provider_raises_and_creates_no_committee() -> None:
    with pytest.raises(ModelProviderUnavailableError):
        build_ai_trading_committee()


def test_api_ai_run_fails_closed_without_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
    resp = client.post(
        "/api/v1/ai/run",
        json={
            "symbols": ["SPY", "QQQ"],
            "reference_prices": {"SPY": "450", "QQQ": "380"},
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["outcome"] == "skipped_no_intent"
    assert "model provider unavailable" in body["summary"]
    assert body["plan_count"] == 0
    assert body["attempt_count"] == 0
    assert body["votes"] == []
    assert body["plans"] == []
    assert body["attempts"] == []


def test_api_ai_run_unavailable_record_is_durable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
    created = client.post(
        "/api/v1/ai/run",
        json={"symbols": ["SPY"]},
    ).json()

    history = client.get("/api/v1/ai/history").json()
    assert len(history["cycles"]) >= 1
    assert history["cycles"][0]["cycle_id"] == created["cycle_id"]
    assert history["cycles"][0]["outcome"] == "skipped_no_intent"

    stored = client.get(f"/api/v1/ai/cycles/{created['cycle_id']}").json()
    assert stored["plans"] == []
    assert stored["attempts"] == []
    assert stored["votes"] == []


def test_api_ai_run_with_explicit_fake_is_explicit_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
    monkeypatch.setenv("ALPHABRIEF_AI_MODEL_PROVIDER", "fake")
    resp = client.post(
        "/api/v1/ai/run",
        json={"symbols": ["SPY"], "reference_prices": {"SPY": "450"}},
    )
    # Explicit fake selection is allowed test composition; the cycle runs
    # and records a real (deterministic) outcome rather than failing.
    assert resp.status_code == 201, resp.text
    assert resp.json()["outcome"] in {
        "executed",
        "skipped_no_intent",
        "skipped_no_consensus",
        "blocked_risk_gate",
        "blocked_human_review",
    }
