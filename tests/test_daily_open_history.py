"""UTC entry caps must survive timezone changes, closes and database reopen."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from _helpers import FakeExecutionBackend
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_risk.account_context import AccountExposureContext
from alphabrief_risk.entry_rules import EntryRulePolicy
from alphabrief_trader.daily_cycle import DailyTradingCycle
from alphabrief_trader.db_store import AiTradingStore
from alphabrief_trader.schemas import DailyCycleRecord, OrderAttempt
from test_broker_input_quality import NOW
from test_manager_protocol import RawManager, committee, snapshot


def save_attempt(
    store: AiTradingStore,
    identity: str,
    at: datetime,
    *,
    symbol: str = "EUR_USD",
    reduce_only: bool = False,
    outcome: str = "executed",
) -> None:
    attempt = OrderAttempt.model_validate(
        {
            "intent_id": identity,
            "approved": True,
            "reason": "persisted entry history test",
            "requires_human_review": False,
            "outcome": outcome,
            "order_intent_json": {"symbol": symbol, "reduce_only": reduce_only},
            "created_at": at,
        }
    )
    store.save_cycle(
        DailyCycleRecord(
            cycle_id=identity,
            trading_day=at.astimezone(UTC).date().isoformat(),
            symbols=[symbol],
            attempts=[attempt],
            outcome=attempt.outcome,
            enabled=True,
            summary="persisted entry history test",
            created_at=at,
        )
    )


@pytest.mark.parametrize(
    "timezone",
    [
        "UTC",
        "America/Los_Angeles",
        "America/New_York",
        "Asia/Tokyo",
        "Europe/Berlin",
    ],
)
@pytest.mark.parametrize("day", ["2026-10-02", "2026-03-08", "2026-11-01"])
def test_utc_boundaries_and_closes_survive_reopen(
    tmp_path: Path,
    timezone: str,
    day: str,
) -> None:
    path = tmp_path / "history.duckdb"
    start = datetime.combine(date.fromisoformat(day), datetime.min.time(), tzinfo=UTC)
    end = start + timedelta(days=1)
    store = AiTradingStore(path)
    try:
        store._conn.execute("SET TimeZone = ?", [timezone])
        save_attempt(store, "previous", start - timedelta(microseconds=1))
        save_attempt(store, "midnight", start)
        save_attempt(store, "last", end - timedelta(microseconds=1), symbol="USD_JPY")
        save_attempt(store, "next", end)
        save_attempt(store, "close", start + timedelta(hours=1), reduce_only=True)
        save_attempt(store, "refused", start, outcome="blocked_risk_gate")
        save_attempt(store, "failed", start, outcome="error")
        expected = (2, {"EUR_USD": 1, "USD_JPY": 1})
        assert store.count_daily_opens(trading_day=day) == expected
    finally:
        store.close()
    store = AiTradingStore(path)
    try:
        store._conn.execute("SET TimeZone = ?", [timezone])
        assert store.count_daily_opens(trading_day=day) == expected
        assert store.count_daily_opens(trading_day=end.date().isoformat()) == (
            1,
            {"EUR_USD": 1},
        )
    finally:
        store.close()


@pytest.mark.parametrize(
    "intent",
    [
        None,
        [],
        {},
        {"symbol": ""},
        {"symbol": 123},
        {"symbol": "EUR_USD", "reduce_only": "false"},
        {"symbol": "EUR_USD", "reduce_only": 0},
    ],
)
def test_corrupt_history_is_unknown_not_zero(
    tmp_path: Path,
    intent: Any,
) -> None:
    import json

    store = AiTradingStore(tmp_path / "history.duckdb")
    try:
        save_attempt(store, "corrupt", NOW)
        store._conn.execute(
            "UPDATE ai_order_attempts SET attempt_json = ?::JSON",
            [json.dumps({"order_intent_json": intent})],
        )
        with pytest.raises(ValueError, match="daily entry history"):
            store.count_daily_opens(trading_day=NOW.date().isoformat())
    finally:
        store.close()


def test_legacy_missing_reduce_flag_conservatively_consumes_capacity(
    tmp_path: Path,
) -> None:
    store = AiTradingStore(tmp_path / "history.duckdb")
    try:
        save_attempt(store, "legacy", NOW)
        store._conn.execute(
            "UPDATE ai_order_attempts SET attempt_json = ?::JSON",
            ['{"order_intent_json":{"symbol":"EUR_USD"}}'],
        )
        assert store.count_daily_opens(trading_day=NOW.date().isoformat()) == (
            1,
            {"EUR_USD": 1},
        )
    finally:
        store.close()


def test_actual_midnight_cycle_blocks_another_entry_in_same_symbol(
    tmp_path: Path,
) -> None:
    store = AiTradingStore(tmp_path / "history.duckdb")
    engine, _ = committee(RawManager("open_long"))
    backend = FakeExecutionBackend()
    try:
        store._conn.execute("SET TimeZone = 'America/Los_Angeles'")
        cycle = DailyTradingCycle(
            committee=engine,
            risk_gate=RiskGate(
                RiskLimitConfig(symbol_allowlist=frozenset({"EUR_USD"})),
                clock=lambda: NOW,
            ),
            execution_backend=backend,
            store=store,
            snapshot_loader=lambda _: snapshot(),
            quantity_override=Decimal(2),
            enabled=True,
            trading_mode="on",
            clock=lambda: NOW,
        )
        result = cycle.run(["EUR_USD"])
        assert backend.submission_count == 1
        total, symbols = store.count_daily_opens(trading_day=NOW.date().isoformat())
        assert (total, symbols) == (1, {"EUR_USD": 1})
        context = AccountExposureContext(
            current_total_exposure=Decimal(0),
            cash=Decimal(100000),
            captured_at=NOW,
            account_id="test-account",
            open_position_count=0,
            daily_open_count=total,
            daily_symbol_open_count=symbols["EUR_USD"],
            quote_captured_at=NOW,
            quote_tradeable=True,
        )
        from alphabrief_core import OrderIntent

        gate = RiskGate(
            RiskLimitConfig(
                symbol_allowlist=frozenset({"EUR_USD"}),
                entry_rules=EntryRulePolicy(
                    max_daily_opens=5, max_daily_symbol_opens=1
                ),
            ),
            clock=lambda: NOW,
        )
        verdict = gate.evaluate(
            OrderIntent.model_validate(result.attempts[0].order_intent_json),
            estimated_price=Decimal("1.1"),
            estimated_quantity=Decimal(2),
            data_quality_passed=True,
            account_context=context,
        )
        assert not verdict.approved
        assert "DAILY_INTENT_CAP" in verdict.risk_tags
    finally:
        store.close()


def test_production_context_unknown_history_blocks_entry_but_allows_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alphabrief_cli import cycle_commands
    from alphabrief_core import OrderIntent

    monkeypatch.setattr(
        cycle_commands,
        "_drawdown_verdict",
        lambda _: SimpleNamespace(blocked=False, reason=None),
    )
    monkeypatch.setattr(cycle_commands, "_spread_facts", lambda *_: (None, ()))
    monkeypatch.setattr(cycle_commands, "_instrument_types", lambda _: {})

    def source_context(**kwargs: Any) -> AccountExposureContext:
        return AccountExposureContext(
            current_total_exposure=Decimal(0),
            cash=Decimal(100000),
            captured_at=NOW,
            account_id="test-account",
            open_position_count=0,
            daily_open_count=kwargs["daily_open_count"],
            daily_symbol_open_count=kwargs["daily_symbol_open_count"],
            quote_captured_at=NOW,
            quote_tradeable=True,
        )

    store = AiTradingStore(tmp_path / "history.duckdb")
    try:
        save_attempt(store, "corrupt", NOW)
        store._conn.execute("UPDATE ai_order_attempts SET attempt_json = '{}'::JSON")
        provider = cycle_commands._account_context_provider(
            SimpleNamespace(account_exposure_context=source_context),
            trading_day=NOW.date().isoformat(),
            store=store,
        )
        context = provider("EUR_USD")
        assert context.daily_open_count is None
        assert context.daily_symbol_open_count is None
        gate = RiskGate(
            RiskLimitConfig(
                symbol_allowlist=frozenset({"EUR_USD"}),
                entry_rules=EntryRulePolicy(
                    max_daily_opens=5, max_daily_symbol_opens=1
                ),
            ),
            clock=lambda: NOW,
        )
        for closing in (False, True):
            intent = OrderIntent(
                intent_id=f"history-test-{closing}",
                source="model",
                symbol="EUR_USD",
                side="sell",
                order_type="market",
                quantity=Decimal(2),
                rationale="history refusal test",
                created_at=NOW,
                reduce_only=closing,
                stop_loss=Decimal("1.2"),
                take_profit=Decimal("1.0"),
            )
            verdict = gate.evaluate(
                intent,
                estimated_price=Decimal("1.1"),
                estimated_quantity=Decimal(2),
                account_context=context,
                data_quality_passed=True,
            )
            assert verdict.approved is closing
            assert ("DAILY_INTENT_CAP" in verdict.risk_tags) is (not closing)
    finally:
        store.close()
