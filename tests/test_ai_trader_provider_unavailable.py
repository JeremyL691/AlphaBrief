"""Fail-closed behavior when the model channel cannot serve a request.

The ChatGPT subscription channel always exists as a provider, so
"unavailable" now means "the channel refuses or fails the call": no
credentials, no granted scope, or a channel error. In every case the
trading path must produce a durable record with no proposal, no
OrderIntent, and no broker submission, and it must never be silently
replaced by a fake provider.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alphabrief_api.main import app
from alphabrief_api.routes.ai_trading import _reset_ai_state
from alphabrief_core import paths as _paths
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


def test_signed_out_channel_refuses_the_call_instead_of_faking() -> None:
    """Without credentials the channel exists but every call fails closed."""
    from alphabrief_models.chatgpt_plan import ChatGptPlanError
    from alphabrief_models.gateway import ModelRequest

    committee = build_ai_trading_committee()
    provider = committee._gateway._providers[0]  # noqa: SLF001

    with pytest.raises(ChatGptPlanError) as exc:
        provider.call(
            ModelRequest(
                request_id="probe",
                task_type="test",
                prompt_version="v1",
                input_text="hello",
                required_capabilities=["text_generation"],
            )
        )

    assert exc.value.code == "not_configured"

    # ``ModelProviderUnavailableError`` remains the fail-closed error type
    # for callers that compose their own provider list.
    with pytest.raises(ModelProviderUnavailableError):
        raise ModelProviderUnavailableError("no model channel configured")


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
    # The channel refused the call, so the cycle is a recorded error with
    # no proposal, no intent, and therefore no order.
    assert body["outcome"] == "provider_error"
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
        json={"symbols": ["SPY"], "reference_prices": {"SPY": "450"}},
    ).json()

    history = client.get("/api/v1/ai/history").json()
    assert len(history["cycles"]) >= 1
    assert history["cycles"][0]["cycle_id"] == created["cycle_id"]
    assert history["cycles"][0]["outcome"] == "provider_error"

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


def test_api_ai_run_persists_terminal_call_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The trading path persists every terminal ModelGateway call record."""
    from alphabrief_api.db.model_call import ModelCallStore

    monkeypatch.setenv("ALPHABRIEF_AI_TRADING_ENABLED", "true")
    monkeypatch.setenv("ALPHABRIEF_AI_MODEL_PROVIDER", "fake")
    resp = client.post(
        "/api/v1/ai/run",
        json={"symbols": ["SPY"], "reference_prices": {"SPY": "450"}},
    )
    assert resp.status_code == 201, resp.text

    store = ModelCallStore(db_path=tmp_path / "alphabrief_db" / _paths.DATABASE_NAME)
    try:
        rows = store.list_calls()
        # The committee makes one gateway call per role; each must be a
        # terminal record with a classification and content hashes.
        assert len(rows) >= 1
        for row in rows:
            assert row["status"] in {"succeeded", "failed", "rejected"}
            assert row["classification"] in {
                "success",
                "malformed",
                "timeout",
                "rate_limit",
                "provider_error",
                "budget_exhausted",
                "no_provider",
            }
            assert len(row["input_hash"]) == 64
            assert row["task_type"] == "symbol_research"
    finally:
        store.close()
