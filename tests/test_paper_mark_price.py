"""R21.1 — real mark prices wired into the paper order flow.

The paper route previously hardcoded ``reference_price = Decimal("100")``,
which meant the ``max_order_notional=$100`` and ``max_total_exposure=$300``
caps from ``PaperExecutionPolicy`` were validated against a price chosen
to never trip them — the limits did not bind. R21.1 resolves the mark
price from the latest stored daily close (``MarketDataStore.get_bar_models``)
and fails closed (``missing_mark_price``) when no bars are stored.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_api.main import app
from alphabrief_api.routes.data import _close_store
from alphabrief_api.routes.paper import _reset_broker
from alphabrief_api.routes.risk import _reset_risk_gate
from alphabrief_risk import RiskLimitConfig
from fastapi.testclient import TestClient
from httpx import Response

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate_stores(tmp_path: Path) -> Generator[None, None, None]:
    """Isolate DuckDB stores so mark-price tests never touch real data."""
    os.environ["ALPHABRIEF_DATA_DIR"] = str(tmp_path / "alphabrief_db")
    _close_store()
    _reset_broker()
    _reset_risk_gate()
    yield
    _close_store()


def _no_review_gate(
    max_order_value: Decimal,
    max_total_exposure: Decimal | None = None,
) -> None:
    """A gate with human review off so the mark-price path is reachable."""
    _reset_risk_gate(
        RiskLimitConfig(
            trading_enabled=True,
            live_trading_enabled=False,
            symbol_allowlist=frozenset({"SPY"}),
            enabled_strategies=frozenset(),
            max_order_value=max_order_value,
            max_order_quantity=Decimal("10"),
            max_total_exposure=max_total_exposure,
            require_data_quality_passed=False,
            require_human_review=False,
        )
    )


def _load_spy(tmp_path: Path, close: str) -> None:
    c = Decimal(close)
    csv_path = tmp_path / "spy.csv"
    csv_path.write_text(
        "timestamp,open,high,low,close,volume\n"
        f"2026-06-12T09:30:00,{c},{c + Decimal('5')},{c - Decimal('2')},"
        f"{c},1000.0\n",
        encoding="utf-8",
    )
    resp = client.post(
        "/api/v1/data/load",
        json={"file_path": str(csv_path), "symbol": "SPY", "source": "test"},
    )
    assert resp.status_code == 201, resp.text


def _buy(quantity: str = "1", rationale: str = "mark-price test") -> Response:
    return client.post(  # type: ignore[no-any-return]
        "/api/v1/paper/orders",
        json={
            "symbol": "SPY",
            "side": "buy",
            "order_type": "market",
            "quantity": quantity,
            "rationale": rationale,
        },
    )


def test_order_for_symbol_with_stored_bars_uses_real_close_as_mark(
    tmp_path: Path,
) -> None:
    _no_review_gate(max_order_value=Decimal("200"))
    _load_spy(tmp_path, close="150.0")

    resp = _buy("1")

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["symbol"] == "SPY"
    assert body["status"] == "filled"
    # The fill price equals the resolved mark (FillSimulator defaults to
    # 0 bps slippage/fee), proving the real stored close flowed through.
    assert Decimal(body["price"]) == Decimal("150.0")


def test_order_for_symbol_without_stored_bars_fails_closed(tmp_path: Path) -> None:
    _no_review_gate(max_order_value=Decimal("200"))
    # No bars loaded for SPY -> the route must reject before RiskGate.

    resp = _buy("1")

    assert resp.status_code == 422
    assert "missing_mark_price" in resp.json()["detail"]
    # No order was created and no fill audit event was recorded.
    audit = client.get("/api/v1/paper/audit").json()
    event_types = {e["event_type"] for e in audit["entries"]}
    assert "order_created" not in event_types
    assert "fill_created" not in event_types


def test_total_exposure_cap_binds_against_real_mark_not_placeholder(
    tmp_path: Path,
) -> None:
    # Real close $200. Cap $250. Buy 1 -> exposure $200 <= $250 (fills).
    # Buy 1 again -> projected exposure $400 > $250 -> rejected. If the
    # route still used the $100 fiction, $200 projected would pass and
    # this second order would wrongly fill at 201.
    _no_review_gate(max_order_value=Decimal("200"), max_total_exposure=Decimal("250"))
    _load_spy(tmp_path, close="200.0")

    first = _buy("1", rationale="first fill")
    assert first.status_code == 201, first.text

    second = _buy("1", rationale="should breach at real price")
    assert second.status_code == 422
    assert "max_total_exposure" in second.json()["detail"]


def test_order_value_at_exact_cap_boundary_is_approved(tmp_path: Path) -> None:
    # Real close $200, max_order_value $200: qty*price == cap exactly.
    _no_review_gate(max_order_value=Decimal("200"))
    _load_spy(tmp_path, close="200.0")

    resp = _buy("1")

    assert resp.status_code == 201, resp.text


def test_risk_decision_audit_event_records_resolved_reference_price(
    tmp_path: Path,
) -> None:
    _no_review_gate(max_order_value=Decimal("200"))
    _load_spy(tmp_path, close="175.0")

    resp = _buy("1")
    assert resp.status_code == 201, resp.text

    from alphabrief_api.routes.paper import _get_paper_store

    raw = _get_paper_store().get_audit_events(event_type="risk_decision_recorded")
    route_event = next(e for e in raw if "reference_price" in e["details"])
    # The resolved real close (not the old "100" placeholder) is recorded.
    assert Decimal(route_event["details"]["reference_price"]) == Decimal("175.0")
