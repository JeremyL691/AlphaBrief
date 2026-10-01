"""Tests for the rule-11 drawdown state machine (PROJECT_GUIDE 5.7).

3% blocks new exposure for 48 hours and then resumes at half risk until
the drawdown recovers below 3%; 5% halts new exposure for the rest of the
soak. The state is persisted, so a restart cannot reset a block.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_core import OrderIntent
from alphabrief_risk import (
    DRAWDOWN_BLOCK_PCT,
    DRAWDOWN_HALF_RISK_MULTIPLIER,
    DRAWDOWN_HALT_PCT,
    DrawdownState,
    DrawdownStateStore,
    drawdown_pct,
    evaluate_drawdown,
)
from alphabrief_risk.account_context import AccountExposureContext
from alphabrief_risk.entry_rules import EntryRulePolicy, evaluate_entry_rules

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
NAV = Decimal("100000")


def _intent(**overrides: object) -> OrderIntent:
    payload: dict[str, object] = {
        "intent_id": "intent_1",
        "source": "model",
        "symbol": "EUR_USD",
        "side": "buy",
        "order_type": "market",
        "quantity": Decimal("1000"),
        "stop_loss": Decimal("1.0900"),
        "take_profit": Decimal("1.1200"),
        "rationale": "drawdown test",
        "created_at": NOW,
    }
    payload.update(overrides)
    return OrderIntent.model_validate(payload)


def _context(**overrides: object) -> AccountExposureContext:
    payload: dict[str, object] = {
        "current_total_exposure": Decimal("0"),
        "cash": NAV,
        "account_id": "acct-1",
        "captured_at": NOW,
        "quote_captured_at": NOW,
        "quote_tradeable": True,
    }
    payload.update(overrides)
    return AccountExposureContext.model_validate(payload)


class TestStateMachine:
    def test_small_drawdown_is_normal(self) -> None:
        verdict = evaluate_drawdown(
            equity=Decimal("99000"), high_water=NAV, now=NOW
        )

        assert verdict.state.state == "normal"
        assert verdict.blocked is False
        assert verdict.risk_multiplier == Decimal("1")
        assert verdict.code == ""

    def test_three_percent_boundary_blocks_for_48_hours(self) -> None:
        equity = NAV * (Decimal("1") - DRAWDOWN_BLOCK_PCT)

        verdict = evaluate_drawdown(equity=equity, high_water=NAV, now=NOW)

        assert verdict.blocked is True
        assert verdict.code == "DRAWDOWN"
        assert verdict.state.state == "blocked"
        assert verdict.state.blocked_until == NOW + timedelta(hours=48)
        assert "48" not in verdict.reason or "blocked until" in verdict.reason

    def test_block_expiry_resumes_at_half_risk(self) -> None:
        equity = NAV * (Decimal("1") - DRAWDOWN_BLOCK_PCT)
        first = evaluate_drawdown(equity=equity, high_water=NAV, now=NOW)

        later = evaluate_drawdown(
            equity=equity,
            high_water=NAV,
            now=NOW + timedelta(hours=49),
            previous=first.state,
        )

        assert later.state.state == "half_risk"
        assert later.blocked is False
        assert later.risk_multiplier == DRAWDOWN_HALF_RISK_MULTIPLIER
        assert later.code == ""

    def test_recovery_below_three_percent_clears_the_state(self) -> None:
        half = DrawdownState(
            state="half_risk",
            triggered_at=NOW - timedelta(days=3),
            blocked_until=NOW - timedelta(days=1),
            high_water=NAV,
            updated_at=NOW - timedelta(days=1),
        )

        recovered = evaluate_drawdown(
            equity=NAV, high_water=NAV, now=NOW, previous=half
        )

        assert recovered.state.state == "normal"
        assert recovered.risk_multiplier == Decimal("1")

    def test_five_percent_halts_for_the_rest_of_the_soak(self) -> None:
        equity = NAV * (Decimal("1") - DRAWDOWN_HALT_PCT)

        verdict = evaluate_drawdown(equity=equity, high_water=NAV, now=NOW)

        assert verdict.state.state == "soak_halted"
        assert verdict.blocked is True
        assert verdict.state.blocked_until is None
        assert "soak limit" in verdict.reason

    def test_halt_is_sticky_even_after_recovery(self) -> None:
        halted = evaluate_drawdown(
            equity=NAV * (Decimal("1") - DRAWDOWN_HALT_PCT),
            high_water=NAV,
            now=NOW,
        )

        after = evaluate_drawdown(
            equity=NAV, high_water=NAV, now=NOW + timedelta(days=1),
            previous=halted.state,
        )

        assert after.state.state == "soak_halted"
        assert after.blocked is True

    def test_high_water_mark_only_rises(self) -> None:
        verdict = evaluate_drawdown(
            equity=Decimal("120000"),
            high_water=NAV,
            now=NOW,
        )

        assert verdict.state.high_water == Decimal("120000")
        assert verdict.drawdown_pct == 0

    def test_drawdown_pct_helper(self) -> None:
        assert drawdown_pct(equity=NAV, high_water=NAV) == 0
        assert drawdown_pct(equity=Decimal("95000"), high_water=NAV) == Decimal(
            "0.05"
        )
        with pytest.raises(ValueError, match="high_water must be positive"):
            drawdown_pct(equity=NAV, high_water=Decimal("0"))


class TestPersistence:
    def test_state_survives_a_reopen(self, tmp_path: Path) -> None:
        db = tmp_path / "drawdown.duckdb"
        store = DrawdownStateStore(db_path=db)
        try:
            verdict = evaluate_drawdown(
                equity=NAV * (Decimal("1") - DRAWDOWN_BLOCK_PCT),
                high_water=NAV,
                now=NOW,
            )
            store.save("acct-1", verdict.state)
        finally:
            store.close()

        reopened = DrawdownStateStore(db_path=db)
        try:
            loaded = reopened.load("acct-1")
        finally:
            reopened.close()

        assert loaded is not None
        assert loaded.state == "blocked"
        assert loaded.blocked_until == NOW + timedelta(hours=48)
        assert loaded.high_water == NAV

    def test_unknown_account_has_no_state(self, tmp_path: Path) -> None:
        store = DrawdownStateStore(db_path=tmp_path / "d.duckdb")
        try:
            assert store.load("nobody") is None
        finally:
            store.close()


class TestRuleIntegration:
    def test_drawdown_block_rejects_an_entry(self) -> None:
        policy = EntryRulePolicy(block_on_drawdown=True)
        context = _context(
            drawdown_block_reason="drawdown 3.5% blocks new exposure"
        )

        rejections = evaluate_entry_rules(
            _intent(), policy=policy, now=NOW, account_context=context
        )

        assert [r.code for r in rejections] == ["DRAWDOWN"]
        assert "3.5%" in rejections[0].detail

    def test_no_block_allows_the_entry(self) -> None:
        policy = EntryRulePolicy(block_on_drawdown=True)

        assert (
            evaluate_entry_rules(
                _intent(),
                policy=policy,
                now=NOW,
                account_context=_context(),
            )
            == ()
        )

    def test_missing_context_fails_closed(self) -> None:
        policy = EntryRulePolicy(block_on_drawdown=True)

        rejections = evaluate_entry_rules(
            _intent(), policy=policy, now=NOW, account_context=None
        )

        assert [r.code for r in rejections] == ["DRAWDOWN"]

    def test_rule_disabled_by_default(self) -> None:
        assert (
            evaluate_entry_rules(
                _intent(),
                policy=EntryRulePolicy(),
                now=NOW,
                account_context=_context(drawdown_block_reason="blocked"),
            )
            == ()
        )

    def test_close_is_exempt(self) -> None:
        policy = EntryRulePolicy(block_on_drawdown=True)
        close = _intent(
            reduce_only=True,
            side="sell",
            stop_loss=None,
            take_profit=None,
        )

        assert (
            evaluate_entry_rules(
                close,
                policy=policy,
                now=NOW,
                account_context=_context(drawdown_block_reason="blocked"),
            )
            == ()
        )


class TestHalfRiskSizing:
    def test_multiplier_halves_the_units(self) -> None:
        from alphabrief_trader.sizing import SizingInputs, size_entry

        # A 0.01 stop keeps the risk-sized order below the notional cap,
        # so this test measures the multiplier alone.
        full = size_entry(
            inputs=SizingInputs(nav=NAV),
            reference_price=Decimal("1.1000"),
            stop_loss=Decimal("1.0900"),
        )
        half = size_entry(
            inputs=SizingInputs(nav=NAV, risk_multiplier=Decimal("0.5")),
            reference_price=Decimal("1.1000"),
            stop_loss=Decimal("1.0900"),
        )

        # 250 / 0.0100 = 25000 units; halved risk = 125 / 0.0100 = 12500.
        assert full.units == Decimal("25000")
        assert half.units == Decimal("12500")
        assert half.risk_amount == full.risk_amount / 2

    def test_non_positive_multiplier_is_refused(self) -> None:
        from alphabrief_trader.sizing import SizingError, SizingInputs, size_entry

        with pytest.raises(SizingError, match="risk_multiplier"):
            size_entry(
                inputs=SizingInputs(nav=NAV, risk_multiplier=Decimal("0")),
                reference_price=Decimal("1.1000"),
                stop_loss=Decimal("1.0900"),
            )
