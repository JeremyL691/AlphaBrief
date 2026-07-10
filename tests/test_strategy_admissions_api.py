"""API tests for append-only strategy-admission evidence."""

from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_api.db import StrategySpecStore
from alphabrief_api.main import app
from alphabrief_api.routes.risk import _reset_risk_gate
from alphabrief_api.routes.strategies import _clear_strategy_store
from alphabrief_core import OrderIntent
from alphabrief_risk import RiskGate, RiskLimitConfig
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path) -> Generator[None, None, None]:
    os.environ["ALPHABRIEF_DATA_DIR"] = str(tmp_path / "alphabrief_db")
    _clear_strategy_store()
    _reset_risk_gate()
    yield
    _clear_strategy_store()
    _reset_risk_gate()


def _spec(
    strategy_id: str = "ema_trend_v1",
    version: str = "1.0.0",
) -> dict[str, object]:
    return {
        "strategy_id": strategy_id,
        "name": "EMA Trend v1",
        "version": version,
        "universe": {"symbols": ["SPY"]},
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


def _admission(
    *,
    strategy_id: str = "ema_trend_v1",
    version: str = "1.0.0",
    status: str = "approved",
) -> dict[str, object]:
    return {
        "strategy_id": strategy_id,
        "strategy_version": version,
        "status": status,
        "reviewer_id": "risk-owner",
        "reviewed_at": "2026-06-20T09:30:00+00:00",
        "evidence": {
            "data_version": "bars-2026-06-20",
            "in_sample_backtest_report_id": "backtest-in-sample-1",
            "out_of_sample_backtest_report_id": "backtest-out-of-sample-1",
            "fee_bps": "5",
            "slippage_bps": "10",
            "lookahead_check_passed": True,
            "risk_review_notes": ["Costs and data provenance reviewed."],
            "disabled_conditions": ["RiskGate rejection", "manual suspension"],
        },
    }


def _create_spec(
    strategy_id: str = "ema_trend_v1",
    version: str = "1.0.0",
) -> None:
    response = client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec(strategy_id, version)},
    )
    assert response.status_code == 201


def test_create_and_read_append_only_admission_record() -> None:
    _create_spec()

    created = client.post("/api/v1/strategy-admissions", json=_admission())

    assert created.status_code == 201
    body = created.json()
    assert body["strategy_id"] == "ema_trend_v1"
    assert body["status"] == "approved"
    assert body["evidence"]["lookahead_check_passed"] is True
    admission_id = body["admission_id"]

    fetched = client.get(f"/api/v1/strategy-admissions/{admission_id}")
    assert fetched.status_code == 200
    assert fetched.json()["reviewer_id"] == "risk-owner"
    patch = client.patch(f"/api/v1/strategy-admissions/{admission_id}")
    delete = client.delete(f"/api/v1/strategy-admissions/{admission_id}")
    assert patch.status_code == 405
    assert delete.status_code == 405


def test_list_filters_and_supersedes_same_strategy_only() -> None:
    _create_spec()
    first = client.post("/api/v1/strategy-admissions", json=_admission())
    assert first.status_code == 201

    replacement = _admission(status="suspended")
    replacement["supersedes_admission_id"] = first.json()["admission_id"]
    second = client.post("/api/v1/strategy-admissions", json=replacement)
    assert second.status_code == 201

    listed = client.get(
        "/api/v1/strategy-admissions?strategy_id=ema_trend_v1&status=suspended"
    )
    assert listed.status_code == 200
    admissions = listed.json()["admissions"]
    assert len(admissions) == 1
    assert admissions[0]["supersedes_admission_id"] == first.json()["admission_id"]


def test_admission_requires_existing_strategy_matching_version_and_evidence() -> None:
    missing = client.post("/api/v1/strategy-admissions", json=_admission())
    assert missing.status_code == 404

    _create_spec()
    wrong_version = client.post(
        "/api/v1/strategy-admissions",
        json=_admission(version="2.0.0"),
    )
    assert wrong_version.status_code == 422

    bad_approval = _admission()
    evidence = bad_approval["evidence"]
    assert isinstance(evidence, dict)
    evidence["lookahead_check_passed"] = False
    response = client.post("/api/v1/strategy-admissions", json=bad_approval)
    assert response.status_code == 422


def test_approval_record_cannot_grant_execution_authority() -> None:
    _create_spec()
    created = client.post("/api/v1/strategy-admissions", json=_admission())
    assert created.status_code == 201

    config = client.get("/api/v1/risk/config")
    assert config.status_code == 200
    assert config.json()["enabled_strategies"] == []
    # Round 0063: default allowlist is the OANDA multi-asset universe.
    assert config.json()["symbol_allowlist"] == sorted([
        "EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "AUD_USD", "USD_CAD", "NZD_USD",
        "EUR_GBP", "EUR_JPY", "GBP_JPY", "AUD_JPY", "CHF_JPY",
        "XAU_USD", "XAG_USD",
        "US30_USD", "SPX500_USD", "NAS100_USD", "DE30_EUR", "JP225_USD",
    ])
    assert config.json()["max_order_value"] == "10000"
    assert config.json()["require_human_review"] is True

    gate = RiskGate(limits=RiskLimitConfig(enabled_strategies=frozenset()))
    intent = OrderIntent(
        intent_id="admission-cannot-authorize",
        source="strategy",
        symbol="EUR_USD",
        side="buy",
        order_type="market",
        quantity=Decimal("1"),
        rationale="admission safety test",
        created_at=datetime(2026, 6, 20, tzinfo=UTC),
    )
    decision = gate.evaluate(intent, strategy_id="ema_trend_v1")
    assert decision.approved is False
    assert "strategy_disabled" in decision.risk_tags


def test_admission_schema_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "admissions.duckdb"
    first = StrategySpecStore(database_path)
    first.close()

    second = StrategySpecStore(database_path)
    assert second.list_admissions() == []
    second.close()
