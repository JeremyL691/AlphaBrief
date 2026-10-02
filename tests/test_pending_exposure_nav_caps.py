"""Complete native pending-order coverage and fresh NAV-derived exposure caps."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alphabrief_execution.broker.oanda.order_ops import (
    OrderOperationError,
    OrderOpsClient,
)
from alphabrief_risk.broker_context import PendingOrderDatum
from alphabrief_risk.gate import RiskGate, RiskLimitConfig
from test_oanda_gate_context import NOW, price, source
from test_production_exposure_rule import context
from test_production_margin_rule import _client, _intent

D = Decimal


def pending_client(rows: list[Any]) -> OrderOpsClient:
    client = _client({})
    client._http_send = lambda request, timeout: json.dumps({"orders": rows}).encode()
    return OrderOpsClient(client)


def row(order_id: str = "1", **updates: Any) -> dict[str, Any]:
    result = dict(
        id=order_id,
        instrument="EUR_USD",
        units="100",
        type="LIMIT",
        state="PENDING",
        price="1.2",
    )
    result.update(updates)
    return result


def test_pending_endpoint_returns_more_than_historical_page_limit() -> None:
    ops = pending_client([row(str(i)) for i in range(70)])
    response = ops.list_pending_orders()
    assert len(response.orders) == 70 and not response.has_more


@pytest.mark.parametrize(
    "changes",
    [
        {"units": None},
        {"units": 1.0},
        {"units": True},
        {"units": "NaN"},
        {"units": "0"},
        {"units": "bad"},
        {"price": 1.2},
        {"price": "NaN"},
        {"price": "-1"},
        {"price": "bad"},
        {"price": None},
        {"state": "FILLED"},
        {"instrument": None},
        {"type": None},
    ],
)
def test_incomplete_pending_entry_response_fails_closed(
    changes: dict[str, Any],
) -> None:
    with pytest.raises(OrderOperationError):
        pending_client([row(**changes)]).list_pending_orders()


def test_duplicate_pending_rows_fail_closed() -> None:
    with pytest.raises(OrderOperationError):
        pending_client([row(), row()]).list_pending_orders()


def test_protective_and_reduce_only_orders_do_not_increase_entry_exposure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = source(monkeypatch)
    monkeypatch.delattr(sources, "fetch_pending_orders")
    ops = pending_client(
        [
            row(),
            row("2", units="-100"),
            row("3", positionFill="REDUCE_ONLY"),
            dict(id="4", tradeID="9", state="PENDING", type="STOP_LOSS", price="1.1"),
            dict(id="5", tradeID="9", state="PENDING", type="TAKE_PROFIT", price="1.3"),
        ]
    )
    sources._client = ops._client
    pending = sources.fetch_pending_orders()
    assert len(pending) == 2
    assert [o.units for o in pending] == [D("100"), D("-100")]


@pytest.mark.parametrize("signed_units", ["100", "-100"])
@pytest.mark.parametrize(
    "limit_price,expected", [("1.2", "120"), ("1", "110.0100"), (None, "110.0100")]
)
def test_pending_units_add_gross_at_conservative_home_value(
    monkeypatch: pytest.MonkeyPatch,
    signed_units: str,
    limit_price: str | None,
    expected: str,
) -> None:
    sources = source(monkeypatch)
    monkeypatch.setattr(
        sources,
        "fetch_pending_orders",
        lambda: [
            PendingOrderDatum(
                broker_order_id="1",
                symbol="EUR_USD",
                state="PENDING",
                units=D(signed_units),
                price=None if limit_price is None else D(limit_price),
            )
        ],
    )
    monkeypatch.setattr(
        sources,
        "_prices_by_symbol",
        lambda: {
            "EUR_USD": price("EUR_USD", age=0, tradeable=True),
        },
    )
    result = sources.account_exposure_context(now=NOW, symbol="EUR_USD")
    assert result.exposure_complete and result.current_total_exposure == D(expected)
    assert result.pending_exposure_by_symbol == {"EUR_USD": D(expected)}


def ratio_gate(**extra: Any) -> RiskGate:
    return RiskGate(
        limits=RiskLimitConfig(
            max_order_value_pct=D(".5"),
            max_total_exposure_pct=D("1.5"),
            require_home_currency_exposure=True,
            **extra,
        ),
        clock=lambda: NOW,
    )


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_same_gate_recomputes_caps_after_nav_moves(side: str) -> None:
    gate = ratio_gate()
    intent = _intent(side).model_copy(update={"quantity": D("400")})
    for nav, approved in [("1000", True), ("500", False), ("2000", True)]:
        result = gate.evaluate(
            intent,
            estimated_price=D("100"),
            account_context=context(equity=D(nav), current_total_exposure=D(0)),
        )
        assert result.approved is approved
        evidence = result.rule_evidence["exposure_caps"]
        assert D(evidence["order_cap"]) == D(nav) * D(".5")
        assert D(evidence["total_cap"]) == D(nav) * D("1.5")
        assert result.rule_evidence["exposure"]["order_cap"] == evidence["order_cap"]


@pytest.mark.parametrize("nav", [None, D(0)])
def test_missing_nav_blocks_entries_but_not_reduce_only(nav: Decimal | None) -> None:
    ctx = context(equity=nav)
    for side in ("buy", "sell"):
        assert (
            not ratio_gate()
            .evaluate(_intent(side), estimated_price=D(100), account_context=ctx)
            .approved
        )
        assert (
            ratio_gate()
            .evaluate(_intent(side, close=True), account_context=ctx)
            .approved
        )


@pytest.mark.parametrize("age", [61, -1])
def test_old_or_future_nav_cannot_define_exposure_caps(age: int) -> None:
    result = ratio_gate().evaluate(
        _intent("buy"),
        estimated_price=D(100),
        account_context=context(captured_at=NOW - timedelta(seconds=age)),
    )
    assert not result.approved
    assert result.rule_evidence["exposure_caps"]["passed"] == "False"


@pytest.mark.parametrize("bad", [D(0), D("-1"), D("NaN"), D("Infinity"), 0.5])
def test_invalid_nav_fractions_are_rejected(bad: Any) -> None:
    with pytest.raises(ValueError):
        RiskLimitConfig(max_order_value_pct=bad)
    with pytest.raises(ValueError):
        RiskLimitConfig(max_total_exposure_pct=bad)


def test_absolute_cap_also_tightens_nav_ratio() -> None:
    result = ratio_gate(max_order_value=D("100")).evaluate(
        _intent("buy").model_copy(update={"quantity": D(101)}),
        estimated_price=D(100),
        account_context=context(current_total_exposure=D(0)),
    )
    assert not result.approved
    assert result.rule_evidence["exposure_caps"]["order_cap"] == "100"


def test_production_ratio_policy_and_fixed_units_policy_are_distinct(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from alphabrief_cli.cycle_commands import _risk_gate

    monkeypatch.setenv("ALPHABRIEF_HOME", str(tmp_path))
    live = _risk_gate(("EUR_USD",), nav=D("1000"), require_nav=True).limits
    assert live.max_order_value is None and live.max_total_exposure is None
    assert live.max_order_value_pct == D(".5") and live.max_total_exposure_pct == D(
        "1.5"
    )
    fixed = _risk_gate(("EUR_USD",)).limits
    assert fixed.max_order_value_pct is None and fixed.max_order_value is not None


@pytest.mark.parametrize("side", ["buy", "sell"])
@pytest.mark.parametrize("gross,approved", [("1400", True), ("1400.01", False)])
def test_dynamic_total_cap_includes_current_and_pending_gross(
    side: str,
    gross: str,
    approved: bool,
) -> None:
    result = ratio_gate().evaluate(
        _intent(side).model_copy(update={"quantity": D(100)}),
        estimated_price=D(100),
        account_context=context(current_total_exposure=D(gross)),
    )
    assert result.approved is approved
    assert ("max_total_exposure" in result.risk_tags) is (not approved)


@pytest.mark.parametrize("age", [None, 16, -1])
def test_missing_stale_future_pending_quote_prevents_complete_projection(
    monkeypatch: pytest.MonkeyPatch,
    age: int | None,
) -> None:
    sources = source(monkeypatch)
    monkeypatch.setattr(
        sources,
        "fetch_pending_orders",
        lambda: [
            PendingOrderDatum(
                broker_order_id="1",
                symbol="EUR_USD",
                state="PENDING",
                units=D(100),
                price=D("1.2"),
            )
        ],
    )
    monkeypatch.setattr(
        sources,
        "_prices_by_symbol",
        lambda: (
            {}
            if age is None
            else {
                "EUR_USD": price("EUR_USD", age=age, tradeable=True),
            }
        ),
    )
    result = sources.account_exposure_context(now=NOW, symbol="EUR_USD")
    assert not result.exposure_complete and "EUR_USD" in result.exposure_errors
    assert (
        not ratio_gate()
        .evaluate(_intent("sell"), estimated_price=D(1), account_context=result)
        .approved
    )


def test_native_pending_read_uses_complete_snapshot_endpoint() -> None:
    client = _client({})
    paths: list[str] = []

    def read(request: Any, timeout: float) -> bytes:
        paths.append(request.full_url)
        return b'{"orders": []}'

    client._http_send = read
    assert OrderOpsClient(client).list_pending_orders().orders == ()
    assert len(paths) == 1 and paths[0].endswith("/pendingOrders")
