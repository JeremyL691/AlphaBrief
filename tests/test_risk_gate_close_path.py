"""Gate-level tests for the reduced close path (PROJECT_GUIDE 5.7).

A reduce-only close remains available under the kill switch and requires
rule 3 (a fresh, tradeable quote). Everything that guards new exposure —
trading mode, the freeze, the allowlist, the daily caps, the weekend
window, exposure and order-value limits — must not stop a position from
being closed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from alphabrief_core import OrderIntent
from alphabrief_risk import KillSwitch, RiskGate, RiskLimitConfig
from alphabrief_risk.account_context import AccountExposureContext
from alphabrief_risk.entry_rules import EntryRulePolicy

NOW = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)  # Saturday: close-only window


def _close_intent(**overrides: object) -> OrderIntent:
    payload: dict[str, object] = {
        "intent_id": "ai_close",
        "source": "manual",
        "symbol": "EUR_USD",
        "side": "sell",
        "order_type": "market",
        "quantity": Decimal("1000"),
        "reduce_only": True,
        "rationale": "close",
        "created_at": NOW,
    }
    payload.update(overrides)
    return OrderIntent.model_validate(payload)


def _context(
    *, quote_age_seconds: int = 1, tradeable: bool = True
) -> AccountExposureContext:
    return AccountExposureContext(
        current_total_exposure=Decimal("999999"),
        exposure_by_symbol={"EUR_USD": Decimal("999999")},
        cash=Decimal("100000"),
        account_id="acct-1",
        captured_at=NOW,
        equity=Decimal("100000"),
        open_position_count=9,
        daily_open_count=9,
        daily_symbol_open_count=9,
        quote_captured_at=NOW - timedelta(seconds=quote_age_seconds),
        quote_tradeable=tradeable,
        frozen_symbols={"EUR_USD": "3 losing closes in a row"},
    )


def _hostile_gate(*, kill_switch: KillSwitch | None = None) -> RiskGate:
    """A gate configured to reject every entry rule there is."""
    return RiskGate(
        limits=RiskLimitConfig(            trading_enabled=False,
            symbol_allowlist=frozenset({"GBP_USD"}),
            max_order_quantity=Decimal("1"),
            max_order_value=Decimal("1"),
            max_total_exposure=Decimal("1"),
            max_symbol_exposure=Decimal("1"),
            max_leverage=Decimal("0.01"),
            max_signal_age_seconds=1,
            duplicate_order_window_seconds=60,
            max_daily_loss_pct=Decimal("0.0001"),
            max_drawdown_floor_pct=Decimal("0.0001"),
            entry_rules=EntryRulePolicy(
                max_quote_age_seconds=15,
                require_quote_tradeable=True,
                max_daily_opens=0,
                max_daily_symbol_opens=0,
                max_open_positions=0,
                require_protective_orders=True,
                block_weekend_and_late_friday=True,
            ),
        ),
        kill_switch=kill_switch or KillSwitch(),
        clock=lambda: NOW,
    )


class TestCloseOnlyChecksKillSwitchAndQuote:
    def test_every_entry_guard_is_bypassed(self) -> None:
        decision = _hostile_gate().evaluate(
            _close_intent(),
            estimated_price=Decimal("1.1000"),
            estimated_quantity=Decimal("1000"),
            data_quality_passed=False,
            account_context=_context(),
        )

        assert decision.approved is True
        assert "approved" in decision.risk_tags
        for tag in (
            "trading_disabled",
            "data_quality",
            "symbol_not_allowed",
            "max_quantity",
            "max_order_value",
            "max_total_exposure",
            "max_symbol_exposure",
            "LOSS_STREAK",
            "MAX_POSITIONS",
            "DAILY_INTENT_CAP",
            "WEEKEND",
            "ORDER_INVALID",
        ):
            assert tag not in decision.risk_tags

    def test_kill_switch_allows_verified_reduction(self) -> None:
        gate = _hostile_gate(
            kill_switch=KillSwitch(active=True, reason="manual halt")
        )

        decision = gate.evaluate(
            _close_intent(),
            estimated_price=Decimal("1.1000"),
            estimated_quantity=Decimal("1000"),
            account_context=_context(),
        )

        assert decision.approved is True
        assert "kill_switch_reduce_only" in decision.risk_tags

    def test_a_stale_quote_blocks(self) -> None:
        decision = _hostile_gate().evaluate(
            _close_intent(),
            estimated_price=Decimal("1.1000"),
            estimated_quantity=Decimal("1000"),
            account_context=_context(quote_age_seconds=60),
        )

        assert decision.approved is False
        assert "QUOTE_STALE" in decision.risk_tags

    def test_a_non_tradeable_instrument_blocks(self) -> None:
        decision = _hostile_gate().evaluate(
            _close_intent(),
            estimated_price=Decimal("1.1000"),
            estimated_quantity=Decimal("1000"),
            account_context=_context(tradeable=False),
        )

        assert decision.approved is False
        assert "NOT_TRADEABLE" in decision.risk_tags

    def test_no_quote_at_all_fails_closed(self) -> None:
        decision = _hostile_gate().evaluate(
            _close_intent(),
            estimated_price=Decimal("1.1000"),
            estimated_quantity=Decimal("1000"),
        )

        assert decision.approved is False
        assert "QUOTE_STALE" in decision.risk_tags

    def test_a_flat_target_intent_takes_the_same_path(self) -> None:
        decision = _hostile_gate().evaluate(
            _close_intent(
                quantity=None,
                target_position_pct=Decimal("0"),
                reduce_only=False,
            ),
            estimated_price=Decimal("1.1000"),
            account_context=_context(),
        )

        assert decision.approved is True

    def test_an_entry_intent_still_hits_every_guard(self) -> None:
        decision = _hostile_gate().evaluate(
            _close_intent(
                reduce_only=False,
                side="buy",
                stop_loss=Decimal("1.0900"),
                take_profit=Decimal("1.1200"),
            ),
            estimated_price=Decimal("1.1000"),
            estimated_quantity=Decimal("1000"),
            data_quality_passed=False,
            account_context=_context(),
        )

        assert decision.approved is False
        assert "trading_disabled" in decision.risk_tags
        assert "data_quality" in decision.risk_tags
