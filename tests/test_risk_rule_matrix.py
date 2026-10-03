"""The rule matrix: every PROJECT_GUIDE 5.7 rule has a pass and a reject case.

This module is deliberately table-driven. Each of the 14 rules declares:

* the violation that must be rejected, and the guide's rejection code;
* the baseline state that must be approved.

If a future change removes a rule's enforcement, the corresponding reject
case fails; if it starts rejecting healthy entries, the pass case fails. The
matrix also pins the rule-1 freeze and rule-2 classification halves that the
base gate checks do not cover.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alphabrief_core import OrderIntent, RiskDecision
from alphabrief_risk import KillSwitch, RiskGate, RiskLimitConfig
from alphabrief_risk.account_context import AccountExposureContext
from alphabrief_risk.entry_rules import EntryRulePolicy

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)  # Wednesday, mid-session
SYMBOL = "EUR_USD"
UNIVERSE = ("EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD")


def _intent(**overrides: object) -> OrderIntent:
    payload: dict[str, object] = {
        "intent_id": "intent_matrix",
        "source": "model",
        "symbol": SYMBOL,
        "side": "buy",
        "order_type": "market",
        "quantity": Decimal("10000"),
        "stop_loss": Decimal("1.0900"),
        "take_profit": Decimal("1.1200"),
        "rationale": "rule matrix",
        "created_at": NOW,
    }
    payload.update(overrides)
    return OrderIntent.model_validate(payload)


def _context(**overrides: object) -> AccountExposureContext:
    """A context in which every rule passes."""
    payload: dict[str, object] = {
        "current_total_exposure": Decimal("0"),
        "exposure_by_symbol": {},
        "cash": Decimal("100000"),
        "account_id": "acct-1",
        "captured_at": NOW,
        "equity": Decimal("100000"),
        "equity_high_water_mark": Decimal("100000"),
        "day_start_equity": Decimal("100000"),
        "day_realized_pnl": Decimal(0),
        "day_unrealized_pnl": Decimal(0),
        "daily_loss_captured_at": NOW,
        "daily_loss_blocked": False,
        "open_position_count": 0,
        "daily_open_count": 0,
        "daily_symbol_open_count": 0,
        "quote_captured_at": NOW,
        "quote_tradeable": True,
        "frozen_symbols": {},
        "recent_high_impact_events": {},
        "drawdown_block_reason": None,
        "current_spread": Decimal("0.0002"),
        "recent_spreads": (Decimal("0.0002"),) * 20,
        "reconciliation_state": "clean",
        "symbol_types": {symbol: "CURRENCY" for symbol in UNIVERSE},
    }
    payload.update(overrides)
    return AccountExposureContext.model_validate(payload)


def _gate(
    *,
    kill_switch: KillSwitch | None = None,
    trading_enabled: bool = True,
    limits: dict[str, object] | None = None,
) -> RiskGate:
    """A gate that enforces all 14 rules at their guide thresholds."""
    entry_rules = EntryRulePolicy(
        max_quote_age_seconds=15,
        require_quote_tradeable=True,
        max_daily_opens=5,
        max_daily_symbol_opens=1,
        max_open_positions=3,
        require_protective_orders=True,
        block_weekend_and_late_friday=True,
        event_window_minutes=30,
        block_on_drawdown=True,
        max_spread_median_multiplier=Decimal("2"),
        min_spread_samples=5,
        require_unfrozen=True,
        require_currency_type=True,
    )
    payload: dict[str, object] = {
        "trading_enabled": trading_enabled,
        "symbol_allowlist": frozenset(UNIVERSE),
        "max_order_quantity": Decimal("100000"),
        "max_order_value": Decimal("50000"),
        "max_total_exposure": Decimal("150000"),
        "max_daily_loss_pct": Decimal("0.01"),
        "max_drawdown_floor_pct": Decimal("0.05"),
        "entry_rules": entry_rules,
    }
    if limits:
        payload.update(limits)
    return RiskGate(
        limits=RiskLimitConfig(**payload),  # type: ignore[arg-type]
        kill_switch=kill_switch or KillSwitch(),
        clock=lambda: NOW,
    )


def _weekend_gate() -> RiskGate:
    """The same gate, evaluated on a Saturday (rule 13's close-only window)."""
    saturday = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
    return RiskGate(
        limits=RiskLimitConfig(
            trading_enabled=True,
            symbol_allowlist=frozenset(UNIVERSE),
            entry_rules=EntryRulePolicy(block_weekend_and_late_friday=True),
        ),
        kill_switch=KillSwitch(),
        clock=lambda: saturday,
    )


def _evaluate(
    gate: RiskGate,
    *,
    intent: OrderIntent | None = None,
    context: AccountExposureContext | None = None,
    price: Decimal | None = Decimal("1.1000"),
    data_quality_passed: bool = True,
) -> RiskDecision:
    return gate.evaluate(
        intent or _intent(),
        estimated_price=price,
        estimated_quantity=Decimal("10000"),
        data_quality_passed=data_quality_passed,
        account_context=context if context is not None else _context(),
    )


#: One row per rule: violation → expected code, and the pass case.
MATRIX = [
    pytest.param(
        "1-trading-off",
        lambda: _evaluate(_gate(trading_enabled=False)),
        "trading_disabled",
        id="rule1-trading-off",
    ),
    pytest.param(
        "1-kill-switch",
        lambda: _evaluate(
            _gate(kill_switch=KillSwitch(active=True, reason="manual halt"))
        ),
        "kill_switch",
        id="rule1-kill-switch",
    ),
    pytest.param(
        "1-frozen",
        lambda: _evaluate(_gate(), context=_context(reconciliation_state="frozen")),
        "FROZEN",
        id="rule1-frozen",
    ),
    pytest.param(
        "2-instrument-type",
        lambda: _evaluate(
            _gate(),
            context=_context(symbol_types={SYMBOL: "CFD"}),
        ),
        "INSTRUMENT_NOT_ALLOWED",
        id="rule2-instrument-type",
    ),
    pytest.param(
        "2-not-allowlisted",
        lambda: _evaluate(_gate(), intent=_intent(symbol="USD_TRY")),
        "symbol_not_allowed",
        id="rule2-not-allowlisted",
    ),
    pytest.param(
        "3-stale-quote",
        lambda: _evaluate(
            _gate(), context=_context(quote_captured_at=NOW - timedelta(minutes=5))
        ),
        "QUOTE_STALE",
        id="rule3-stale-quote",
    ),
    pytest.param(
        "3-not-tradeable",
        lambda: _evaluate(_gate(), context=_context(quote_tradeable=False)),
        "NOT_TRADEABLE",
        id="rule3-not-tradeable",
    ),
    pytest.param(
        "4-wide-spread",
        lambda: _evaluate(_gate(), context=_context(current_spread=Decimal("0.0010"))),
        "SPREAD_WIDE",
        id="rule4-wide-spread",
    ),
    pytest.param(
        "5-data-quality",
        lambda: _evaluate(_gate(), data_quality_passed=False),
        "data_quality",
        id="rule5-data-quality",
    ),
    pytest.param(
        "6-event-window",
        lambda: _evaluate(
            _gate(),
            context=_context(
                recent_high_impact_events={SYMBOL: "fomc (USD) at 12:00Z"}
            ),
        ),
        "EVENT_WINDOW",
        id="rule6-event-window",
    ),
    pytest.param(
        "7-daily-cap",
        lambda: _evaluate(_gate(), context=_context(daily_open_count=5)),
        "DAILY_INTENT_CAP",
        id="rule7-daily-cap",
    ),
    pytest.param(
        "7-daily-symbol-cap",
        lambda: _evaluate(_gate(), context=_context(daily_symbol_open_count=1)),
        "DAILY_INTENT_CAP",
        id="rule7-daily-symbol-cap",
    ),
    pytest.param(
        "8-max-positions",
        lambda: _evaluate(_gate(), context=_context(open_position_count=3)),
        "MAX_POSITIONS",
        id="rule8-max-positions",
    ),
    pytest.param(
        "9-order-value",
        lambda: _evaluate(_gate(), intent=_intent(quantity=Decimal("100000"))),
        "max_order_value",
        id="rule9-order-value",
    ),
    pytest.param(
        "9-total-exposure",
        lambda: _evaluate(
            _gate(), context=_context(current_total_exposure=Decimal("150000"))
        ),
        "max_total_exposure",
        id="rule9-total-exposure",
    ),
    pytest.param(
        "10-daily-loss",
        lambda: _evaluate(
            _gate(),
            context=_context(
                day_realized_pnl=Decimal("-2000"), equity=Decimal("98000")
            ),
        ),
        "max_daily_loss",
        id="rule10-daily-loss",
    ),
    pytest.param(
        "11-drawdown",
        lambda: _evaluate(
            _gate(),
            context=_context(drawdown_block_reason="drawdown 3.5% blocks exposure"),
        ),
        "DRAWDOWN",
        id="rule11-drawdown",
    ),
    pytest.param(
        "12-loss-streak",
        lambda: _evaluate(
            _gate(), context=_context(frozen_symbols={SYMBOL: "3 losing closes"})
        ),
        "LOSS_STREAK",
        id="rule12-loss-streak",
    ),
    pytest.param(
        "13-weekend",
        lambda: _evaluate(_weekend_gate(), context=_context()),
        "WEEKEND",
        id="rule13-weekend",
    ),
    pytest.param(
        "14-order-invalid",
        lambda: _evaluate(
            _gate(),
            intent=_intent(stop_loss=None, take_profit=None),
        ),
        "ORDER_INVALID",
        id="rule14-order-invalid",
    ),
]


class TestBaselineIsApproved:
    """The healthy entry must pass every rule at once."""

    def test_all_rules_pass_on_a_clean_context(self) -> None:
        decision = _evaluate(_gate())

        assert decision.approved is True
        assert "approved" in decision.risk_tags


class TestRejectMatrix:
    @pytest.mark.parametrize("rule,run,expected_code", MATRIX)
    def test_rule_rejects_with_its_guide_code(
        self, rule: str, run: Callable[[], RiskDecision], expected_code: str
    ) -> None:
        decision = run()

        assert decision.approved is False, f"{rule} should reject"
        assert expected_code in decision.risk_tags, (
            f"{rule} should carry {expected_code}"
        )

    def test_rule_13_weekend_case_uses_a_saturday_clock(self) -> None:
        saturday = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
        gate = RiskGate(
            limits=RiskLimitConfig(
                trading_enabled=True,
                symbol_allowlist=frozenset(UNIVERSE),
                entry_rules=EntryRulePolicy(block_weekend_and_late_friday=True),
            ),
            kill_switch=KillSwitch(),
            clock=lambda: saturday,
        )

        decision = gate.evaluate(
            _intent(),
            estimated_price=Decimal("1.1000"),
            estimated_quantity=Decimal("10000"),
            account_context=_context(),
        )

        assert decision.approved is False
        assert "WEEKEND" in decision.risk_tags


class TestCloseExemptionMatrix:
    """A close is exempt from every entry rule but rule 3 and the switch."""

    def test_close_passes_every_entry_rule(self) -> None:
        gate = _gate()
        close = _intent(
            reduce_only=True,
            side="sell",
            stop_loss=None,
            take_profit=None,
            quantity=Decimal("10000"),
        )
        hostile = _context(
            quote_captured_at=NOW,
            open_position_count=9,
            daily_open_count=9,
            daily_symbol_open_count=9,
            frozen_symbols={SYMBOL: "frozen"},
            recent_high_impact_events={SYMBOL: "fomc"},
            drawdown_block_reason="blocked",
            current_spread=Decimal("0.0100"),
            reconciliation_state="frozen",
            symbol_types={SYMBOL: "CFD"},
        )

        decision = _evaluate(gate, intent=close, context=hostile)

        assert decision.approved is True

    def test_close_still_needs_a_fresh_quote(self) -> None:
        gate = _gate()
        close = _intent(
            reduce_only=True,
            side="sell",
            stop_loss=None,
            take_profit=None,
        )

        decision = _evaluate(
            gate,
            intent=close,
            context=_context(quote_captured_at=NOW - timedelta(minutes=5)),
        )

        assert decision.approved is False
        assert "QUOTE_STALE" in decision.risk_tags

    def test_kill_switch_only_allows_explicit_reduction(self) -> None:
        gate = _gate(kill_switch=KillSwitch(active=True, reason="manual halt"))
        close = _intent(reduce_only=True, side="sell", stop_loss=None, take_profit=None)

        decision = _evaluate(gate, intent=close, context=_context())

        assert decision.approved is True
        assert "kill_switch_reduce_only" in decision.risk_tags
        entry = close.model_copy(update={"reduce_only": False})
        blocked = _evaluate(gate, intent=entry, context=_context())
        assert blocked.approved is False
        assert "kill_switch" in blocked.risk_tags


class TestSizingMatrix:
    """EUR_USD (USD quote) and USD_JPY (JPY quote) both size correctly."""

    def test_eur_usd_uses_the_risk_budget_without_conversion(self) -> None:
        from alphabrief_trader.sizing import SizingInputs, size_entry

        result = size_entry(
            inputs=SizingInputs(nav=Decimal("100000"), quote_to_home=Decimal("1")),
            reference_price=Decimal("1.1000"),
            stop_loss=Decimal("1.0900"),
        )

        # 250 / 0.0100 = 25000 units, below the 50% NAV notional cap.
        assert result.units == Decimal("25000")
        assert result.outcome == "sized"

    def test_usd_jpy_converts_the_quote_currency_loss(self) -> None:
        from alphabrief_trader.sizing import SizingInputs, size_entry

        result = size_entry(
            inputs=SizingInputs(
                nav=Decimal("100000"),
                quote_to_home=Decimal("0.0066667"),
            ),
            reference_price=Decimal("150"),
            stop_loss=Decimal("149"),
        )

        # 250 / (1.0 x 0.0066667) = 37500.1875 -> 37499 units (floor), and
        # the home-currency notional 37499 x 150 x 0.0066667 = 37499.19
        # stays under the 50% NAV cap, so the risk budget alone sizes it.
        assert result.units == Decimal("37499")
        assert result.notional <= Decimal("50000")
        assert result.reason == "sized from the risk budget"

    def test_usd_jpy_notional_cap_binds_on_a_tight_stop(self) -> None:
        from alphabrief_trader.sizing import SizingInputs, size_entry

        result = size_entry(
            inputs=SizingInputs(
                nav=Decimal("100000"),
                quote_to_home=Decimal("0.0066667"),
            ),
            reference_price=Decimal("150"),
            stop_loss=Decimal("149.9"),
        )

        # The risk budget would allow 250 / (0.1 x 0.0066667) = 375000
        # units; the 50% NAV notional cap binds first.
        assert "clamped" in result.reason
        assert result.notional <= Decimal("50000")
        assert result.units < Decimal("375000")

    def test_usd_jpy_without_conversion_would_be_wrong(self) -> None:
        from alphabrief_trader.sizing import SizingInputs, size_entry

        converted = size_entry(
            inputs=SizingInputs(
                nav=Decimal("100000"), quote_to_home=Decimal("0.0066667")
            ),
            reference_price=Decimal("150"),
            stop_loss=Decimal("149"),
        )
        unconverted = size_entry(
            inputs=SizingInputs(nav=Decimal("100000"), quote_to_home=Decimal("1")),
            reference_price=Decimal("150"),
            stop_loss=Decimal("149"),
        )

        assert converted.units != unconverted.units
        assert converted.actual_risk < Decimal("250")
