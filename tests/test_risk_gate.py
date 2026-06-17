from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alphabrief_core import OrderIntent
from alphabrief_risk import (
    RISK_TAG_HUMAN_REVIEW,
    RISK_TAG_MACRO_HIGH_RISK,
    RISK_TAG_NEGATIVE_NEWS,
    RISK_TAG_POSITION_REDUCTION,
    KillSwitch,
    RiskContextDecision,
    RiskGate,
    RiskLimitConfig,
)

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


def _empty_context(decision_id: str = "rctx_empty") -> RiskContextDecision:
    return RiskContextDecision(decision_id=decision_id)


def test_risk_gate_no_context_matches_default_behavior() -> None:
    baseline = _gate().evaluate(
        _intent(),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
    )

    explicit_none = _gate().evaluate(
        _intent(),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
        risk_context=None,
    )

    empty = _gate().evaluate(
        _intent(),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
        risk_context=_empty_context(),
    )

    assert explicit_none.approved == baseline.approved
    assert explicit_none.max_quantity == baseline.max_quantity
    assert explicit_none.requires_human_review == baseline.requires_human_review
    assert explicit_none.risk_tags == baseline.risk_tags
    assert empty.approved == baseline.approved
    assert empty.max_quantity == baseline.max_quantity
    assert empty.requires_human_review == baseline.requires_human_review
    assert empty.risk_tags == baseline.risk_tags


def test_risk_gate_negative_context_flips_human_review() -> None:
    context = RiskContextDecision(
        decision_id="rctx_neg",
        requires_human_review=True,
        risk_tags=(RISK_TAG_NEGATIVE_NEWS, RISK_TAG_HUMAN_REVIEW),
    )

    decision = _gate().evaluate(
        _intent(),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
        risk_context=context,
    )

    assert decision.approved is True
    assert decision.requires_human_review is True
    assert RISK_TAG_NEGATIVE_NEWS in decision.risk_tags
    assert RISK_TAG_HUMAN_REVIEW in decision.risk_tags
    assert "approved" in decision.risk_tags
    assert decision.max_quantity == Decimal("2")


def test_risk_gate_macro_high_risk_reduces_max_quantity() -> None:
    context = RiskContextDecision(
        decision_id="rctx_macro",
        risk_tags=(RISK_TAG_MACRO_HIGH_RISK, RISK_TAG_POSITION_REDUCTION),
        suggested_max_position_multiplier=0.5,
    )

    decision = _gate().evaluate(
        _intent(),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
        risk_context=context,
    )

    assert decision.approved is True
    assert decision.requires_human_review is False
    assert RISK_TAG_MACRO_HIGH_RISK in decision.risk_tags
    assert RISK_TAG_POSITION_REDUCTION in decision.risk_tags
    assert decision.max_quantity == Decimal("1")


def test_risk_gate_combined_context_applies_both_effects() -> None:
    context = RiskContextDecision(
        decision_id="rctx_both",
        requires_human_review=True,
        risk_tags=(
            RISK_TAG_NEGATIVE_NEWS,
            RISK_TAG_HUMAN_REVIEW,
            RISK_TAG_MACRO_HIGH_RISK,
            RISK_TAG_POSITION_REDUCTION,
        ),
        suggested_max_position_multiplier=0.5,
    )

    decision = _gate().evaluate(
        _intent(),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
        risk_context=context,
    )

    assert decision.approved is True
    assert decision.requires_human_review is True
    assert RISK_TAG_NEGATIVE_NEWS in decision.risk_tags
    assert RISK_TAG_MACRO_HIGH_RISK in decision.risk_tags
    assert decision.max_quantity == Decimal("1")


def test_risk_gate_context_cannot_reapprove_rejected_intent() -> None:
    context = RiskContextDecision(
        decision_id="rctx_neg",
        requires_human_review=True,
        risk_tags=(RISK_TAG_NEGATIVE_NEWS, RISK_TAG_HUMAN_REVIEW),
    )

    decision = _gate().evaluate(
        _intent(symbol="ETH-USD"),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
        risk_context=context,
    )

    assert decision.approved is False
    assert "ETH-USD" in decision.reason
    assert "symbol_not_allowed" in decision.risk_tags
    assert RISK_TAG_NEGATIVE_NEWS in decision.risk_tags
    assert RISK_TAG_HUMAN_REVIEW in decision.risk_tags
    assert "approved" not in decision.risk_tags


def test_risk_gate_context_with_multiplier_one_does_not_relax() -> None:
    context = RiskContextDecision(
        decision_id="rctx_one",
        suggested_max_position_multiplier=1.0,
    )

    decision = _gate().evaluate(
        _intent(),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
        risk_context=context,
    )

    assert decision.approved is True
    assert decision.max_quantity == Decimal("2")


def test_risk_gate_context_cannot_override_kill_switch() -> None:
    kill_switch = KillSwitch()
    kill_switch.activate("manual halt")
    gate = RiskGate(
        limits=RiskLimitConfig(symbol_allowlist=frozenset({"BTC-USD"})),
        kill_switch=kill_switch,
        clock=lambda: NOW,
        decision_id_factory=lambda: "risk_1",
    )
    context = RiskContextDecision(
        decision_id="rctx_neg",
        requires_human_review=True,
        risk_tags=(RISK_TAG_NEGATIVE_NEWS,),
    )

    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("100"),
        risk_context=context,
    )

    assert decision.approved is False
    assert "manual halt" in decision.reason
    assert "kill_switch" in decision.risk_tags


def test_risk_gate_context_cannot_override_live_trading_lock() -> None:
    context = RiskContextDecision(
        decision_id="rctx_neg",
        requires_human_review=True,
        risk_tags=(RISK_TAG_NEGATIVE_NEWS, RISK_TAG_HUMAN_REVIEW),
    )

    decision = _gate(live_trading_enabled=True).evaluate(
        _intent(),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
        risk_context=context,
    )

    assert decision.approved is False
    assert "live trading" in decision.reason
    assert "live_trading_locked" in decision.risk_tags


def test_risk_gate_context_tags_dedup_with_existing() -> None:
    context = RiskContextDecision(
        decision_id="rctx_dup",
        requires_human_review=True,
        risk_tags=("approved", RISK_TAG_NEGATIVE_NEWS, RISK_TAG_NEGATIVE_NEWS),
    )

    decision = _gate().evaluate(
        _intent(),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
        risk_context=context,
    )

    assert decision.risk_tags.count("approved") == 1
    assert decision.risk_tags.count(RISK_TAG_NEGATIVE_NEWS) == 1
    assert decision.requires_human_review is True


def test_risk_gate_static_human_review_and_context_combine() -> None:
    limits = RiskLimitConfig(
        symbol_allowlist=frozenset({"BTC-USD"}),
        max_order_quantity=Decimal("2"),
        require_human_review=True,
    )
    gate = RiskGate(
        limits=limits,
        clock=lambda: NOW,
        decision_id_factory=lambda: "risk_1",
    )
    context = RiskContextDecision(
        decision_id="rctx_neutral",
        requires_human_review=False,
    )

    decision = gate.evaluate(
        _intent(),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
        risk_context=context,
    )

    assert decision.approved is True
    assert decision.requires_human_review is True


def test_risk_gate_context_multiplier_below_one_only_reduces_not_relaxes() -> None:
    gate = RiskGate(
        limits=RiskLimitConfig(
            symbol_allowlist=frozenset({"BTC-USD"}),
            max_order_quantity=Decimal("1"),
        ),
        clock=lambda: NOW,
        decision_id_factory=lambda: "risk_1",
    )
    context = RiskContextDecision(
        decision_id="rctx_low",
        suggested_max_position_multiplier=0.4,
    )

    decision = gate.evaluate(
        _intent(),
        estimated_price=Decimal("100"),
        risk_context=context,
    )

    assert decision.approved is True
    max_quantity = decision.max_quantity
    assert max_quantity is not None
    assert max_quantity < Decimal("1")
    assert max_quantity >= Decimal("0")
