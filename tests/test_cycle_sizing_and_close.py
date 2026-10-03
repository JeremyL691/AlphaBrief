"""Cycle-level tests for 5.5 intents, 5.6 sizing and the close path."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from _helpers import FakeExecutionBackend
from alphabrief_models import ModelGateway
from alphabrief_risk import KillSwitch, RiskGate, RiskLimitConfig
from alphabrief_risk.account_context import AccountExposureContext
from alphabrief_risk.entry_rules import EntryRulePolicy
from alphabrief_trader.committee import TradingCommittee
from alphabrief_trader.daily_cycle import DailyTradingCycle
from alphabrief_trader.db_store import AiTradingStore
from alphabrief_trader.intents import deterministic_intent_id
from alphabrief_trader.schemas import MarketSnapshot
from alphabrief_trader.sizing import SizingInputs
from committee_provider import GroundedProvider

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)

_BULLISH_PAYLOAD = {
    "analysis": "Bullish continuation.",
    "view": "bullish",
    "confidence": 0.7,
    "evidence_ids": ["input-evidence"],
    "risks": ["r1"],
    "suggested_action": "buy",
    "target_position_pct": 0.10,
    "veto": False,
    "needs_human_review": False,
}


def _committee() -> TradingCommittee:
    provider = GroundedProvider(
        provider_name="fake",
        model_name="fake-1",
        capabilities=["structured_output"],
        structured_output=_BULLISH_PAYLOAD,
    )
    return TradingCommittee(gateway=ModelGateway(providers=[provider]))


def _snapshot(symbol: str = "EUR_USD", *, atr: Decimal | None = None) -> MarketSnapshot:
    return MarketSnapshot(
        symbol=symbol,
        reference_price=Decimal("1.1000"),
        atr=atr,
        data_version="test-v1",
        captured_at=NOW,
    )


def _risk_gate(
    symbols: tuple[str, ...],
    *,
    entry_rules: EntryRulePolicy | None = None,
    trading_enabled: bool = True,
    kill_switch: KillSwitch | None = None,
    clock: datetime = NOW,
) -> RiskGate:
    return RiskGate(
        limits=RiskLimitConfig(
            trading_enabled=trading_enabled,
            symbol_allowlist=frozenset(symbols),
            entry_rules=entry_rules,
        ),
        kill_switch=kill_switch or KillSwitch(),
        clock=lambda: clock,
    )


def _account_context(
    *,
    symbol: str = "EUR_USD",
    quote_age_seconds: int = 1,
    quote_captured_at: datetime | None = None,
    tradeable: bool = True,
    frozen: dict[str, str] | None = None,
) -> AccountExposureContext:
    return AccountExposureContext(
        current_total_exposure=Decimal("0"),
        cash=Decimal("100000"),
        account_id="acct-1",
        captured_at=NOW,
        equity=Decimal("100000"),
        open_position_count=0,
        daily_open_count=0,
        daily_symbol_open_count=0,
        quote_captured_at=quote_captured_at
        or NOW - timedelta(seconds=quote_age_seconds),
        quote_tradeable=tradeable,
        frozen_symbols=frozen or {},
    )


@pytest.fixture
def store(tmp_path: Path) -> Iterator[AiTradingStore]:
    s = AiTradingStore(db_path=tmp_path / "cycle.db")
    try:
        yield s
    finally:
        s.close()


class TestRiskSizedEntries:
    def test_entry_units_come_from_the_risk_budget(self, store: AiTradingStore) -> None:
        backend = FakeExecutionBackend()
        # ATR 0.0050 with the 1.5x default stop = 0.0075 stop distance.
        # 100000 NAV * 0.25% = 250 risk; 250 / 0.0075 = 33333 units.
        cycle = DailyTradingCycle(
            committee=_committee(),
            risk_gate=_risk_gate(("EUR_USD",)),
            execution_backend=backend,
            store=store,
            snapshot_loader=lambda s: _snapshot(s, atr=Decimal("0.0050")),
            enabled=True,
            trading_mode="on",
            clock=lambda: NOW,
            sizing_provider=lambda symbol: SizingInputs(
                nav=Decimal("100000"), quote_to_home=Decimal("1")
            ),
        )

        record = cycle.run(["EUR_USD"])

        assert record.outcome == "executed"
        attempt = record.attempts[0]
        assert attempt.filled is True
        assert attempt.order_intent_json["quantity"] == "33333"
        assert attempt.order_intent_json["stop_loss"] is not None
        assert attempt.order_intent_json["target_position_pct"] is None
        assert backend.submissions[0].intent.quantity == Decimal("33333")

    def test_entry_units_shrink_when_the_risk_is_halved(
        self, store: AiTradingStore
    ) -> None:
        cycle = DailyTradingCycle(
            committee=_committee(),
            risk_gate=_risk_gate(("EUR_USD",)),
            execution_backend=FakeExecutionBackend(),
            store=store,
            snapshot_loader=lambda s: _snapshot(s, atr=Decimal("0.0050")),
            enabled=True,
            trading_mode="on",
            clock=lambda: NOW,
            # Soak day 1 halves the risk: 125 / 0.0075 = 16666 units.
            sizing_provider=lambda symbol: SizingInputs(
                nav=Decimal("100000"), soak_day=1
            ),
        )

        record = cycle.run(["EUR_USD"])

        assert record.attempts[0].order_intent_json["quantity"] == "16666"

    def test_intent_id_is_the_deterministic_hash(self, store: AiTradingStore) -> None:
        cycle = DailyTradingCycle(
            committee=_committee(),
            risk_gate=_risk_gate(("EUR_USD",)),
            execution_backend=FakeExecutionBackend(),
            store=store,
            snapshot_loader=lambda s: _snapshot(s, atr=Decimal("0.0050")),
            enabled=True,
            trading_mode="on",
            clock=lambda: NOW,
            sizing_provider=lambda symbol: SizingInputs(nav=Decimal("100000")),
        )

        record = cycle.run(["EUR_USD"])

        assert record.attempts[0].intent_id == deterministic_intent_id(
            record.cycle_id, "EUR_USD", "entry:buy"
        )

    def test_unavailable_sizing_inputs_refuse_the_entry(
        self, store: AiTradingStore
    ) -> None:
        backend = FakeExecutionBackend()
        cycle = DailyTradingCycle(
            committee=_committee(),
            risk_gate=_risk_gate(("EUR_USD",)),
            execution_backend=backend,
            store=store,
            snapshot_loader=lambda s: _snapshot(s, atr=Decimal("0.0050")),
            enabled=True,
            trading_mode="on",
            clock=lambda: NOW,
            sizing_provider=lambda symbol: None,
        )

        record = cycle.run(["EUR_USD"])

        assert record.outcome == "skipped_no_intent"
        assert backend.submission_count == 0
        attempt = record.attempts[0]
        assert attempt.approved is False
        assert attempt.risk_tags == ["sizing_no_trade"]
        assert attempt.risk_decision_id is None

    def test_missing_atr_refuses_the_entry(self, store: AiTradingStore) -> None:
        backend = FakeExecutionBackend()
        cycle = DailyTradingCycle(
            committee=_committee(),
            risk_gate=_risk_gate(("EUR_USD",)),
            execution_backend=backend,
            store=store,
            snapshot_loader=lambda s: _snapshot(s),  # no ATR
            enabled=True,
            trading_mode="on",
            clock=lambda: NOW,
            sizing_provider=lambda symbol: SizingInputs(nav=Decimal("100000")),
        )

        record = cycle.run(["EUR_USD"])

        assert record.outcome == "skipped_no_intent"
        assert backend.submission_count == 0

    def test_quantity_override_still_pins_the_size(
        self, store: AiTradingStore
    ) -> None:
        cycle = DailyTradingCycle(
            committee=_committee(),
            risk_gate=_risk_gate(("EUR_USD",)),
            execution_backend=FakeExecutionBackend(),
            store=store,
            snapshot_loader=lambda s: _snapshot(s, atr=Decimal("0.0050")),
            enabled=True,
            trading_mode="on",
            clock=lambda: NOW,
            quantity_override=Decimal("1000"),
            sizing_provider=lambda symbol: SizingInputs(nav=Decimal("100000")),
        )

        record = cycle.run(["EUR_USD"])

        intent_json = record.attempts[0].order_intent_json
        assert intent_json["quantity"] == "1000"
        assert intent_json["source"] == "manual"


class TestClosePath:
    def _cycle(
        self,
        store: AiTradingStore,
        *,
        backend: FakeExecutionBackend | None = None,
        gate: RiskGate | None = None,
        context: AccountExposureContext | None = None,
        clock: datetime = NOW,
    ) -> tuple[DailyTradingCycle, FakeExecutionBackend]:
        backend = backend or FakeExecutionBackend()
        cycle = DailyTradingCycle(
            committee=_committee(),
            risk_gate=gate or _risk_gate(("EUR_USD",)),
            execution_backend=backend,
            store=store,
            snapshot_loader=lambda s: None,
            enabled=True,
            trading_mode="on",
            clock=lambda: clock,
            account_context_provider=(
                (lambda symbol: context) if context is not None else None
            ),
        )
        return cycle, backend

    def test_close_submits_a_reduce_only_order(self, store: AiTradingStore) -> None:
        cycle, backend = self._cycle(store)

        attempt = cycle.close_position(
            symbol="EUR_USD",
            position_units=Decimal("1000"),
            reference_price=Decimal("1.1000"),
            cycle_id="cyc_close_1",
            now=NOW,
            reason="operator close",
        )

        assert attempt.outcome == "executed"
        assert attempt.filled is True
        assert attempt.risk_decision_id is not None
        submitted = backend.submissions[0].intent
        assert submitted.reduce_only is True
        assert submitted.side == "sell"
        assert submitted.quantity == Decimal("1000")
        assert submitted.intent_id == deterministic_intent_id(
            "cyc_close_1", "EUR_USD", "close:sell"
        )

    def test_close_remains_executable_under_kill_switch(
        self, store: AiTradingStore
    ) -> None:
        gate = _risk_gate(
            ("EUR_USD",), kill_switch=KillSwitch(active=True, reason="manual halt")
        )
        cycle, backend = self._cycle(store, gate=gate)

        attempt = cycle.close_position(
            symbol="EUR_USD",
            position_units=Decimal("1000"),
            reference_price=Decimal("1.1000"),
            cycle_id="cyc_close_2",
            now=NOW,
            reason="operator close",
        )

        assert attempt.outcome == "executed"
        assert "kill_switch_reduce_only" in attempt.risk_tags
        assert backend.submission_count == 1
        assert backend.submissions[0].intent.reduce_only is True

    def test_frozen_symbol_and_trading_off_do_not_block_a_close(
        self, store: AiTradingStore
    ) -> None:
        rules = EntryRulePolicy(
            max_quote_age_seconds=15,
            require_quote_tradeable=True,
            max_daily_opens=0,
            max_daily_symbol_opens=0,
            max_open_positions=0,
            require_protective_orders=True,
            block_weekend_and_late_friday=True,
        )
        saturday = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
        gate = _risk_gate(
            ("EUR_USD",),
            entry_rules=rules,
            trading_enabled=False,
            clock=saturday,
        )
        cycle, backend = self._cycle(
            store,
            gate=gate,
            clock=saturday,
            context=_account_context(
                frozen={"EUR_USD": "3 losing closes in a row"},
                quote_captured_at=saturday,
            ),
        )

        attempt = cycle.close_position(
            symbol="EUR_USD",
            position_units=Decimal("1000"),
            reference_price=Decimal("1.1000"),
            cycle_id="cyc_close_3",
            now=saturday,
            reason="weekend close-out",
        )

        assert attempt.outcome == "executed"
        assert backend.submission_count == 1

    def test_close_without_a_fresh_quote_fails_closed(
        self, store: AiTradingStore
    ) -> None:
        rules = EntryRulePolicy(
            max_quote_age_seconds=15, require_quote_tradeable=True
        )
        gate = _risk_gate(("EUR_USD",), entry_rules=rules)
        cycle, backend = self._cycle(
            store, gate=gate, context=_account_context(quote_age_seconds=60)
        )

        attempt = cycle.close_position(
            symbol="EUR_USD",
            position_units=Decimal("1000"),
            reference_price=Decimal("1.1000"),
            cycle_id="cyc_close_4",
            now=NOW,
            reason="operator close",
        )

        assert attempt.outcome == "blocked_risk_gate"
        assert "QUOTE_STALE" in attempt.risk_tags
        assert backend.submission_count == 0

    def test_close_with_trading_off_reports_without_submitting(
        self, store: AiTradingStore
    ) -> None:
        cycle, backend = self._cycle(store)

        attempt = cycle.close_position(
            symbol="EUR_USD",
            position_units=Decimal("1000"),
            reference_price=Decimal("1.1000"),
            cycle_id="cyc_close_5",
            now=NOW,
            reason="operator close",
            submit=False,
        )

        assert attempt.outcome == "blocked_trading_off"
        assert attempt.reason == "NO_TRADE_TRADING_OFF"
        assert attempt.risk_decision_id is not None
        assert backend.submission_count == 0
