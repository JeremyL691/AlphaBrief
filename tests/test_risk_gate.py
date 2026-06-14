from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alphabrief_core import OrderIntent
from alphabrief_risk import KillSwitch, RiskGate, RiskLimitConfig

NOW = datetime(2026, 6, 14, 10, 0, tzinfo=UTC)


def _intent(**overrides: object) -> OrderIntent:
    payload: dict[str, object] = {
        "intent_id": "intent_1",
        "source": "strategy",
        "symbol": "BTC-USD",
        "side": "buy",
        "order_type": "market",
        "quantity": Decimal("1"),
        "rationale": "test order",
        "created_at": NOW,
    }
    payload.update(overrides)
    return OrderIntent.model_validate(payload)


def _gate(
    *,
    trading_enabled: bool = True,
    live_trading_enabled: bool = False,
) -> RiskGate:
    limits = RiskLimitConfig(
        trading_enabled=trading_enabled,
        live_trading_enabled=live_trading_enabled,
        symbol_allowlist=frozenset({"BTC-USD"}),
        enabled_strategies=frozenset({"sma_v1"}),
        max_order_quantity=Decimal("2"),
        max_order_value=Decimal("1000"),
    )
    return RiskGate(
        limits=limits,
        clock=lambda: NOW,
        decision_id_factory=lambda: "risk_1",
    )


def test_risk_gate_approves_valid_order_intent() -> None:
    decision = _gate().evaluate(
        _intent(),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
        data_quality_passed=True,
    )

    assert decision.decision_id == "risk_1"
    assert decision.intent_id == "intent_1"
    assert decision.approved is True
    assert decision.reason == "approved"
    assert "approved" in decision.risk_tags
    assert decision.max_quantity == Decimal("2")


def test_risk_gate_rejects_when_trading_disabled() -> None:
    decision = _gate(trading_enabled=False).evaluate(
        _intent(),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
    )

    assert decision.approved is False
    assert "trading disabled" in decision.reason
    assert "trading_disabled" in decision.risk_tags


def test_risk_gate_rejects_live_trading_enabled() -> None:
    decision = _gate(live_trading_enabled=True).evaluate(
        _intent(),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
    )

    assert decision.approved is False
    assert "live trading" in decision.reason
    assert "live_trading_locked" in decision.risk_tags


def test_risk_gate_rejects_kill_switch() -> None:
    kill_switch = KillSwitch()
    kill_switch.activate("manual halt")
    gate = RiskGate(
        limits=RiskLimitConfig(symbol_allowlist=frozenset({"BTC-USD"})),
        kill_switch=kill_switch,
        clock=lambda: NOW,
        decision_id_factory=lambda: "risk_1",
    )

    decision = gate.evaluate(_intent(), estimated_price=Decimal("100"))

    assert decision.approved is False
    assert "manual halt" in decision.reason
    assert "kill_switch" in decision.risk_tags


def test_risk_gate_rejects_symbol_strategy_and_data_quality_failures() -> None:
    decision = _gate().evaluate(
        _intent(symbol="ETH-USD"),
        strategy_id="disabled",
        estimated_price=Decimal("100"),
        data_quality_passed=False,
    )

    assert decision.approved is False
    assert "symbol ETH-USD is not allowed" in decision.reason
    assert "strategy disabled" in decision.reason
    assert "data quality" in decision.reason


def test_risk_gate_rejects_quantity_and_order_value_limits() -> None:
    decision = _gate().evaluate(
        _intent(quantity=Decimal("3")),
        strategy_id="sma_v1",
        estimated_price=Decimal("400"),
    )

    assert decision.approved is False
    assert "quantity" in decision.reason
    assert "order value" in decision.reason


def test_risk_gate_requires_price_for_order_value_limit() -> None:
    decision = _gate().evaluate(_intent(), strategy_id="sma_v1")

    assert decision.approved is False
    assert "estimated_price" in decision.reason


def test_kill_switch_requires_reason_and_can_deactivate() -> None:
    kill_switch = KillSwitch()

    with pytest.raises(ValueError, match="reason"):
        kill_switch.activate(" ")

    kill_switch.activate("stop all")
    assert kill_switch.active is True
    kill_switch.deactivate()
    assert kill_switch.active is False


def test_risk_gate_rejects_target_pct_when_limits_require_estimated_quantity() -> None:
    gate = RiskGate(
        limits=RiskLimitConfig(
            symbol_allowlist=frozenset({"BTC-USD"}),
            max_order_quantity=Decimal("2"),
            max_order_value=Decimal("1000"),
        ),
        clock=lambda: NOW,
        decision_id_factory=lambda: "risk_1",
    )
    intent = _intent(quantity=None, target_position_pct=Decimal("0.5"))

    decision = gate.evaluate(intent, estimated_price=Decimal("100"))

    assert decision.approved is False
    assert "estimated_quantity" in decision.reason


def test_risk_gate_checks_target_pct_quantity_and_value_with_estimates() -> None:
    gate = RiskGate(
        limits=RiskLimitConfig(
            symbol_allowlist=frozenset({"BTC-USD"}),
            max_order_quantity=Decimal("2"),
            max_order_value=Decimal("1000"),
        ),
        clock=lambda: NOW,
        decision_id_factory=lambda: "risk_1",
    )
    intent = _intent(quantity=None, target_position_pct=Decimal("0.5"))

    decision = gate.evaluate(
        intent,
        estimated_price=Decimal("100"),
        estimated_quantity=Decimal("3"),
    )

    assert decision.approved is False
    assert "quantity" in decision.reason


def test_risk_gate_approves_target_pct_within_limits() -> None:
    gate = RiskGate(
        limits=RiskLimitConfig(
            symbol_allowlist=frozenset({"BTC-USD"}),
            max_order_quantity=Decimal("2"),
            max_order_value=Decimal("1000"),
        ),
        clock=lambda: NOW,
        decision_id_factory=lambda: "risk_1",
    )
    intent = _intent(quantity=None, target_position_pct=Decimal("0.5"))

    decision = gate.evaluate(
        intent,
        estimated_price=Decimal("100"),
        estimated_quantity=Decimal("1"),
    )

    assert decision.approved is True


def test_risk_gate_target_pct_skips_limits_when_none_configured() -> None:
    gate = RiskGate(
        limits=RiskLimitConfig(symbol_allowlist=frozenset({"BTC-USD"})),
        clock=lambda: NOW,
        decision_id_factory=lambda: "risk_1",
    )
    intent = _intent(quantity=None, target_position_pct=Decimal("0.5"))

    decision = gate.evaluate(intent)

    assert decision.approved is True
