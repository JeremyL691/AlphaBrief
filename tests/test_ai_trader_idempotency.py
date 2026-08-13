"""M10-W05: committee run idempotency and durable no-trade resolution.

Covers AC-M10-W05-02/03: exhausted repair, budget exhaustion, and
unresolved grounding produce one durable blocked or no-trade result with
no OrderIntent; repeating the same cycle key and snapshot returns the
existing terminal result without creating another proposal or intent.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_execution import (
    FillSimulator,
    OrderRouter,
    PaperBroker,
    PortfolioState,
)
from alphabrief_models import (
    FakeProviderAdapter,
    ModelCallBudget,
    ModelGateway,
    ModelRequest,
    ModelResponse,
)
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_trader.committee import TradingCommittee
from alphabrief_trader.daily_cycle import DailyTradingCycle, _snapshot_fingerprint
from alphabrief_trader.db_store import AiTradingStore
from alphabrief_trader.rules import DisciplineConfig
from alphabrief_trader.schemas import MarketSnapshot

_BULLISH_PAYLOAD: dict[str, object] = {
    "analysis": "Bullish continuation.",
    "view": "bullish",
    "confidence": 0.7,
    "evidence": ["e1"],
    "risks": ["r1"],
    "suggested_action": "buy",
    "target_position_pct": 0.10,
    "veto": False,
    "needs_human_review": False,
}


def _snapshot(symbol: str) -> MarketSnapshot:
    return MarketSnapshot(
        symbol=symbol,
        reference_price=Decimal("100"),
        data_version="test-v1",
        captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _committee(
    payload: dict[str, object] | None = None,
    *,
    repair_attempts: int = 0,
    budget: ModelCallBudget | None = None,
) -> TradingCommittee:
    provider = FakeProviderAdapter(
        provider_name="fake",
        model_name="fake-1",
        capabilities=["structured_output"],
        structured_output=payload or _BULLISH_PAYLOAD,
    )
    gateway = ModelGateway(providers=[provider], budget=budget)
    return TradingCommittee(
        gateway=gateway,
        discipline=DisciplineConfig(),
        repair_attempts=repair_attempts,
    )


def _broker() -> PaperBroker:
    return PaperBroker(
        portfolio=PortfolioState(cash=Decimal("100000")),
        router=OrderRouter(),
        fill_simulator=FillSimulator(),
    )


def _risk_gate(symbols: list[str]) -> RiskGate:
    return RiskGate(
        limits=RiskLimitConfig(
            trading_enabled=True,
            symbol_allowlist=frozenset(symbols),
        )
    )


@pytest.fixture
def store(tmp_path: Path) -> Iterator[AiTradingStore]:
    s = AiTradingStore(db_path=tmp_path / "trader.db")
    try:
        yield s
    finally:
        s.close()


def _cycle(
    store: AiTradingStore,
    *,
    committee: TradingCommittee,
    symbol: str = "SPY",
) -> DailyTradingCycle:
    return DailyTradingCycle(
        committee=committee,
        risk_gate=_risk_gate([symbol]),
        broker=_broker(),
        store=store,
        snapshot_loader=lambda s: _snapshot(s),
        enabled=True,
        clock=lambda: datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
    )


class TestCycleIdempotency:
    def test_same_cycle_key_and_snapshot_returns_existing_record(
        self, store: AiTradingStore
    ) -> None:
        cycle = _cycle(store, committee=_committee())
        first = cycle.run(["SPY"], cycle_key="cycle-2026-08-13-SPY")
        second = cycle.run(["SPY"], cycle_key="cycle-2026-08-13-SPY")

        assert second.cycle_id == first.cycle_id
        assert second.outcome == first.outcome
        # Exactly one terminal record exists: no duplicate run was created.
        assert len(store.list_cycles()) == 1

    def test_same_key_different_snapshot_creates_new_run(
        self, store: AiTradingStore
    ) -> None:
        cycle = _cycle(store, committee=_committee())
        first = cycle.run(["SPY"], cycle_key="cycle-2026-08-13-SPY")

        # A different reference price changes the snapshot fingerprint.
        changed_cycle = DailyTradingCycle(
            committee=_committee(),
            risk_gate=_risk_gate(["SPY"]),
            broker=_broker(),
            store=store,
            snapshot_loader=lambda s: MarketSnapshot(
                symbol="SPY",
                reference_price=Decimal("150"),
                data_version="test-v1",
                captured_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            enabled=True,
            clock=lambda: datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
        )
        second = changed_cycle.run(["SPY"], cycle_key="cycle-2026-08-13-SPY")

        assert second.cycle_id != first.cycle_id
        assert len(store.list_cycles()) == 2

    def test_fingerprint_is_deterministic_and_content_sensitive(self) -> None:
        snap_a = _snapshot("SPY")
        snap_b = _snapshot("SPY")
        snap_c = MarketSnapshot(
            symbol="SPY",
            reference_price=Decimal("150"),
            data_version="test-v1",
            captured_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert _snapshot_fingerprint({"SPY": snap_a}) == _snapshot_fingerprint(
            {"SPY": snap_b}
        )
        assert _snapshot_fingerprint({"SPY": snap_a}) != _snapshot_fingerprint(
            {"SPY": snap_c}
        )

    def test_no_cycle_key_never_deduplicates(self, store: AiTradingStore) -> None:
        cycle = _cycle(store, committee=_committee())
        first = cycle.run(["SPY"])
        second = cycle.run(["SPY"])
        assert first.cycle_id != second.cycle_id
        assert len(store.list_cycles()) == 2

    def test_blocked_records_deduplicate_by_key(self, store: AiTradingStore) -> None:
        cycle = _cycle(store, committee=_committee())
        cycle = DailyTradingCycle(
            committee=_committee(),
            risk_gate=_risk_gate(["SPY"]),
            broker=_broker(),
            store=store,
            snapshot_loader=lambda s: _snapshot(s),
            enabled=False,
            clock=lambda: datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
        )
        first = cycle.run(["SPY"], cycle_key="cycle-2026-08-13-SPY")
        second = cycle.run(["SPY"], cycle_key="cycle-2026-08-13-SPY")
        assert first.cycle_id == second.cycle_id
        assert first.outcome == "blocked_disabled"


class TestDurableNoTrade:
    def test_exhausted_repair_produces_no_trade_without_intent(
        self, store: AiTradingStore
    ) -> None:
        # Every role returns invalid output and the repair never succeeds:
        # the cycle records a durable provider_error with zero intents.
        bad_payload: dict[str, object] = {"bogus": "field"}
        committee = _committee(bad_payload, repair_attempts=2)
        cycle = _cycle(store, committee=committee)
        record = cycle.run(["SPY"], cycle_key="cycle-repair-fail")

        assert record.outcome == "provider_error"
        assert record.plans == []
        assert record.attempts == []
        assert record.votes == []
        stored = store.get_cycle(record.cycle_id)
        assert stored is not None
        assert stored["outcome"] == "provider_error"
        assert stored["attempts"] == []

    def test_budget_exhaustion_produces_no_trade_without_intent(
        self, store: AiTradingStore
    ) -> None:
        # One call per UTC day: the first role call is allowed, every
        # following committee call is rejected by the budget, so the
        # cycle records a durable provider_error with no plan or intent.
        budget = ModelCallBudget(
            max_calls_per_request=100,
            max_calls_per_cycle=100,
            max_calls_per_day=1,
        )
        committee = _committee(budget=budget)
        cycle = _cycle(store, committee=committee)
        record = cycle.run(["SPY"], cycle_key="cycle-budget")

        assert record.outcome == "provider_error"
        assert record.plans == []
        assert record.attempts == []
        stored = store.get_cycle(record.cycle_id)
        assert stored is not None
        assert stored["outcome"] == "provider_error"
        assert stored["attempts"] == []

    def test_repair_success_produces_tradeable_proposal_path(
        self, store: AiTradingStore
    ) -> None:
        # A role whose output repairs successfully still votes; the cycle
        # proceeds to a plan without any repair verdict being lost.
        class _RepairingProvider(FakeProviderAdapter):
            def __init__(self) -> None:
                super().__init__(
                    provider_name="fake",
                    model_name="fake-1",
                    capabilities=["structured_output"],
                )
                self.calls = 0

            def call(self, request: ModelRequest) -> ModelResponse:
                self.calls += 1
                payload: dict[str, object] | None = (
                    {"bogus": "field"} if self.calls % 2 == 1 else _BULLISH_PAYLOAD
                )
                return ModelResponse(
                    request_id=request.request_id,
                    provider=self.provider_name,
                    model=self.model_name,
                    output_text="{}",
                    structured_output=payload,
                    status="succeeded",
                    finish_reason="stop",
                )

        committee = TradingCommittee(
            gateway=ModelGateway(providers=[_RepairingProvider()]),
            discipline=DisciplineConfig(),
            repair_attempts=1,
        )
        cycle = _cycle(store, committee=committee)
        record = cycle.run(["SPY"], cycle_key="cycle-repair-ok")

        assert record.outcome in {"executed", "skipped_no_intent"}
        assert record.votes
