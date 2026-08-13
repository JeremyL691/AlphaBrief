"""M11-W05: catch-up windows and expiry for missed cycles.

Covers AC-M11-W05-02: a missed cycle runs only inside its configured
catch-up window and records expired-without-chase after the window
closes, without chasing obsolete trades.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alphabrief_execution import (
    FillSimulator,
    OrderRouter,
    PaperBroker,
    PortfolioState,
)
from alphabrief_models import FakeProviderAdapter, ModelGateway
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_trader.committee import TradingCommittee
from alphabrief_trader.cycle_schedule import CatchUpPolicy, daily_cycle_key
from alphabrief_trader.daily_cycle import DurableDailyCycle
from alphabrief_trader.db_store import AiTradingStore, CycleStateStore
from alphabrief_trader.execution_gate import PreflightFacts
from alphabrief_trader.rules import DisciplineConfig
from alphabrief_trader.runtime_truth import RuntimeTruthStore
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

_SCHEDULED = datetime(2026, 8, 13, 8, 0, tzinfo=UTC)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _committee() -> TradingCommittee:
    provider = FakeProviderAdapter(
        provider_name="fake",
        model_name="fake-1",
        capabilities=["structured_output"],
        structured_output=_BULLISH_PAYLOAD,
    )
    return TradingCommittee(
        gateway=ModelGateway(providers=[provider]),
        discipline=DisciplineConfig(),
    )


def _build_cycle(
    store: AiTradingStore,
    state_store: CycleStateStore,
    runtime_store: RuntimeTruthStore,
    clock: _Clock,
    *,
    window_hours: int = 24,
    submits: list[int] | None = None,
) -> DurableDailyCycle:
    broker = PaperBroker(
        portfolio=PortfolioState(cash=Decimal("100000")),
        router=OrderRouter(),
        fill_simulator=FillSimulator(),
    )
    from alphabrief_trader.execution_backend import LocalPaperExecutionBackend

    backend = LocalPaperExecutionBackend(broker)
    if submits is not None:
        from alphabrief_core import OrderIntent, RiskDecision
        from alphabrief_trader.execution_backend import ExecutionBackendResult

        counter = submits

        class _CountingBackend(LocalPaperExecutionBackend):
            def submit(
                self,
                intent: OrderIntent,
                decision: RiskDecision,
                *,
                reference_price: Decimal,
                now: datetime,
                estimated_quantity: Decimal | None,
            ) -> ExecutionBackendResult:
                counter.append(1)
                return super().submit(
                    intent,
                    decision,
                    reference_price=reference_price,
                    now=now,
                    estimated_quantity=estimated_quantity,
                )

        backend = _CountingBackend(broker)
    return DurableDailyCycle(
        committee=_committee(),
        risk_gate=RiskGate(
            limits=RiskLimitConfig(
                trading_enabled=True, symbol_allowlist=frozenset({"SPY"})
            )
        ),
        broker=broker,
        store=store,
        state_store=state_store,
        runtime_store=runtime_store,
        snapshot_loader=lambda s: MarketSnapshot(
            symbol=s,
            reference_price=Decimal("100"),
            data_version="v1",
            captured_at=_SCHEDULED,
        ),
        execution_backend=backend,
        enabled=True,
        clock=clock,
        preflight_facts_provider=lambda: PreflightFacts(),
        catchup_window_hours=window_hours,
    )


@pytest.fixture
def stores(tmp_path: Path) -> Iterator[
    tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore]
]:
    store = AiTradingStore(db_path=tmp_path / "trader.db")
    state_store = CycleStateStore(db_path=tmp_path / "trader.db")
    runtime_store = RuntimeTruthStore(db_path=tmp_path / "trader.db")
    try:
        yield store, state_store, runtime_store
    finally:
        store.close()
        state_store.close()
        runtime_store.close()


class TestCatchUpPolicy:
    def test_on_time_cycle_is_allowed(self) -> None:
        policy = CatchUpPolicy(window_hours=24, clock=_Clock(_SCHEDULED))
        verdict = policy.evaluate(_SCHEDULED)
        assert verdict.allowed is True
        assert verdict.reason == "on_time"

    def test_within_window_is_allowed(self) -> None:
        policy = CatchUpPolicy(
            window_hours=24, clock=_Clock(_SCHEDULED + timedelta(hours=12))
        )
        verdict = policy.evaluate(_SCHEDULED)
        assert verdict.allowed is True
        assert verdict.reason == "within_catchup_window"

    def test_after_window_is_expired(self) -> None:
        policy = CatchUpPolicy(
            window_hours=24, clock=_Clock(_SCHEDULED + timedelta(hours=25))
        )
        verdict = policy.evaluate(_SCHEDULED)
        assert verdict.allowed is False
        assert verdict.reason == "expired_without_chase"

    def test_daily_cycle_key_is_deterministic(self) -> None:
        key_a = daily_cycle_key("2026-08-13", "snap-abc")
        key_b = daily_cycle_key("2026-08-13", "snap-abc")
        key_c = daily_cycle_key("2026-08-13", "snap-xyz")
        assert key_a == key_b
        assert key_a != key_c
        assert key_a.startswith("daily_")


class TestExpiredCycle:
    def test_expired_cycle_records_without_chasing(
        self, stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore]
    ) -> None:
        store, state_store, runtime_store = stores
        clock = _Clock(_SCHEDULED + timedelta(hours=25))
        submits: list[int] = []
        cycle = _build_cycle(
            store, state_store, runtime_store, clock, submits=submits
        )
        record = cycle.run(
            ["SPY"], cycle_key="cyc-expired", scheduled_at=_SCHEDULED
        )

        assert record.outcome == "expired_without_chase"
        assert record.votes == []
        assert record.plans == []
        assert record.attempts == []
        assert submits == []
        stored = store.get_cycle(record.cycle_id)
        assert stored is not None
        assert stored["outcome"] == "expired_without_chase"

    def test_missed_within_window_still_runs(
        self, stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore]
    ) -> None:
        store, state_store, runtime_store = stores
        clock = _Clock(_SCHEDULED + timedelta(hours=12))
        submits: list[int] = []
        cycle = _build_cycle(
            store, state_store, runtime_store, clock, submits=submits
        )
        record = cycle.run(
            ["SPY"], cycle_key="cyc-catchup", scheduled_at=_SCHEDULED
        )
        assert record.outcome != "expired_without_chase"
        assert record.votes  # research ran within the window

    def test_expired_is_idempotent(
        self, stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore]
    ) -> None:
        store, state_store, runtime_store = stores
        clock = _Clock(_SCHEDULED + timedelta(hours=30))
        cycle = _build_cycle(store, state_store, runtime_store, clock)
        first = cycle.run(
            ["SPY"], cycle_key="cyc-expired-2", scheduled_at=_SCHEDULED
        )
        second = cycle.run(
            ["SPY"], cycle_key="cyc-expired-2", scheduled_at=_SCHEDULED
        )
        assert first.cycle_id == second.cycle_id
        assert len(store.list_cycles()) == 1
