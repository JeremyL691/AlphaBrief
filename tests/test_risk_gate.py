from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alphabrief_core import OrderIntent
from alphabrief_risk import (
    RISK_TAG_HUMAN_REVIEW,
    RISK_TAG_MACRO_HIGH_RISK,
    RISK_TAG_NEGATIVE_NEWS,
    RISK_TAG_POSITION_REDUCTION,
    AccountExposureContext,
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


def test_empty_strategy_allowlist_denies_all_strategy_orders() -> None:
    gate = RiskGate(
        limits=RiskLimitConfig(enabled_strategies=frozenset()),
        clock=lambda: NOW,
        decision_id_factory=lambda: "risk_1",
    )

    decision = gate.evaluate(_intent(), strategy_id="ema_trend_v1")

    assert decision.approved is False
    assert "ema_trend_v1" in decision.reason
    assert "strategy_disabled" in decision.risk_tags


def test_unconfigured_strategy_allowlist_preserves_legacy_behavior() -> None:
    gate = RiskGate(
        limits=RiskLimitConfig(enabled_strategies=None),
        clock=lambda: NOW,
        decision_id_factory=lambda: "risk_1",
    )

    decision = gate.evaluate(_intent(), strategy_id="ema_trend_v1")

    assert decision.approved is True


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


# ---------------------------------------------------------------------------
# Phase 19 R19.1 — account-level total-exposure enforcement
# ---------------------------------------------------------------------------


def _exposure_gate(
    *,
    max_total_exposure: Decimal,
    max_order_quantity: Decimal = Decimal("10"),
    max_order_value: Decimal = Decimal("100"),
) -> RiskGate:
    limits = RiskLimitConfig(
        trading_enabled=True,
        live_trading_enabled=False,
        symbol_allowlist=frozenset({"BTC-USD"}),
        enabled_strategies=frozenset({"sma_v1"}),
        max_order_quantity=max_order_quantity,
        max_order_value=max_order_value,
        max_total_exposure=max_total_exposure,
    )
    return RiskGate(
        limits=limits,
        clock=lambda: NOW,
        decision_id_factory=lambda: "risk_1",
    )


def _account_context(
    *,
    current_total_exposure: Decimal,
    cash: Decimal = Decimal("1000"),
) -> AccountExposureContext:
    return AccountExposureContext(
        current_total_exposure=current_total_exposure,
        exposure_by_symbol={"BTC-USD": current_total_exposure},
        cash=cash,
        account_id="acct_1",
        captured_at=NOW,
    )


def test_account_exposure_buy_under_cap_is_approved() -> None:
    gate = _exposure_gate(max_total_exposure=Decimal("300"))
    decision = gate.evaluate(
        _intent(quantity=Decimal("1")),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
        account_context=_account_context(current_total_exposure=Decimal("150")),
    )
    assert decision.approved is True
    assert "max_total_exposure" not in decision.risk_tags


def test_account_exposure_buy_exactly_at_cap_is_approved() -> None:
    # Existing 200 + new 100 == cap 300 -> on the cap, approved.
    gate = _exposure_gate(max_total_exposure=Decimal("300"))
    decision = gate.evaluate(
        _intent(quantity=Decimal("1")),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
        account_context=_account_context(current_total_exposure=Decimal("200")),
    )
    assert decision.approved is True
    assert "max_total_exposure" not in decision.risk_tags


def test_account_exposure_buy_one_cent_over_cap_is_rejected() -> None:
    # Existing 200.01 + new 100 = 300.01 > cap 300 -> rejected.
    gate = _exposure_gate(max_total_exposure=Decimal("300"))
    decision = gate.evaluate(
        _intent(quantity=Decimal("1")),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
        account_context=_account_context(current_total_exposure=Decimal("200.01")),
    )
    assert decision.approved is False
    assert "max_total_exposure" in decision.risk_tags
    assert "max_total_exposure" in decision.reason


def test_account_exposure_sell_over_cap_is_not_rejected_on_exposure() -> None:
    # Sells never increase gross exposure, so even at/over the cap a sell
    # is not rejected on account-exposure grounds (other checks still apply).
    gate = _exposure_gate(max_total_exposure=Decimal("300"))
    decision = gate.evaluate(
        _intent(side="sell", quantity=Decimal("1")),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
        account_context=_account_context(current_total_exposure=Decimal("500")),
    )
    assert "max_total_exposure" not in decision.risk_tags


def test_account_exposure_fail_closed_when_context_missing() -> None:
    gate = _exposure_gate(max_total_exposure=Decimal("300"))
    decision = gate.evaluate(
        _intent(quantity=Decimal("1")),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
        account_context=None,
    )
    assert decision.approved is False
    assert "account_context_required" in decision.risk_tags
    assert "account context" in decision.reason


def test_account_exposure_noop_when_cap_unset() -> None:
    # Legacy behavior: no max_total_exposure configured -> the account
    # context (even None) is irrelevant, decision is byte-for-byte the
    # per-order-only path.
    limits = RiskLimitConfig(
        trading_enabled=True,
        symbol_allowlist=frozenset({"BTC-USD"}),
        enabled_strategies=frozenset({"sma_v1"}),
        max_order_quantity=Decimal("2"),
        max_order_value=Decimal("1000"),
        # max_total_exposure unset (None) -> legacy
    )
    gate = RiskGate(
        limits=limits, clock=lambda: NOW, decision_id_factory=lambda: "risk_1"
    )
    decision = gate.evaluate(
        _intent(quantity=Decimal("1")),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
        account_context=None,
    )
    assert decision.approved is True
    assert "account_context_required" not in decision.risk_tags
    assert "max_total_exposure" not in decision.risk_tags


def test_account_exposure_clamp_reduces_max_quantity_to_headroom() -> None:
    # Existing 250 + new 100 = 350 > cap 300. Headroom = 50, price 100 ->
    # clamp = 0.5. The decision rejects the order (it is over cap) but
    # surfaces the clamped max_quantity so a resubmit at 0.5 lands on cap.
    gate = _exposure_gate(max_total_exposure=Decimal("300"))
    decision = gate.evaluate(
        _intent(quantity=Decimal("1")),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
        account_context=_account_context(current_total_exposure=Decimal("250")),
    )
    assert decision.approved is False
    assert decision.max_quantity == Decimal("0.5")


def test_account_exposure_clamp_never_exceeds_max_order_quantity() -> None:
    # Headroom/price = 80, but max_order_quantity = 10. The clamp only
    # tightens; it must not raise max_quantity above the configured cap.
    gate = _exposure_gate(
        max_total_exposure=Decimal("1000"),
        max_order_quantity=Decimal("10"),
    )
    decision = gate.evaluate(
        _intent(quantity=Decimal("20")),  # over per-order qty cap too
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
        account_context=_account_context(current_total_exposure=Decimal("0")),
    )
    # Rejected (over per-order qty). max_quantity stays at the configured 10,
    # never inflated toward the 10-headroom/100-price = 0.1 clamp... here
    # headroom=1000 so clamp=10, equal to max_order_quantity; assert it does
    # not exceed the configured cap in any case.
    assert decision.max_quantity is not None
    assert decision.max_quantity <= Decimal("10")


def test_account_exposure_clamp_stacks_with_risk_context_multiplier() -> None:
    # Both the account clamp and a risk_context multiplier can apply; the
    # stricter (smaller) bound wins, and max_quantity never exceeds the
    # configured per-order limit.
    gate = _exposure_gate(
        max_total_exposure=Decimal("300"),
        max_order_quantity=Decimal("2"),
    )
    ctx = _account_context(current_total_exposure=Decimal("250"))  # headroom 50
    risk_ctx = RiskContextDecision(
        decision_id="rctx_low",
        suggested_max_position_multiplier=0.4,
    )
    decision = gate.evaluate(
        _intent(quantity=Decimal("2")),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
        account_context=ctx,
        risk_context=risk_ctx,
    )
    assert decision.approved is False
    # multiplier path: 2 * 0.4 = 0.8 ; account clamp: 50/100 = 0.5.
    # The smaller (0.5) must win.
    assert decision.max_quantity == Decimal("0.5")


def test_account_exposure_missing_price_rejected() -> None:
    gate = _exposure_gate(max_total_exposure=Decimal("300"))
    decision = gate.evaluate(
        _intent(quantity=Decimal("1")),
        strategy_id="sma_v1",
        estimated_price=None,
        account_context=_account_context(current_total_exposure=Decimal("150")),
    )
    assert decision.approved is False
    assert "missing_price" in decision.risk_tags


def test_account_exposure_zero_headroom_rejects_without_clamp() -> None:
    # Already at the cap; a buy has no headroom, so it is rejected and no
    # clamp is offered (None stays the configured max_order_quantity).
    gate = _exposure_gate(
        max_total_exposure=Decimal("300"),
        max_order_quantity=Decimal("2"),
    )
    decision = gate.evaluate(
        _intent(quantity=Decimal("1")),
        strategy_id="sma_v1",
        estimated_price=Decimal("100"),
        account_context=_account_context(current_total_exposure=Decimal("300")),
    )
    assert decision.approved is False
    assert "max_total_exposure" in decision.risk_tags
    # No headroom -> no clamp -> max_quantity stays at the configured limit.
    assert decision.max_quantity == Decimal("2")


def test_risk_limit_config_rejects_total_exposure_below_order_value() -> None:
    with pytest.raises(ValueError, match="max_total_exposure"):
        RiskLimitConfig(
            max_order_value=Decimal("100"),
            max_total_exposure=Decimal("50"),
        )


def test_risk_limit_config_rejects_non_positive_total_exposure() -> None:
    with pytest.raises(ValueError, match="max_total_exposure must be positive"):
        RiskLimitConfig(max_total_exposure=Decimal("0"))
