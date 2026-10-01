"""Tests for the decision → intent conversion (PROJECT_GUIDE 5.5)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alphabrief_trader.intents import (
    ACTION_CLOSE,
    ACTION_ENTRY,
    IntentError,
    IntentSizing,
    build_close_intent,
    build_entry_intent,
    deterministic_intent_id,
    intent_action,
)

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


class TestDeterministicIntentId:
    def test_same_cycle_instrument_action_hash_identically(self) -> None:
        first = deterministic_intent_id("cyc_1", "EUR_USD", "entry:buy")
        second = deterministic_intent_id("cyc_1", "EUR_USD", "entry:buy")

        assert first == second
        assert first.startswith("ai_")
        assert len(first) == len("ai_") + 12

    def test_each_component_changes_the_id(self) -> None:
        base = deterministic_intent_id("cyc_1", "EUR_USD", "entry:buy")

        assert base != deterministic_intent_id("cyc_2", "EUR_USD", "entry:buy")
        assert base != deterministic_intent_id("cyc_1", "GBP_USD", "entry:buy")
        assert base != deterministic_intent_id("cyc_1", "EUR_USD", "close:sell")

    def test_missing_components_are_refused(self) -> None:
        with pytest.raises(IntentError):
            deterministic_intent_id("", "EUR_USD", "entry:buy")
        with pytest.raises(IntentError):
            deterministic_intent_id("cyc_1", "", "entry:buy")
        with pytest.raises(IntentError):
            deterministic_intent_id("cyc_1", "EUR_USD", "")

    def test_action_carries_the_kind_and_side(self) -> None:
        assert intent_action(reduce_only=False, side="buy") == ACTION_ENTRY + ":buy"
        assert intent_action(reduce_only=True, side="sell") == ACTION_CLOSE + ":sell"


class TestCloseIntent:
    def test_long_position_closes_by_selling_it_back(self) -> None:
        intent = build_close_intent(
            cycle_id="cyc_1",
            symbol="EUR_USD",
            position_units=Decimal("1000"),
            now=NOW,
            reason="weekend close-out",
        )

        assert intent.side == "sell"
        assert intent.quantity == Decimal("1000")
        assert intent.reduce_only is True
        assert intent.stop_loss is None
        assert intent.take_profit is None
        assert "weekend close-out" in intent.rationale

    def test_short_position_closes_by_buying_it_back(self) -> None:
        intent = build_close_intent(
            cycle_id="cyc_1",
            symbol="USD_JPY",
            position_units=Decimal("-500"),
            now=NOW,
            reason="48h hold limit",
        )

        assert intent.side == "buy"
        assert intent.quantity == Decimal("500")

    def test_flat_position_is_refused(self) -> None:
        with pytest.raises(IntentError):
            build_close_intent(
                cycle_id="cyc_1",
                symbol="EUR_USD",
                position_units=Decimal("0"),
                now=NOW,
                reason="nothing to close",
            )

    def test_close_intent_id_is_reproducible(self) -> None:
        first = build_close_intent(
            cycle_id="cyc_1",
            symbol="EUR_USD",
            position_units=Decimal("1000"),
            now=NOW,
            reason="operator close",
        )
        second = build_close_intent(
            cycle_id="cyc_1",
            symbol="EUR_USD",
            position_units=Decimal("1000"),
            now=NOW,
            reason="operator close",
        )

        assert first.intent_id == second.intent_id
        assert first.intent_id == deterministic_intent_id(
            "cyc_1", "EUR_USD", "close:sell"
        )


class TestEntryIntent:
    def test_sized_entry_carries_units_and_protection(self) -> None:
        intent = build_entry_intent(
            cycle_id="cyc_1",
            symbol="EUR_USD",
            side="buy",
            sizing=IntentSizing(
                units=Decimal("50000"),
                stop_loss=Decimal("1.0950"),
                take_profit=Decimal("1.1100"),
                risk_amount=Decimal("250.0000"),
                notional=Decimal("55000"),
            ),
            target_position_pct=None,
            now=NOW,
            rationale="committee long",
        )

        assert intent.quantity == Decimal("50000")
        assert intent.stop_loss == Decimal("1.0950")
        assert intent.take_profit == Decimal("1.1100")
        assert intent.target_position_pct is None
        assert intent.intent_id == deterministic_intent_id(
            "cyc_1", "EUR_USD", "entry:buy"
        )

    def test_percentage_entry_keeps_the_committee_fraction(self) -> None:
        intent = build_entry_intent(
            cycle_id="cyc_1",
            symbol="EUR_USD",
            side="sell",
            sizing=None,
            target_position_pct=Decimal("0.10"),
            now=NOW,
            rationale="committee short",
            stop_loss=Decimal("1.1100"),
            take_profit=Decimal("1.0900"),
        )

        assert intent.target_position_pct == Decimal("0.10")
        assert intent.quantity is None

    def test_exactly_one_size_source_is_required(self) -> None:
        with pytest.raises(IntentError):
            build_entry_intent(
                cycle_id="cyc_1",
                symbol="EUR_USD",
                side="buy",
                sizing=IntentSizing(
                    units=Decimal("1000"),
                    stop_loss=Decimal("1.0"),
                    take_profit=Decimal("1.1"),
                    risk_amount=Decimal("10"),
                    notional=Decimal("1000"),
                ),
                target_position_pct=Decimal("0.10"),
                now=NOW,
                rationale="both",
            )
        with pytest.raises(IntentError):
            build_entry_intent(
                cycle_id="cyc_1",
                symbol="EUR_USD",
                side="buy",
                sizing=None,
                target_position_pct=None,
                now=NOW,
                rationale="neither",
            )
