"""Gross FX exposure, purpose-specific conversion, and both entry directions."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from alphabrief_execution.broker.oanda.risk_sources import OandaRiskContextSources
from alphabrief_risk.account_context import AccountExposureContext
from alphabrief_risk.gate import RiskGate, RiskLimitConfig
from alphabrief_trader.sizing import SizingInputs, size_entry
from test_oanda_gate_context import NOW, price, source
from test_production_margin_rule import _intent

D = Decimal


def context(**updates: object) -> AccountExposureContext:
    data: dict[str, object] = dict(
        current_total_exposure=D("1400"),
        cash=D("1000"),
        equity=D("1000"),
        captured_at=NOW,
        account_id="test",
        exposure_complete=True,
        quote_position_to_home={"EUR_USD": D("0.01")},
    )
    data.update(updates)
    return AccountExposureContext.model_validate(data)


def gate() -> RiskGate:
    return RiskGate(
        limits=RiskLimitConfig(
            require_home_currency_exposure=True,
            max_order_quantity=D("2000"),
            max_order_value=D("500"),
            max_total_exposure=D("1500"),
        ),
        clock=lambda: NOW,
    )


@pytest.mark.parametrize("side", ["buy", "sell"])
@pytest.mark.parametrize("quantity,approved", [("1000", True), ("1001", False)])
def test_both_entry_directions_use_home_currency_and_gross_cap(
    side: str,
    quantity: str,
    approved: bool,
) -> None:
    intent = _intent(side).model_copy(update={"quantity": D(quantity)})
    result = gate().evaluate(intent, estimated_price=D("10"), account_context=context())
    assert result.approved is approved
    assert ("max_total_exposure" in result.risk_tags) is (not approved)
    assert D(result.rule_evidence["exposure"]["order_notional"]) == D(quantity) * D(
        "0.1"
    )
    if not approved:
        assert result.max_quantity == D("1000")


@pytest.mark.parametrize(
    "updates",
    [
        {"quote_position_to_home": {}},
        {"exposure_complete": False},
        {"exposure_errors": {"GBP_USD": "missing_position_quote"}},
        {"captured_at": NOW - timedelta(seconds=61)},
        {"captured_at": NOW + timedelta(seconds=1)},
    ],
)
def test_unknown_or_stale_exposure_blocks_both_entries_but_not_reduce_only(
    updates: dict[str, object],
) -> None:
    for side in ("buy", "sell"):
        result = gate().evaluate(
            _intent(side), estimated_price=D("10"), account_context=context(**updates)
        )
        assert not result.approved and "EXPOSURE" in result.risk_tags
        close = gate().evaluate(
            _intent(side, close=True), account_context=context(**updates)
        )
        assert close.approved and close.rule_evidence == {}


@pytest.mark.parametrize("factor", [D(0), D("-1"), D("NaN"), D("Infinity"), 0.01])
def test_bad_value_conversion_rejected_by_context(factor: object) -> None:
    with pytest.raises(ValueError):
        context(quote_position_to_home={"EUR_USD": factor})


def held_source(monkeypatch: pytest.MonkeyPatch) -> OandaRiskContextSources:
    sources = source(monkeypatch)
    monkeypatch.setattr(
        sources,
        "fetch_positions",
        lambda: [
            SimpleNamespace(
                symbol="USD_JPY",
                long_units=D("1000"),
                short_units=D("-1000"),
            )
        ],
    )
    return sources


def test_native_hedged_position_keeps_both_legs_in_home_gross(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = held_source(monkeypatch)
    p = price("USD_JPY", age=0, tradeable=True)
    p.bids[0].price = p.asks[0].price = D("150")
    p.conversion_factor = D("0.006666666666666666666666666667")
    monkeypatch.setattr(sources, "_prices_by_symbol", lambda: {"USD_JPY": p})
    result = sources.account_exposure_context(now=NOW, symbol="USD_JPY")
    assert result.exposure_complete and not result.exposure_errors
    assert result.current_total_exposure == D("2000.000000000000000000000000")
    assert result.quote_position_to_home["USD_JPY"] == p.conversion_factor


@pytest.mark.parametrize("age", [16, -1, None])
def test_missing_or_stale_held_quote_marks_projection_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    age: int | None,
) -> None:
    sources = held_source(monkeypatch)
    prices = (
        {} if age is None else {"USD_JPY": price("USD_JPY", age=age, tradeable=True)}
    )
    monkeypatch.setattr(sources, "_prices_by_symbol", lambda: prices)
    result = sources.account_exposure_context(now=NOW, symbol="USD_JPY")
    assert not result.exposure_complete and "USD_JPY" in result.exposure_errors
    assert (
        not gate()
        .evaluate(_intent("sell"), estimated_price=D(1), account_context=result)
        .approved
    )


def test_sizing_uses_loss_factor_for_risk_and_value_factor_for_notional() -> None:
    result = size_entry(
        inputs=SizingInputs(
            nav=D("1000"),
            quote_to_home=D("0.02"),
            quote_position_to_home=D("0.01"),
        ),
        reference_price=D("150"),
        stop_loss=D("149.9"),
    )
    assert result.units == D("333")
    assert result.notional == D("499.50")
    assert result.actual_risk == D("0.666")


@pytest.mark.parametrize("side", ["buy", "sell"])
@pytest.mark.parametrize("quantity,approved", [("500", True), ("501", False)])
def test_home_order_value_cap_boundary(
    side: str, quantity: str, approved: bool
) -> None:
    intent = _intent(side).model_copy(update={"quantity": D(quantity)})
    result = gate().evaluate(
        intent,
        estimated_price=D("100"),
        account_context=context(current_total_exposure=D(0)),
    )
    assert result.approved is approved
    assert ("max_order_value" in result.risk_tags) is (not approved)


def test_missing_held_conversion_never_defaults_to_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = held_source(monkeypatch)
    p = price("USD_JPY", age=0, tradeable=True)
    p.conversion_factor = None
    monkeypatch.setattr(sources, "_prices_by_symbol", lambda: {"USD_JPY": p})
    result = sources.account_exposure_context(now=NOW, symbol="USD_JPY")
    assert result.exposure_errors == {"USD_JPY": "missing_position_conversion"}
    assert not result.exposure_complete
    assert "USD_JPY" not in result.quote_position_to_home


def test_production_defaults_require_home_exposure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    from alphabrief_cli.cycle_commands import _risk_gate

    monkeypatch.setenv("ALPHABRIEF_HOME", str(tmp_path))
    assert _risk_gate(("EUR_USD",), nav=D("1000")).limits.require_home_currency_exposure


@pytest.mark.parametrize("bad_price", [D(0), D("-1"), D("NaN"), D("Infinity"), None])
def test_invalid_price_cannot_support_home_notional(bad_price: Decimal | None) -> None:
    result = gate().evaluate(
        _intent("sell"), estimated_price=bad_price, account_context=context()
    )
    assert not result.approved and "EXPOSURE" in result.risk_tags
