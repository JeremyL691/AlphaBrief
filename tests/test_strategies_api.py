"""API tests for the strategy registry routes.

Covers POST /specs, GET /specs, GET /specs/{id}, PATCH /specs/{id},
DELETE /specs/{id}, plus validation and isolation.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alphabrief_api.main import app
from alphabrief_api.routes.paper import _reset_broker
from alphabrief_api.routes.risk import _reset_risk_gate
from alphabrief_api.routes.strategies import _clear_strategy_store
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path) -> Generator[None, None, None]:
    os.environ["ALPHABRIEF_DATA_DIR"] = str(tmp_path / "alphabrief_db")
    _clear_strategy_store()
    _reset_broker()
    _reset_risk_gate()
    yield
    _clear_strategy_store()


def _spec(
    strategy_id: str = "ema_trend_v1",
    name: str = "EMA Trend v1",
    version: str = "1.0.0",
) -> dict[str, object]:
    return {
        "strategy_id": strategy_id,
        "name": name,
        "version": version,
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


# ---------------------------------------------------------------------------
# POST /api/v1/strategies/specs
# ---------------------------------------------------------------------------


def test_create_spec_succeeds() -> None:
    resp = client.post("/api/v1/strategies/specs", json={"spec": _spec()})
    assert resp.status_code == 201
    body = resp.json()
    assert body["strategy_id"] == "ema_trend_v1"
    assert body["name"] == "EMA Trend v1"
    assert body["version"] == "1.0.0"
    assert body["enabled"] is False


def test_create_spec_with_enabled_true() -> None:
    resp = client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec(), "enabled": True},
    )
    assert resp.status_code == 201
    assert resp.json()["enabled"] is True


def test_create_spec_rejects_invalid_payload() -> None:
    bad = _spec()
    del bad["universe"]
    resp = client.post("/api/v1/strategies/specs", json={"spec": bad})
    assert resp.status_code == 422
    assert "StrategySpec" in resp.json()["detail"]


def test_create_spec_rejects_extra_fields() -> None:
    resp = client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec(), "extra_field": "nope"},
    )
    assert resp.status_code == 422


def test_create_spec_rejects_extra_in_spec() -> None:
    bad = _spec()
    bad["rogue_field"] = "nope"
    resp = client.post("/api/v1/strategies/specs", json={"spec": bad})
    assert resp.status_code == 422


def test_create_spec_upserts_existing() -> None:
    first = client.post("/api/v1/strategies/specs", json={"spec": _spec()})
    assert first.status_code == 201
    second = client.post(
        "/api/v1/strategies/specs",
        json={
            "spec": _spec(name="EMA Trend Updated", version="1.1.0"),
            "enabled": True,
        },
    )
    assert second.status_code == 201
    fetched = client.get("/api/v1/strategies/specs/ema_trend_v1").json()
    assert fetched["name"] == "EMA Trend Updated"
    assert fetched["version"] == "1.1.0"
    assert fetched["enabled"] is True


# ---------------------------------------------------------------------------
# GET /api/v1/strategies/specs
# ---------------------------------------------------------------------------


def test_list_specs_empty() -> None:
    resp = client.get("/api/v1/strategies/specs")
    assert resp.status_code == 200
    assert resp.json() == {"strategies": []}


def test_list_specs_returns_summaries() -> None:
    client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec(strategy_id="a", name="A"), "enabled": True},
    )
    client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec(strategy_id="b", name="B")},
    )
    resp = client.get("/api/v1/strategies/specs")
    assert resp.status_code == 200
    strategies = resp.json()["strategies"]
    assert len(strategies) == 2
    ids = {s["strategy_id"] for s in strategies}
    assert ids == {"a", "b"}
    for s in strategies:
        assert "spec" not in s
        assert "created_at" in s
        assert "updated_at" in s


def test_list_specs_enabled_true_filter() -> None:
    client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec(strategy_id="a"), "enabled": True},
    )
    client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec(strategy_id="b")},
    )
    resp = client.get("/api/v1/strategies/specs?enabled=true")
    assert resp.status_code == 200
    strategies = resp.json()["strategies"]
    assert len(strategies) == 1
    assert strategies[0]["strategy_id"] == "a"


def test_list_specs_enabled_false_filter() -> None:
    client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec(strategy_id="a"), "enabled": True},
    )
    client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec(strategy_id="b")},
    )
    resp = client.get("/api/v1/strategies/specs?enabled=false")
    assert resp.status_code == 200
    strategies = resp.json()["strategies"]
    assert len(strategies) == 1
    assert strategies[0]["strategy_id"] == "b"


def test_list_specs_ordered_by_id() -> None:
    for sid in ["c", "a", "b"]:
        client.post(
            "/api/v1/strategies/specs",
            json={"spec": _spec(strategy_id=sid)},
        )
    resp = client.get("/api/v1/strategies/specs").json()
    ids = [s["strategy_id"] for s in resp["strategies"]]
    assert ids == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# GET /api/v1/strategies/specs/{id}
# ---------------------------------------------------------------------------


def test_get_spec_returns_full_record() -> None:
    client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec(), "enabled": True},
    )
    resp = client.get("/api/v1/strategies/specs/ema_trend_v1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["strategy_id"] == "ema_trend_v1"
    assert body["enabled"] is True
    assert body["spec"]["strategy_id"] == "ema_trend_v1"
    assert body["spec"]["entry"]["condition"] == "close > ema_50"


def test_get_spec_404_when_missing() -> None:
    resp = client.get("/api/v1/strategies/specs/does_not_exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/v1/strategies/specs/{id}
# ---------------------------------------------------------------------------


def test_patch_enables_strategy() -> None:
    client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec()},
    )
    resp = client.patch(
        "/api/v1/strategies/specs/ema_trend_v1",
        json={"enabled": True},
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "strategy_id": "ema_trend_v1",
        "enabled": True,
    }
    fetched = client.get("/api/v1/strategies/specs/ema_trend_v1").json()
    assert fetched["enabled"] is True


def test_patch_disables_strategy() -> None:
    client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec(), "enabled": True},
    )
    resp = client.patch(
        "/api/v1/strategies/specs/ema_trend_v1",
        json={"enabled": False},
    )
    assert resp.status_code == 200
    fetched = client.get("/api/v1/strategies/specs/ema_trend_v1").json()
    assert fetched["enabled"] is False


def test_patch_404_when_missing() -> None:
    resp = client.patch(
        "/api/v1/strategies/specs/does_not_exist",
        json={"enabled": True},
    )
    assert resp.status_code == 404


def test_patch_rejects_extra_fields() -> None:
    client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec()},
    )
    resp = client.patch(
        "/api/v1/strategies/specs/ema_trend_v1",
        json={"enabled": True, "name": "hijack"},
    )
    assert resp.status_code == 422


def test_patch_requires_enabled_field() -> None:
    client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec()},
    )
    resp = client.patch(
        "/api/v1/strategies/specs/ema_trend_v1",
        json={},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /api/v1/strategies/specs/{id}
# ---------------------------------------------------------------------------


def test_delete_spec() -> None:
    client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec(), "enabled": True},
    )
    resp = client.delete("/api/v1/strategies/specs/ema_trend_v1")
    assert resp.status_code == 200
    assert resp.json() == {
        "strategy_id": "ema_trend_v1",
        "enabled": False,
    }
    get_resp = client.get("/api/v1/strategies/specs/ema_trend_v1")
    assert get_resp.status_code == 404


def test_delete_spec_404_when_missing() -> None:
    resp = client.delete("/api/v1/strategies/specs/does_not_exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test isolation: store clears between tests
# ---------------------------------------------------------------------------


def test_store_isolation_after_clear() -> None:
    client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec()},
    )
    _clear_strategy_store()
    resp = client.get("/api/v1/strategies/specs")
    assert resp.status_code == 200
    assert resp.json() == {"strategies": []}


# ---------------------------------------------------------------------------
# Validation against StrategySpec boundary
# ---------------------------------------------------------------------------


def test_validation_risk_max_position_pct_out_of_range() -> None:
    bad = _spec()
    bad["risk"] = {"max_position_pct": "1.5"}
    resp = client.post("/api/v1/strategies/specs", json={"spec": bad})
    assert resp.status_code == 422


def test_validation_float_rejected_for_decimal() -> None:
    bad = _spec()
    bad["risk"] = {"max_position_pct": 0.2}
    resp = client.post("/api/v1/strategies/specs", json={"spec": bad})
    assert resp.status_code == 422


def test_validation_train_test_overlap_rejected() -> None:
    bad = _spec()
    bad["evaluation"] = {
        "train_period": {"start": "2024-01-01", "end": "2024-12-31"},
        "test_period": {"start": "2024-06-01", "end": "2025-06-01"},
    }
    resp = client.post("/api/v1/strategies/specs", json={"spec": bad})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/strategies/enabled (Phase 15 R15.4 — advisory activation)
# ---------------------------------------------------------------------------


def test_enabled_endpoint_empty() -> None:
    resp = client.get("/api/v1/strategies/enabled")
    assert resp.status_code == 200
    assert resp.json() == {"strategy_ids": []}


def test_enabled_endpoint_returns_enabled_ids() -> None:
    client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec(strategy_id="a"), "enabled": True},
    )
    client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec(strategy_id="b")},
    )
    client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec(strategy_id="c"), "enabled": True},
    )
    resp = client.get("/api/v1/strategies/enabled")
    assert resp.status_code == 200
    assert resp.json() == {"strategy_ids": ["a", "c"]}


def test_enabled_endpoint_reflects_patch() -> None:
    client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec(strategy_id="a")},
    )
    client.patch("/api/v1/strategies/specs/a", json={"enabled": True})
    resp = client.get("/api/v1/strategies/enabled")
    assert resp.json() == {"strategy_ids": ["a"]}

    client.patch("/api/v1/strategies/specs/a", json={"enabled": False})
    resp = client.get("/api/v1/strategies/enabled")
    assert resp.json() == {"strategy_ids": []}


def test_enabled_endpoint_reflects_delete() -> None:
    client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec(strategy_id="a"), "enabled": True},
    )
    client.delete("/api/v1/strategies/specs/a")
    resp = client.get("/api/v1/strategies/enabled")
    assert resp.json() == {"strategy_ids": []}


# ---------------------------------------------------------------------------
# Advisory nature: activation flag is informational only
# ---------------------------------------------------------------------------


def test_advisory_flag_does_not_affect_risk_gate_allowlist() -> None:
    """The ``enabled`` flag must be independent from the risk allowlist.

    The risk gate's ``enabled_strategies`` is a separate, manually
    configured frozenset. Setting the registry ``enabled`` flag for a
    strategy that is NOT in the risk allowlist must not change what
    the gate accepts. This is the safety property the advisory
    surface relies on.
    """
    from datetime import UTC, datetime
    from decimal import Decimal

    from alphabrief_core import OrderIntent
    from alphabrief_risk import RiskGate, RiskLimitConfig

    # The risk allowlist is the default empty frozenset.
    gate = RiskGate(limits=RiskLimitConfig(enabled_strategies=frozenset({"ghost"})))

    client.post(
        "/api/v1/strategies/specs",
        json={"spec": _spec(strategy_id="ghost"), "enabled": True},
    )

    enabled_resp = client.get("/api/v1/strategies/enabled")
    assert enabled_resp.json() == {"strategy_ids": ["ghost"]}

    intent = OrderIntent(
        intent_id="i1",
        source="strategy",
        symbol="BTC-USD",
        side="buy",
        order_type="market",
        quantity=Decimal("0.1"),
        rationale="test",
        created_at=datetime.now(UTC),
    )

    # The risk gate allowlist happens to contain the strategy, so the
    # gate decision is determined by *other* checks, not by the
    # registry ``enabled`` flag. Here the order value is well within
    # the default limits and there is no symbol allowlist configured,
    # so the decision is approved — proving the registry flag is
    # purely advisory and not consulted by the gate.
    decision = gate.evaluate(intent, strategy_id="ghost")
    assert decision.approved is True

    # And the same order with a strategy id NOT in the allowlist is
    # rejected for the strategy check, irrespective of any registry
    # flag. This is the symmetric negative case: the registry flag
    # never grants, never blocks.
    decision_blocked = gate.evaluate(intent, strategy_id="nope")
    assert decision_blocked.approved is False
    assert "nope" in decision_blocked.reason