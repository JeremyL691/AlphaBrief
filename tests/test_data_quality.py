"""Tests for the real data-quality evaluation (S4-1).

PROJECT_GUIDE 5.7 rule 5 requires the risk gate to receive the *real*
result of the input-quality check. These tests pin the fail-closed
contract: stale, malformed, or future-dated inputs are rejected, and the
trading cycle passes that verdict through instead of hardcoding it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alphabrief_core import OrderIntent, RiskDecision
from alphabrief_models import FakeProviderAdapter, ModelCallRecord, ModelGateway
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_trader import (
    DailyTradingCycle,
    DisciplineConfig,
    MarketSnapshot,
    TradingCommittee,
)
from alphabrief_trader.data_quality import (
    DEFAULT_MAX_AGE_SECONDS,
    DataQualityVerdict,
    evaluate_snapshot_quality,
    evaluate_snapshots,
)
from alphabrief_trader.db_store import AiTradingStore
from alphabrief_trader.execution_backend import ExecutionBackendResult
from alphabrief_trader.schemas import CommitteeInput

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)

_BULLISH = {
    "analysis": "Bullish continuation.",
    "view": "bullish",
    "confidence": 0.8,
    "evidence": ["trend"],
    "risks": [],
    "suggested_action": "buy",
    "target_position_pct": "0.10",
    "veto": False,
    "needs_human_review": False,
}


def _snapshot(*, captured_at: datetime = NOW, price: str = "1.1000") -> MarketSnapshot:
    return MarketSnapshot(
        symbol="EUR_USD",
        reference_price=Decimal(price),
        data_version="test",
        captured_at=captured_at,
    )


class TestVerdicts:
    def test_fresh_snapshot_passes(self) -> None:
        verdict = evaluate_snapshot_quality(_snapshot(), now=NOW)

        assert verdict.passed is True
        assert verdict.reasons == ()

    def test_stale_snapshot_fails_with_the_age(self) -> None:
        stale = _snapshot(captured_at=NOW - timedelta(seconds=7201))

        verdict = evaluate_snapshot_quality(stale, now=NOW)

        assert verdict.passed is False
        assert verdict.reasons == ("snapshot_stale_7201s",)

    def test_snapshot_at_the_limit_still_passes(self) -> None:
        at_limit = _snapshot(
            captured_at=NOW - timedelta(seconds=DEFAULT_MAX_AGE_SECONDS)
        )

        assert evaluate_snapshot_quality(at_limit, now=NOW).passed is True

    def test_future_capture_time_fails(self) -> None:
        future = _snapshot(captured_at=NOW + timedelta(minutes=5))

        verdict = evaluate_snapshot_quality(future, now=NOW)

        assert verdict.passed is False
        assert "captured_at_in_the_future" in verdict.reasons

    def test_verdict_is_json_safe(self) -> None:
        verdict = evaluate_snapshot_quality(
            _snapshot(captured_at=NOW - timedelta(hours=5)), now=NOW
        )

        assert isinstance(verdict, DataQualityVerdict)
        payload = verdict.to_dict()
        assert payload["passed"] is False
        assert isinstance(payload["reasons"], list)


class _RecordingBackend:
    def __init__(self) -> None:
        self.submissions = 0

    def estimate_quantity(
        self, intent: OrderIntent, *, reference_price: Decimal
    ) -> Decimal | None:
        quantity = getattr(intent, "quantity", None)
        return quantity if isinstance(quantity, Decimal) else None

    def submit(
        self,
        intent: OrderIntent,
        decision: RiskDecision,
        *,
        reference_price: Decimal,
        now: datetime,
        estimated_quantity: Decimal | None,
    ) -> ExecutionBackendResult:
        self.submissions += 1
        return ExecutionBackendResult(
            execution_backend="external_paper",
            order_id="fake-1",
            broker_order_id="fake-1",
            filled=True,
            fill_price=reference_price,
            fill_quantity=Decimal("1"),
            fill_json=None,
        )


def _cycle(
    store: AiTradingStore,
    backend: _RecordingBackend,
    *,
    snapshot: MarketSnapshot | None,
    clock: datetime = NOW,
    calls: list[ModelCallRecord] | None = None,
    snapshots: dict[str, MarketSnapshot] | None = None,
    refresher: Callable[[MarketSnapshot], MarketSnapshot] | None = None,
) -> DailyTradingCycle:
    provider = FakeProviderAdapter(
        provider_name="fake",
        model_name="fake-1",
        capabilities=["structured_output"],
        structured_output=_BULLISH,
    )
    return DailyTradingCycle(
        committee=TradingCommittee(
            gateway=ModelGateway(
                providers=[provider],
                record_sink=None if calls is None else calls.append,
            ),
            discipline=DisciplineConfig(),
        ),
        risk_gate=RiskGate(
            limits=RiskLimitConfig(
                trading_enabled=True,
                symbol_allowlist=frozenset(
                    {"EUR_USD"} if snapshots is None else snapshots
                ),
            )
        ),
        execution_backend=backend,
        store=store,
        snapshot_loader=lambda symbol: (
            snapshot if snapshots is None else snapshots.get(symbol)
        ),
        enabled=True,
        clock=lambda: clock,
        trading_mode="on",
        snapshot_refresher=refresher,
    )


@pytest.fixture
def store(tmp_path: Path) -> Iterator[AiTradingStore]:
    trading_store = AiTradingStore(db_path=tmp_path / "trader.duckdb")
    try:
        yield trading_store
    finally:
        trading_store.close()


class TestCycleUsesTheRealVerdict:
    def test_stale_inputs_are_rejected_before_the_model(
        self, store: AiTradingStore
    ) -> None:
        backend = _RecordingBackend()
        calls: list[ModelCallRecord] = []
        cycle = _cycle(
            store,
            backend,
            snapshot=_snapshot(captured_at=NOW - timedelta(hours=5)),
            calls=calls,
        )

        record = cycle.run(["EUR_USD"])

        assert record.outcome == "skipped_data_stale"
        assert backend.submissions == 0
        assert calls == []
        assert record.plans == []
        assert record.votes == []
        assert record.attempts == []
        quality = record.input_quality[0]
        assert quality.passed is False
        assert quality.no_trade_reason == "NO_TRADE_DATA_STALE"
        assert quality.reasons == ["snapshot_stale_18000s"]
        assert quality.evaluated_at == NOW
        assert quality.snapshot_captured_at == NOW - timedelta(hours=5)
        persisted = store.get_cycle(record.cycle_id)
        assert persisted is not None
        assert persisted["input_quality"] == [quality.model_dump(mode="json")]
        assert "NO_TRADE_DATA_STALE" in persisted["summary"]

    def test_fresh_inputs_execute(self, store: AiTradingStore) -> None:
        backend = _RecordingBackend()

        record = _cycle(store, backend, snapshot=_snapshot()).run(["EUR_USD"])

        assert record.outcome == "executed"
        assert backend.submissions == 1

    def test_input_expiring_during_model_calls_is_rejected_before_submit(
        self, store: AiTradingStore
    ) -> None:
        current = NOW

        def after_call(record: ModelCallRecord) -> None:
            nonlocal current
            current = NOW + timedelta(hours=3)

        provider = FakeProviderAdapter(
            provider_name="fake", model_name="fake-1",
            capabilities=["structured_output"], structured_output=_BULLISH,
        )
        backend = _RecordingBackend()
        cycle = DailyTradingCycle(
            committee=TradingCommittee(
                gateway=ModelGateway(providers=[provider], record_sink=after_call),
                discipline=DisciplineConfig(),
            ),
            risk_gate=RiskGate(limits=RiskLimitConfig(
                trading_enabled=True, symbol_allowlist=frozenset({"EUR_USD"}),
            )),
            execution_backend=backend, store=store,
            snapshot_loader=lambda symbol: _snapshot(),
            enabled=True, trading_mode="on", clock=lambda: current,
        )
        record = cycle.run(["EUR_USD"])
        assert record.input_quality[0].passed
        assert record.input_quality[0].evaluated_at == NOW
        assert record.outcome == "blocked_risk_gate"
        assert backend.submissions == 0
        assert "data quality" in record.attempts[0].reason
        assert record.attempts[0].created_at == NOW + timedelta(hours=3)

    @pytest.mark.parametrize("kind", ["missing", "future", "wrong_symbol"])
    def test_unusable_input_has_no_model_calls_or_intents(
        self, store: AiTradingStore, kind: str
    ) -> None:
        snapshot = {
            "missing": None,
            "future": _snapshot(captured_at=NOW + timedelta(minutes=5)),
            "wrong_symbol": _snapshot().model_copy(update={"symbol": "USD_JPY"}),
        }[kind]
        calls: list[ModelCallRecord] = []
        backend = _RecordingBackend()
        record = _cycle(store, backend, snapshot=snapshot, calls=calls).run(["EUR_USD"])
        assert record.outcome == "skipped_data_stale"
        assert calls == []
        assert backend.submissions == 0
        assert record.plans == []
        assert record.votes == []
        assert record.attempts == []
        assert len(record.input_quality) == 1
        assert record.input_quality[0].reasons == [{
            "missing": "snapshot_missing",
            "future": "captured_at_in_the_future",
            "wrong_symbol": "snapshot_symbol_mismatch",
        }[kind]]

    def test_mixed_universe_preserves_every_verdict_and_only_calls_for_fresh_inputs(
        self, store: AiTradingStore
    ) -> None:
        snapshots = {
            "EUR_USD": _snapshot(),
            "GBP_USD": _snapshot(captured_at=NOW - timedelta(hours=3)).model_copy(
                update={"symbol": "GBP_USD"}
            ),
        }
        calls: list[ModelCallRecord] = []
        backend = _RecordingBackend()
        record = _cycle(
            store, backend, snapshot=None, snapshots=snapshots, calls=calls
        ).run(["GBP_USD", "USD_JPY", "EUR_USD"])
        assert record.outcome == "executed"
        assert backend.submissions == 1
        assert len(calls) == 10  # One default committee, not one per requested symbol.
        assert [plan.symbol for plan in record.plans] == ["EUR_USD"]
        assert [a.order_intent_json["symbol"] for a in record.attempts] == ["EUR_USD"]
        assert [(q.symbol, q.passed) for q in record.input_quality] == [
            ("GBP_USD", False), ("USD_JPY", False), ("EUR_USD", True)
        ]
        assert "GBP_USD:snapshot_stale_10800s" in record.summary
        assert "USD_JPY:snapshot_missing" in record.summary


def test_quality_evaluates_requested_missing_symbols() -> None:
    verdicts = evaluate_snapshots(
        {"EUR_USD": _snapshot()}, symbols=["EUR_USD", "USD_JPY"], now=NOW
    )
    assert verdicts["EUR_USD"].passed
    assert verdicts["USD_JPY"].reasons == ("snapshot_missing",)


@pytest.mark.parametrize("stale_after_model", [False, True])
def test_broker_facts_are_refreshed_after_model_and_persisted_with_attempt(
    store: AiTradingStore, monkeypatch: pytest.MonkeyPatch, stale_after_model: bool,
) -> None:
    from alphabrief_execution.broker.oanda.input_facts import BrokerInputFacts

    clock = [NOW]
    refreshed: list[datetime] = []

    def refresh(snapshot: MarketSnapshot) -> MarketSnapshot:
        refreshed.append(clock[0])
        quote_time = clock[0]
        if stale_after_model and len(refreshed) == 2:
            quote_time -= timedelta(seconds=16)
        return snapshot.model_copy(update={"broker_evidence": BrokerInputFacts(
            symbol=snapshot.symbol, bid=Decimal("1.1"), ask=Decimal("1.1002"),
            spread=Decimal("0.0002"), quote_to_home=Decimal(1),
            quote_position_to_home=Decimal(1),
            quote_captured_at=quote_time, nav=Decimal(1000),
            margin_available=Decimal(950),
            account_captured_at=clock[0], positions_captured_at=clock[0],
            reconciliation_captured_at=clock[0], position_units=Decimal(0),
            position_unrealized_pnl=Decimal(0), daily_open_count=0,
        )})

    backend = _RecordingBackend()
    cycle = _cycle(store, backend, snapshot=_snapshot(), refresher=refresh)
    monkeypatch.setattr(cycle, "_clock", lambda: clock[0])
    original = cycle._committee.run

    def model(payload: CommitteeInput) -> Any:
        result = original(payload)
        clock[0] += timedelta(seconds=30)
        return result

    monkeypatch.setattr(cycle._committee, "run", model)
    record = cycle.run(["EUR_USD"], cycle_key="fresh-broker-round")
    assert refreshed == [NOW, NOW + timedelta(seconds=30)]
    assert record.input_quality[0].passed
    assert record.input_quality[0].broker_evidence is not None
    assert record.input_quality[0].broker_evidence.quote_captured_at == NOW
    assert record.attempts[0].broker_evidence is not None
    expected_quote = NOW + timedelta(seconds=14 if stale_after_model else 30)
    assert record.attempts[0].broker_evidence.quote_captured_at == expected_quote
    assert backend.submissions == (0 if stale_after_model else 1)
    if stale_after_model:
        assert record.attempts[0].outcome == "blocked_risk_gate"
        assert "data_quality" in record.attempts[0].risk_tags
    saved = store.get_latest_cycle()
    assert saved is not None
    assert saved["attempts"][0]["broker_evidence"]["quote_captured_at"] == (
        expected_quote.isoformat().replace("+00:00", "Z")
    )
    # A completed decision key keeps its original inputs despite fresher quotes.
    assert cycle.run(["EUR_USD"], cycle_key="fresh-broker-round") == record
    assert len(refreshed) == 2
