"""Pass/reject tests for the entry rules (PROJECT_GUIDE 5.7 rules 3, 7, 8, 12, 13, 14).

Every rule has at least one passing case and one rejecting case, and the
closing exemption is pinned: a reduce-only intent is never blocked by an
entry rule other than rule 3, which still requires a fresh, tradeable quote.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from alphabrief_core import OrderIntent
from alphabrief_risk.account_context import AccountExposureContext
from alphabrief_risk.entry_rules import (
    EntryRulePolicy,
    evaluate_entry_rules,
    rejection_codes,
)

#: Wednesday 12:00 UTC: inside the week and before the Friday cutoff.
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _intent(**overrides: object) -> OrderIntent:
    payload: dict[str, object] = {
        "intent_id": "intent_1",
        "source": "model",
        "symbol": "EUR_USD",
        "side": "buy",
        "order_type": "market",
        "quantity": Decimal("1000"),
        "stop_loss": Decimal("1.1200"),
        "take_profit": Decimal("1.1500"),
        "rationale": "entry rule test",
        "created_at": NOW,
    }
    payload.update(overrides)
    return OrderIntent.model_validate(payload)


def _context(**overrides: object) -> AccountExposureContext:
    payload: dict[str, object] = {
        "current_total_exposure": Decimal("0"),
        "cash": Decimal("100000"),
        "account_id": "acct-1",
        "captured_at": NOW,
        "open_position_count": 0,
        "daily_open_count": 0,
        "daily_symbol_open_count": 0,
        "quote_captured_at": NOW,
        "quote_tradeable": True,
    }
    payload.update(overrides)
    return AccountExposureContext.model_validate(payload)


def _codes(
    intent: OrderIntent,
    policy: EntryRulePolicy,
    *,
    context: AccountExposureContext | None = None,
    now: datetime = NOW,
) -> tuple[str, ...]:
    return rejection_codes(
        evaluate_entry_rules(
            intent, policy=policy, now=now, account_context=context
        )
    )


class TestRule3Quote:
    policy = EntryRulePolicy(
        max_quote_age_seconds=15, require_quote_tradeable=True
    )

    def test_fresh_tradeable_quote_passes(self) -> None:
        assert _codes(_intent(), self.policy, context=_context()) == ()

    def test_stale_quote_is_rejected(self) -> None:
        context = _context(quote_captured_at=NOW - timedelta(seconds=16))

        assert _codes(_intent(), self.policy, context=context) == ("QUOTE_STALE",)

    def test_missing_quote_timestamp_is_rejected(self) -> None:
        context = _context(quote_captured_at=None)

        assert _codes(_intent(), self.policy, context=context) == ("QUOTE_STALE",)

    def test_untradeable_instrument_is_rejected(self) -> None:
        assert _codes(
            _intent(), self.policy, context=_context(quote_tradeable=False)
        ) == ("NOT_TRADEABLE",)


class TestRule7DailyCaps:
    policy = EntryRulePolicy(max_daily_opens=5, max_daily_symbol_opens=1)

    def test_under_the_caps_passes(self) -> None:
        assert _codes(_intent(), self.policy, context=_context()) == ()

    def test_daily_cap_reached_is_rejected(self) -> None:
        assert _codes(
            _intent(), self.policy, context=_context(daily_open_count=5)
        ) == ("DAILY_INTENT_CAP",)

    def test_symbol_cap_reached_is_rejected(self) -> None:
        assert _codes(
            _intent(), self.policy, context=_context(daily_symbol_open_count=1)
        ) == ("DAILY_INTENT_CAP",)

    def test_unknown_counts_fail_closed(self) -> None:
        assert _codes(
            _intent(), self.policy, context=_context(daily_open_count=None)
        ) == ("DAILY_INTENT_CAP",)


class TestRule8MaxPositions:
    policy = EntryRulePolicy(max_open_positions=3)

    def test_below_the_limit_passes(self) -> None:
        assert _codes(
            _intent(), self.policy, context=_context(open_position_count=2)
        ) == ()

    def test_at_the_limit_is_rejected(self) -> None:
        assert _codes(
            _intent(), self.policy, context=_context(open_position_count=3)
        ) == ("MAX_POSITIONS",)

    def test_existing_position_may_be_added_to_at_the_limit(self) -> None:
        context = _context(
            open_position_count=3,
            exposure_by_symbol={"EUR_USD": Decimal("1100")},
        )

        assert _codes(_intent(), self.policy, context=context) == ()

    def test_unknown_position_count_fails_closed(self) -> None:
        assert _codes(
            _intent(), self.policy, context=_context(open_position_count=None)
        ) == ("MAX_POSITIONS",)


class TestRule12LossStreak:
    policy = EntryRulePolicy()

    def test_unfrozen_symbol_passes(self) -> None:
        assert _codes(_intent(), self.policy, context=_context()) == ()

    def test_frozen_symbol_is_rejected(self) -> None:
        context = _context(frozen_symbols={"EUR_USD": "3 losing closes"})

        assert _codes(_intent(), self.policy, context=context) == ("LOSS_STREAK",)


class TestRule13Weekend:
    policy = EntryRulePolicy(block_weekend_and_late_friday=True)

    def test_wednesday_passes(self) -> None:
        assert _codes(_intent(), self.policy) == ()

    def test_friday_before_the_cutoff_passes(self) -> None:
        friday = datetime(2026, 10, 2, 12, 59, tzinfo=UTC)

        assert _codes(_intent(), self.policy, now=friday) == ()

    def test_friday_after_the_cutoff_is_rejected(self) -> None:
        friday = datetime(2026, 10, 2, 13, 0, tzinfo=UTC)

        assert _codes(_intent(), self.policy, now=friday) == ("WEEKEND",)

    def test_saturday_is_rejected(self) -> None:
        saturday = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)

        assert _codes(_intent(), self.policy, now=saturday) == ("WEEKEND",)


class TestRule14OrderValidity:
    policy = EntryRulePolicy(require_protective_orders=True)

    def test_complete_order_passes(self) -> None:
        assert _codes(_intent(), self.policy) == ()

    def test_missing_stop_loss_is_rejected(self) -> None:
        assert _codes(_intent(stop_loss=None), self.policy) == ("ORDER_INVALID",)

    def test_missing_take_profit_is_rejected(self) -> None:
        assert _codes(_intent(take_profit=None), self.policy) == ("ORDER_INVALID",)

    def test_fractional_units_are_rejected(self) -> None:
        assert _codes(_intent(quantity=Decimal("10.5")), self.policy) == (
            "ORDER_INVALID",
        )

    def test_long_with_inverted_protection_is_rejected(self) -> None:
        assert _codes(
            _intent(stop_loss=Decimal("1.1600"), take_profit=Decimal("1.1500")),
            self.policy,
        ) == ("ORDER_INVALID",)

    def test_short_with_inverted_protection_is_rejected(self) -> None:
        assert _codes(
            _intent(
                side="sell",
                stop_loss=Decimal("1.1200"),
                take_profit=Decimal("1.1500"),
            ),
            self.policy,
        ) == ("ORDER_INVALID",)


class TestClosesAreExemptExceptForTheQuote:
    """PROJECT_GUIDE 5.7: a close checks only the kill switch and rule 3."""

    policy = EntryRulePolicy(
        max_quote_age_seconds=15,
        require_quote_tradeable=True,
        max_daily_opens=0,
        max_daily_symbol_opens=0,
        max_open_positions=0,
        require_protective_orders=True,
        block_weekend_and_late_friday=True,
    )

    def test_reduce_only_close_ignores_every_rule_but_the_quote(self) -> None:
        close = _intent(
            reduce_only=True,
            side="sell",
            stop_loss=None,
            take_profit=None,
        )
        friday_evening = datetime(2026, 10, 2, 20, 0, tzinfo=UTC)
        # Every entry-rule input is hostile: the caps are spent, the
        # position limit is reached and the symbol is frozen. None of it
        # may block a close that is priced from a fresh quote.
        hostile = _context(
            open_position_count=9,
            daily_open_count=9,
            daily_symbol_open_count=9,
            frozen_symbols={"EUR_USD": "3 losing closes in a row"},
            quote_captured_at=friday_evening,
        )

        assert _codes(
            close, self.policy, context=hostile, now=friday_evening
        ) == ()

    def test_flat_target_close_ignores_every_rule_but_the_quote(self) -> None:
        close = _intent(
            target_position_pct=Decimal("0"),
            quantity=None,
            stop_loss=None,
            take_profit=None,
        )

        assert _codes(close, self.policy, context=_context()) == ()

    def test_close_still_needs_a_fresh_tradeable_quote(self) -> None:
        close = _intent(
            reduce_only=True,
            side="sell",
            stop_loss=None,
            take_profit=None,
        )

        # No quote at all: fail closed rather than submit at an unknown price.
        assert _codes(close, self.policy, context=None) == (
            "QUOTE_STALE",
            "NOT_TRADEABLE",
        )
        # A stale quote is refused; a non-tradeable instrument too.
        assert _codes(
            close,
            self.policy,
            context=_context(quote_captured_at=NOW - timedelta(seconds=60)),
        ) == ("QUOTE_STALE",)
        assert _codes(
            close, self.policy, context=_context(quote_tradeable=False)
        ) == ("NOT_TRADEABLE",)


class TestGateIntegration:
    def test_configured_policy_rejects_through_the_gate(self) -> None:
        from alphabrief_risk import RiskGate, RiskLimitConfig

        gate = RiskGate(
            limits=RiskLimitConfig(
                trading_enabled=True,
                symbol_allowlist=frozenset({"EUR_USD"}),
                entry_rules=EntryRulePolicy(require_protective_orders=True),
            ),
            clock=lambda: NOW,
        )

        decision = gate.evaluate(
            _intent(stop_loss=None), estimated_price=Decimal("1.13")
        )

        assert decision.approved is False
        assert "ORDER_INVALID" in decision.risk_tags

    def test_configured_policy_allows_a_complete_order(self) -> None:
        from alphabrief_risk import RiskGate, RiskLimitConfig

        gate = RiskGate(
            limits=RiskLimitConfig(
                trading_enabled=True,
                symbol_allowlist=frozenset({"EUR_USD"}),
                entry_rules=EntryRulePolicy(require_protective_orders=True),
            ),
            clock=lambda: NOW,
        )

        decision = gate.evaluate(_intent(), estimated_price=Decimal("1.13"))

        assert decision.approved is True

    def test_absent_policy_keeps_legacy_behavior(self) -> None:
        from alphabrief_risk import RiskGate, RiskLimitConfig

        gate = RiskGate(
            limits=RiskLimitConfig(
                trading_enabled=True,
                symbol_allowlist=frozenset({"EUR_USD"}),
            ),
            clock=lambda: NOW,
        )

        decision = gate.evaluate(
            _intent(stop_loss=None), estimated_price=Decimal("1.13")
        )

        assert decision.approved is True
