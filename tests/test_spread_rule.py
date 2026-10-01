"""Tests for rule 4: the spread against its own recent median (PROJECT_GUIDE 5.7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_core import OrderIntent
from alphabrief_data.quote_samples import (
    SPREAD_MEDIAN_SAMPLE_LIMIT,
    QuoteSample,
    QuoteSampleStore,
)
from alphabrief_risk import KillSwitch, RiskGate, RiskLimitConfig, evaluate_spread
from alphabrief_risk.account_context import AccountExposureContext
from alphabrief_risk.entry_rules import EntryRulePolicy, evaluate_entry_rules
from alphabrief_risk.spread_policy import median

#: Mid-hour so "minutes ago" samples stay inside the same UTC hour.
NOW = datetime(2026, 10, 1, 12, 30, tzinfo=UTC)


class TestMedian:
    def test_odd_count_takes_the_middle_value(self) -> None:
        assert median([Decimal("3"), Decimal("1"), Decimal("2")]) == Decimal("2")

    def test_even_count_averages_the_middle_pair(self) -> None:
        assert median(
            [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")]
        ) == Decimal("2.5")

    def test_empty_sequence_is_undefined(self) -> None:
        with pytest.raises(ValueError, match="median of an empty sequence"):
            median([])


class TestSpreadRule:
    def _samples(self, spread: str = "0.0002", count: int = 20) -> list[Decimal]:
        return [Decimal(spread)] * count

    def test_spread_at_the_limit_is_allowed(self) -> None:
        verdict = evaluate_spread(
            current_spread=Decimal("0.0004"),
            recent_spreads=self._samples(),
        )

        assert verdict.allowed is True
        assert verdict.code == ""
        assert verdict.limit == Decimal("0.0004")

    def test_spread_above_twice_the_median_is_rejected(self) -> None:
        verdict = evaluate_spread(
            current_spread=Decimal("0.0005"),
            recent_spreads=self._samples(),
        )

        assert verdict.allowed is False
        assert verdict.code == "SPREAD_WIDE"
        assert "exceeds 2 x the median" in verdict.reason

    def test_a_single_spike_does_not_widen_the_tolerance(self) -> None:
        samples = self._samples() + [Decimal("0.0100")]
        verdict = evaluate_spread(
            current_spread=Decimal("0.0004"),
            recent_spreads=samples,
        )

        # The median stays at the normal spread, so a normal spread passes
        # even though the mean would have been dragged up.
        assert verdict.allowed is True
        assert verdict.median_spread == Decimal("0.0002")

    def test_insufficient_history_fails_closed(self) -> None:
        verdict = evaluate_spread(
            current_spread=Decimal("0.0001"),
            recent_spreads=[Decimal("0.0002")] * 4,
        )

        assert verdict.allowed is False
        assert verdict.code == "SPREAD_WIDE"
        assert "only 4 same-period spread sample(s)" in verdict.reason

    def test_no_history_fails_closed(self) -> None:
        verdict = evaluate_spread(
            current_spread=Decimal("0.0001"), recent_spreads=[]
        )

        assert verdict.allowed is False
        assert verdict.median_spread is None

    def test_invalid_inputs_are_refused(self) -> None:
        with pytest.raises(ValueError, match="must not be negative"):
            evaluate_spread(current_spread=Decimal("-1"), recent_spreads=[])
        with pytest.raises(ValueError, match="multiplier must be positive"):
            evaluate_spread(
                current_spread=Decimal("1"),
                recent_spreads=self._samples(),
                multiplier=Decimal("0"),
            )
        with pytest.raises(ValueError, match="min_samples"):
            evaluate_spread(
                current_spread=Decimal("1"),
                recent_spreads=self._samples(),
                min_samples=0,
            )

    def test_verdict_serializes_for_the_audit_record(self) -> None:
        verdict = evaluate_spread(
            current_spread=Decimal("0.0005"),
            recent_spreads=self._samples(),
        )

        payload = verdict.to_dict()
        assert payload["code"] == "SPREAD_WIDE"
        assert payload["samples"] == 20


class TestQuoteSampleStore:
    @pytest.fixture
    def store(self, tmp_path: Path):
        s = QuoteSampleStore(db_path=tmp_path / "quotes.duckdb")
        try:
            yield s
        finally:
            s.close()

    def _sample(self, *, minutes: int = 0, spread: str = "0.0002") -> QuoteSample:
        mid = Decimal("1.1000")
        half = Decimal(spread) / 2
        return QuoteSample(
            symbol="EUR_USD",
            captured_at=NOW - timedelta(minutes=minutes),
            bid=mid - half,
            ask=mid + half,
            spread=Decimal(spread),
            mid=mid,
        )

    def test_recording_is_idempotent_per_instant(self, store: QuoteSampleStore) -> None:
        assert store.record(self._sample()) is True
        assert store.record(self._sample()) is False
        assert store.count("EUR_USD") == 1

    def test_median_history_is_scoped_to_the_same_hour(
        self, store: QuoteSampleStore
    ) -> None:
        store.record(self._sample(minutes=0, spread="0.0002"))
        store.record(self._sample(minutes=5, spread="0.0004"))
        # A different hour of day must not be part of the same-period set.
        other_hour = self._sample(minutes=0, spread="0.0099")
        store.record(
            QuoteSample(
                symbol="EUR_USD",
                captured_at=other_hour.captured_at - timedelta(hours=3),
                bid=other_hour.bid,
                ask=other_hour.ask,
                spread=other_hour.spread,
                mid=other_hour.mid,
            )
        )

        spreads = store.recent_spreads("EUR_USD", hour=12)

        # Newest first, and only the same hour.
        assert spreads == [Decimal("0.0002"), Decimal("0.0004")]

    def test_history_is_scoped_to_the_symbol_and_limited(
        self, store: QuoteSampleStore
    ) -> None:
        for index in range(SPREAD_MEDIAN_SAMPLE_LIMIT + 5):
            store.record(self._sample(minutes=index))
        store.record(
            QuoteSample(
                symbol="GBP_USD",
                captured_at=NOW,
                bid=Decimal("1.2000"),
                ask=Decimal("1.2002"),
                spread=Decimal("0.0002"),
                mid=Decimal("1.2001"),
            )
        )

        assert len(store.recent_spreads("EUR_USD", hour=12)) == (
            SPREAD_MEDIAN_SAMPLE_LIMIT
        )
        assert len(store.recent_spreads("GBP_USD", hour=12)) == 1

    def test_ask_below_bid_is_refused(self) -> None:
        with pytest.raises(ValueError, match="ask must not be below bid"):
            QuoteSample(
                symbol="EUR_USD",
                captured_at=NOW,
                bid=Decimal("1.1000"),
                ask=Decimal("1.0900"),
                spread=Decimal("-0.0100"),
                mid=Decimal("1.0950"),
            )

    def test_bad_hour_is_refused(self, store: QuoteSampleStore) -> None:
        with pytest.raises(ValueError, match="hour must be within"):
            store.recent_spreads("EUR_USD", hour=24)


class TestRuleIntegration:
    def _intent(self, **overrides: object) -> OrderIntent:
        payload: dict[str, object] = {
            "intent_id": "intent_1",
            "source": "model",
            "symbol": "EUR_USD",
            "side": "buy",
            "order_type": "market",
            "quantity": Decimal("1000"),
            "stop_loss": Decimal("1.0900"),
            "take_profit": Decimal("1.1200"),
            "rationale": "rule 4 test",
            "created_at": NOW,
        }
        payload.update(overrides)
        return OrderIntent.model_validate(payload)

    def _context(self, **overrides: object) -> AccountExposureContext:
        payload: dict[str, object] = {
            "current_total_exposure": Decimal("0"),
            "cash": Decimal("100000"),
            "account_id": "acct-1",
            "captured_at": NOW,
            "quote_captured_at": NOW,
            "quote_tradeable": True,
        }
        payload.update(overrides)
        return AccountExposureContext.model_validate(payload)

    def test_wide_spread_rejects_the_entry(self) -> None:
        policy = EntryRulePolicy(max_spread_median_multiplier=Decimal("2"))

        rejections = evaluate_entry_rules(
            self._intent(),
            policy=policy,
            now=NOW,
            account_context=self._context(
                current_spread=Decimal("0.0005"),
                recent_spreads=(Decimal("0.0002"),) * 20,
            ),
        )

        assert [r.code for r in rejections] == ["SPREAD_WIDE"]

    def test_normal_spread_allows_the_entry(self) -> None:
        policy = EntryRulePolicy(max_spread_median_multiplier=Decimal("2"))

        assert (
            evaluate_entry_rules(
                self._intent(),
                policy=policy,
                now=NOW,
                account_context=self._context(
                    current_spread=Decimal("0.0003"),
                    recent_spreads=(Decimal("0.0002"),) * 20,
                ),
            )
            == ()
        )

    def test_missing_spread_fails_closed(self) -> None:
        policy = EntryRulePolicy(max_spread_median_multiplier=Decimal("2"))

        rejections = evaluate_entry_rules(
            self._intent(),
            policy=policy,
            now=NOW,
            account_context=self._context(),
        )

        assert [r.code for r in rejections] == ["SPREAD_WIDE"]

    def test_rule_disabled_by_default(self) -> None:
        assert (
            evaluate_entry_rules(
                self._intent(),
                policy=EntryRulePolicy(),
                now=NOW,
                account_context=self._context(),
            )
            == ()
        )

    def test_close_is_exempt(self) -> None:
        policy = EntryRulePolicy(max_spread_median_multiplier=Decimal("2"))
        close = self._intent(
            reduce_only=True, side="sell", stop_loss=None, take_profit=None
        )

        assert (
            evaluate_entry_rules(
                close,
                policy=policy,
                now=NOW,
                account_context=self._context(
                    current_spread=Decimal("0.0100"),
                    recent_spreads=(Decimal("0.0002"),) * 20,
                ),
            )
            == ()
        )

    def test_gate_reports_the_guide_code(self) -> None:
        gate = RiskGate(
            limits=RiskLimitConfig(
                trading_enabled=True,
                symbol_allowlist=frozenset({"EUR_USD"}),
                entry_rules=EntryRulePolicy(
                    max_spread_median_multiplier=Decimal("2")
                ),
            ),
            kill_switch=KillSwitch(),
            clock=lambda: NOW,
        )

        decision = gate.evaluate(
            self._intent(),
            estimated_price=Decimal("1.1000"),
            estimated_quantity=Decimal("1000"),
            account_context=self._context(
                current_spread=Decimal("0.0009"),
                recent_spreads=(Decimal("0.0002"),) * 20,
            ),
        )

        assert decision.approved is False
        assert "SPREAD_WIDE" in decision.risk_tags
