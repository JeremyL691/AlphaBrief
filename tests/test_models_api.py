"""Tests for the models API routes (Phase 14 Round 4)."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alphabrief_api.main import app
from alphabrief_api.routes.models import _clear_store, _set_kronos_runtime
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path) -> Generator[None, None, None]:
    os.environ["ALPHABRIEF_DATA_DIR"] = str(tmp_path / "alphabrief_db")
    _clear_store()
    _set_kronos_runtime(None)
    yield
    _clear_store()
    _set_kronos_runtime(None)


def test_list_datasets_returns_bundled() -> None:
    resp = client.get("/api/v1/models/datasets")
    assert resp.status_code == 200
    body = resp.json()
    ids = {d["dataset_id"] for d in body["datasets"]}
    assert "daily_brief_v1" in ids
    assert "market_summary_v1" in ids


def test_evaluate_creates_record() -> None:
    resp = client.post(
        "/api/v1/models/evaluate",
        json={
            "model_id": "fake:fake-model",
            "task_type": "daily_brief",
            "dataset_id": "daily_brief_v1",
            "sample_count": 2,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["model_id"] == "fake:fake-model"
    assert body["task_type"] == "daily_brief"
    assert body["dataset_id"] == "daily_brief_v1"
    assert body["sample_count"] == 2
    assert body["eval_id"].startswith("eval_")


def test_evaluate_rejects_unknown_dataset() -> None:
    resp = client.post(
        "/api/v1/models/evaluate",
        json={
            "model_id": "fake:fake-model",
            "task_type": "daily_brief",
            "dataset_id": "nonexistent",
            "sample_count": 1,
        },
    )
    assert resp.status_code == 422
    assert "unknown dataset_id" in resp.json()["detail"]


def test_evaluate_rejects_task_type_mismatch() -> None:
    resp = client.post(
        "/api/v1/models/evaluate",
        json={
            "model_id": "fake:fake-model",
            "task_type": "risk_review",
            "dataset_id": "daily_brief_v1",
            "sample_count": 1,
        },
    )
    assert resp.status_code == 422
    assert "does not match" in resp.json()["detail"]


def test_evaluate_rejects_malformed_model_id() -> None:
    resp = client.post(
        "/api/v1/models/evaluate",
        json={
            "model_id": "no-colon",
            "task_type": "daily_brief",
            "dataset_id": "daily_brief_v1",
            "sample_count": 1,
        },
    )
    assert resp.status_code == 422


def test_list_evaluations_empty() -> None:
    resp = client.get("/api/v1/models/evaluations")
    assert resp.status_code == 200
    body = resp.json()
    assert body["entries"] == []
    assert body["total"] == 0


def test_list_evaluations_returns_saved() -> None:
    client.post(
        "/api/v1/models/evaluate",
        json={
            "model_id": "fake:fake-model",
            "task_type": "daily_brief",
            "dataset_id": "daily_brief_v1",
            "sample_count": 1,
        },
    )
    resp = client.get("/api/v1/models/evaluations")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["entries"]) == 1
    assert body["entries"][0]["model_id"] == "fake:fake-model"


def test_list_evaluations_filter_by_model_id() -> None:
    client.post(
        "/api/v1/models/evaluate",
        json={
            "model_id": "fake:fake-model",
            "task_type": "daily_brief",
            "dataset_id": "daily_brief_v1",
            "sample_count": 1,
        },
    )
    client.post(
        "/api/v1/models/evaluate",
        json={
            "model_id": "fake:other-model",
            "task_type": "daily_brief",
            "dataset_id": "daily_brief_v1",
            "sample_count": 1,
        },
    )
    resp = client.get("/api/v1/models/evaluations?model_id=fake:fake-model")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["entries"]) == 1
    assert body["entries"][0]["model_id"] == "fake:fake-model"


def test_get_evaluation_by_id() -> None:
    create = client.post(
        "/api/v1/models/evaluate",
        json={
            "model_id": "fake:fake-model",
            "task_type": "daily_brief",
            "dataset_id": "daily_brief_v1",
            "sample_count": 1,
        },
    ).json()
    eid = create["eval_id"]
    resp = client.get(f"/api/v1/models/evaluations/{eid}")
    assert resp.status_code == 200
    assert resp.json()["id"] == eid


def test_get_evaluation_by_id_404() -> None:
    resp = client.get("/api/v1/models/evaluations/eval_nonexistent")
    assert resp.status_code == 404


def test_performance_summary_404_when_empty() -> None:
    resp = client.get("/api/v1/models/performance/fake:fake-model")
    assert resp.status_code == 404


def test_performance_summary_aggregates_per_task() -> None:
    client.post(
        "/api/v1/models/evaluate",
        json={
            "model_id": "fake:fake-model",
            "task_type": "daily_brief",
            "dataset_id": "daily_brief_v1",
            "sample_count": 1,
        },
    )
    client.post(
        "/api/v1/models/evaluate",
        json={
            "model_id": "fake:fake-model",
            "task_type": "market_summary",
            "dataset_id": "market_summary_v1",
            "sample_count": 1,
        },
    )
    resp = client.get("/api/v1/models/performance/fake:fake-model")
    assert resp.status_code == 200
    body = resp.json()
    assert "daily_brief" in body["evaluations_by_task"]
    assert "market_summary" in body["evaluations_by_task"]
    assert body["latest_evaluated_at"] is not None


def test_performance_summary_rejects_malformed_model_id() -> None:
    resp = client.get("/api/v1/models/performance/no-colon")
    assert resp.status_code == 422


def test_route_returns_decision_with_performance() -> None:
    client.post(
        "/api/v1/models/evaluate",
        json={
            "model_id": "anthropic:claude-3",
            "task_type": "daily_brief",
            "dataset_id": "daily_brief_v1",
            "sample_count": 2,
        },
    )
    resp = client.post(
        "/api/v1/models/route",
        json={
            "task_type": "daily_brief",
            "required_capabilities": ["text_generation", "structured_output"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["profile_id"] in ("fake_default", "openai_default", "anthropic_strong")
    assert body["candidates"]


def test_route_falls_back_without_performance() -> None:
    resp = client.post(
        "/api/v1/models/route",
        json={
            "task_type": "test",
            "required_capabilities": ["text_generation"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["used_performance_data"] is False
    assert body["profile_id"] in ("fake_default", "openai_default", "anthropic_strong")


def test_route_rejects_empty_capabilities() -> None:
    resp = client.post(
        "/api/v1/models/route",
        json={
            "task_type": "daily_brief",
            "required_capabilities": [],
        },
    )
    assert resp.status_code == 422


def test_compare_returns_rows_for_each_model() -> None:
    client.post(
        "/api/v1/models/evaluate",
        json={
            "model_id": "fake:fake-model",
            "task_type": "daily_brief",
            "dataset_id": "daily_brief_v1",
            "sample_count": 1,
        },
    )
    client.post(
        "/api/v1/models/evaluate",
        json={
            "model_id": "anthropic:claude-3",
            "task_type": "daily_brief",
            "dataset_id": "daily_brief_v1",
            "sample_count": 1,
        },
    )
    resp = client.post(
        "/api/v1/models/compare",
        json={
            "model_ids": ["fake:fake-model", "anthropic:claude-3"],
            "task_type": "daily_brief",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["rows"]) == 2
    by_model = {r["model_id"]: r for r in body["rows"]}
    assert by_model["fake:fake-model"]["has_data"] is True
    assert by_model["anthropic:claude-3"]["has_data"] is True


def test_compare_marks_missing_models() -> None:
    resp = client.post(
        "/api/v1/models/compare",
        json={
            "model_ids": ["fake:fake-model", "openai:gpt-4o-mini"],
            "task_type": "daily_brief",
        },
    )
    assert resp.status_code == 200
    rows = resp.json()["rows"]
    assert all(r["has_data"] is False for r in rows)


def test_compare_rejects_malformed_model_id() -> None:
    resp = client.post(
        "/api/v1/models/compare",
        json={
            "model_ids": ["fake:fake-model", "no-colon"],
            "task_type": "daily_brief",
        },
    )
    assert resp.status_code == 422


def test_compare_rejects_single_model() -> None:
    resp = client.post(
        "/api/v1/models/compare",
        json={
            "model_ids": ["fake:fake-model"],
            "task_type": "daily_brief",
        },
    )
    assert resp.status_code == 422


def _kronos_bars() -> list[dict[str, str]]:
    return [
        {
            "symbol": "SPY",
            "timestamp": "2026-06-01T13:30:00+00:00",
            "open": "100",
            "high": "101",
            "low": "99",
            "close": "100",
            "volume": "1000",
            "source": "unit",
            "data_version": "v1",
        },
        {
            "symbol": "SPY",
            "timestamp": "2026-06-02T13:30:00+00:00",
            "open": "101",
            "high": "102",
            "low": "100",
            "close": "101",
            "volume": "1000",
            "source": "unit",
            "data_version": "v1",
        },
        {
            "symbol": "SPY",
            "timestamp": "2026-06-03T13:30:00+00:00",
            "open": "102",
            "high": "103",
            "low": "101",
            "close": "102",
            "volume": "1000",
            "source": "unit",
            "data_version": "v1",
        },
    ]


def test_kronos_forecast_endpoint_runs_deterministic_runtime() -> None:
    resp = client.post(
        "/api/v1/models/kronos/forecast",
        json={
            "request_id": "api_req_1",
            "symbol": "SPY",
            "bars": _kronos_bars(),
            "prediction_length": 2,
            "runtime_mode": "deterministic",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["report"]["symbol"] == "SPY"
    assert body["report"]["prediction_length"] == 2
    assert body["report"]["advisory_only"] is True
    assert body["evidence"]["advisory_only"] is True
    assert body["model_call_provider"] == "kronos"


def test_kronos_forecast_endpoint_fails_when_runtime_unconfigured() -> None:
    resp = client.post(
        "/api/v1/models/kronos/forecast",
        json={
            "symbol": "SPY",
            "bars": _kronos_bars(),
            "prediction_length": 2,
        },
    )
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "kronos_forecast_unavailable"
