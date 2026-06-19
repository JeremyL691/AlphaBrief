"""API tests for the strategy signal history routes (Phase 15 R15.5)."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alphabrief_api.main import app
from alphabrief_api.routes.paper import _reset_broker
from alphabrief_api.routes.risk import _reset_risk_gate
from alphabrief_api.routes.strategies import _clear_strategy_store
from alphabrief_api.routes.strategy_signals import _clear_signal_store
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path) -> Generator[None, None, None]:
    os.environ["ALPHABRIEF_DATA_DIR"] = str(tmp_path / "alphabrief_db")
    _clear_strategy_store()
    _clear_signal_store()
    _reset_broker()
    _reset_risk_gate()
    yield
    _clear_strategy_store()
    _clear_signal_store()


def _signal(
    signal_id: str = "sig_1",
    strategy_id: str = "ema_trend_v1",
    symbol: str = "BTC-USD",
    ts: str = "2024-06-01T00:00:00+00:00",
    direction: str = "long",
    confidence: float = 0.8,
    horizon: str = "1d",
) -> dict[str, object]:
    return {
        "signal_id": signal_id,
        "strategy_id": strategy_id,
        "symbol": symbol,
        "timestamp": ts,
        "direction": direction,
        "confidence": confidence,
        "horizon": horizon,
        "rationale": f"rationale for {signal_id}",
    }


# ---------------------------------------------------------------------------
# POST /api/v1/strategies/signals
# ---------------------------------------------------------------------------


def test_record_signal_succeeds() -> None:
    resp = client.post(
        "/api/v1/strategies/signals",
        json={"signal": _signal()},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["signal_id"] == "sig_1"
    assert body["strategy_id"] == "ema_trend_v1"
    assert body["source"] == "other"


def test_record_signal_with_source() -> None:
    resp = client.post(
        "/api/v1/strategies/signals",
        json={"signal": _signal(signal_id="b1"), "source": "backtest"},
    )
    assert resp.status_code == 201
    assert resp.json()["source"] == "backtest"


def test_record_signal_rejects_invalid_source() -> None:
    resp = client.post(
        "/api/v1/strategies/signals",
        json={"signal": _signal(), "source": "nope"},
    )
    assert resp.status_code == 422


def test_record_signal_rejects_missing_confidence() -> None:
    bad = _signal()
    del bad["confidence"]
    resp = client.post(
        "/api/v1/strategies/signals",
        json={"signal": bad},
    )
    assert resp.status_code == 422


def test_record_signal_rejects_out_of_range_confidence() -> None:
    resp = client.post(
        "/api/v1/strategies/signals",
        json={"signal": _signal(confidence=1.5)},
    )
    assert resp.status_code == 422


def test_record_signal_rejects_blank_signal_id() -> None:
    resp = client.post(
        "/api/v1/strategies/signals",
        json={"signal": _signal(signal_id="")},
    )
    assert resp.status_code == 422


def test_record_signal_rejects_extra_fields_in_request() -> None:
    resp = client.post(
        "/api/v1/strategies/signals",
        json={"signal": _signal(), "rogue": "field"},
    )
    assert resp.status_code == 422


def test_record_signal_upserts_existing() -> None:
    client.post("/api/v1/strategies/signals", json={"signal": _signal()})
    client.post(
        "/api/v1/strategies/signals",
        json={"signal": _signal(confidence=0.4), "source": "manual"},
    )
    body = client.get("/api/v1/strategies/signals/sig_1").json()
    assert body["confidence"] == 0.4
    assert body["source"] == "manual"


# ---------------------------------------------------------------------------
# GET /api/v1/strategies/signals
# ---------------------------------------------------------------------------


def test_list_signals_empty() -> None:
    resp = client.get("/api/v1/strategies/signals")
    assert resp.status_code == 200
    assert resp.json() == {"signals": []}


def test_list_signals_returns_summaries() -> None:
    client.post(
        "/api/v1/strategies/signals",
        json={"signal": _signal(signal_id="a")},
    )
    client.post(
        "/api/v1/strategies/signals",
        json={"signal": _signal(signal_id="b", ts="2024-12-01T00:00:00+00:00")},
    )
    resp = client.get("/api/v1/strategies/signals")
    assert resp.status_code == 200
    rows = resp.json()["signals"]
    assert len(rows) == 2
    for row in rows:
        assert "signal" not in row


def test_list_signals_filter_by_strategy() -> None:
    client.post(
        "/api/v1/strategies/signals",
        json={"signal": _signal(signal_id="a", strategy_id="s1")},
    )
    client.post(
        "/api/v1/strategies/signals",
        json={"signal": _signal(signal_id="b", strategy_id="s2")},
    )
    resp = client.get("/api/v1/strategies/signals?strategy_id=s1")
    assert resp.status_code == 200
    rows = resp.json()["signals"]
    assert len(rows) == 1
    assert rows[0]["signal_id"] == "a"


def test_list_signals_filter_by_symbol() -> None:
    client.post(
        "/api/v1/strategies/signals",
        json={"signal": _signal(signal_id="a", symbol="BTC-USD")},
    )
    client.post(
        "/api/v1/strategies/signals",
        json={"signal": _signal(signal_id="b", symbol="ETH-USD")},
    )
    resp = client.get("/api/v1/strategies/signals?symbol=ETH-USD")
    assert resp.status_code == 200
    rows = resp.json()["signals"]
    assert len(rows) == 1
    assert rows[0]["signal_id"] == "b"


def test_list_signals_filter_by_source() -> None:
    client.post(
        "/api/v1/strategies/signals",
        json={"signal": _signal(signal_id="a"), "source": "backtest"},
    )
    client.post(
        "/api/v1/strategies/signals",
        json={"signal": _signal(signal_id="b"), "source": "manual"},
    )
    resp = client.get("/api/v1/strategies/signals?source=manual")
    rows = resp.json()["signals"]
    assert len(rows) == 1
    assert rows[0]["signal_id"] == "b"


def test_list_signals_limit() -> None:
    for i in range(5):
        client.post(
            "/api/v1/strategies/signals",
            json={
                "signal": _signal(
                    signal_id=f"s{i}",
                    ts=f"2024-01-0{i + 1}T00:00:00+00:00",
                )
            },
        )
    resp = client.get("/api/v1/strategies/signals?limit=2")
    assert len(resp.json()["signals"]) == 2


def test_list_signals_ordered_by_ts_desc() -> None:
    timestamps = [
        "2024-01-01T00:00:00+00:00",
        "2024-06-01T00:00:00+00:00",
        "2024-03-01T00:00:00+00:00",
    ]
    for i, ts in enumerate(timestamps):
        client.post(
            "/api/v1/strategies/signals",
            json={"signal": _signal(signal_id=f"s{i}", ts=ts)},
        )
    rows = client.get("/api/v1/strategies/signals").json()["signals"]
    ids = [r["signal_id"] for r in rows]
    assert ids == ["s1", "s2", "s0"]


# ---------------------------------------------------------------------------
# GET /api/v1/strategies/signals/{signal_id}
# ---------------------------------------------------------------------------


def test_get_signal_returns_full_record() -> None:
    client.post("/api/v1/strategies/signals", json={"signal": _signal()})
    resp = client.get("/api/v1/strategies/signals/sig_1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["signal_id"] == "sig_1"
    assert body["signal"]["rationale"] == "rationale for sig_1"


def test_get_signal_404_for_missing() -> None:
    resp = client.get("/api/v1/strategies/signals/nope")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/strategies/signals/{signal_id}
# ---------------------------------------------------------------------------


def test_delete_signal() -> None:
    client.post("/api/v1/strategies/signals", json={"signal": _signal()})
    resp = client.delete("/api/v1/strategies/signals/sig_1")
    assert resp.status_code == 200
    assert resp.json() == {"signal_id": "sig_1", "deleted": True}
    get_resp = client.get("/api/v1/strategies/signals/sig_1")
    assert get_resp.status_code == 404


def test_delete_signal_404_for_missing() -> None:
    resp = client.delete("/api/v1/strategies/signals/nope")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/strategies/{strategy_id}/signals/count
# ---------------------------------------------------------------------------


def test_count_signals_for_strategy() -> None:
    client.post(
        "/api/v1/strategies/signals",
        json={"signal": _signal(signal_id="a", strategy_id="s1")},
    )
    client.post(
        "/api/v1/strategies/signals",
        json={"signal": _signal(signal_id="b", strategy_id="s1")},
    )
    client.post(
        "/api/v1/strategies/signals",
        json={"signal": _signal(signal_id="c", strategy_id="s2")},
    )
    resp = client.get("/api/v1/strategies/s1/signals/count")
    assert resp.status_code == 200
    assert resp.json() == {"strategy_id": "s1", "count": 2}

    resp_zero = client.get("/api/v1/strategies/empty/signals/count")
    assert resp_zero.json() == {"strategy_id": "empty", "count": 0}


# ---------------------------------------------------------------------------
# Advisory nature
# ---------------------------------------------------------------------------


def test_signal_history_does_not_affect_risk_decisions() -> None:
    """Recording a signal must not change the risk gate's decision.

    The signal history is a write-only log of strategy output. The
    risk gate, paper broker, and live-trading lock remain
    completely independent. This is the same safety property as
    the registry ``enabled`` flag.
    """
    from datetime import UTC, datetime
    from decimal import Decimal

    from alphabrief_core import OrderIntent
    from alphabrief_risk import RiskGate, RiskLimitConfig

    gate = RiskGate(limits=RiskLimitConfig())

    # Record several signals.
    for i in range(3):
        client.post(
            "/api/v1/strategies/signals",
            json={
                "signal": _signal(
                    signal_id=f"x{i}",
                    strategy_id="ghost",
                    confidence=0.9,
                ),
                "source": "backtest",
            },
        )

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
    decision = gate.evaluate(intent, strategy_id="ghost")
    # No allowlist, no live trading, no signal history consulted.
    # The decision is approved because the base checks pass.
    assert decision.approved is True
