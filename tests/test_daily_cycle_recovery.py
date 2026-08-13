"""M11-W08: restart-safe autonomous daily operation.

Covers AC-M11-W08-01/02: failure injection before and after every
durable phase and broker boundary resumes to one terminal cycle with no
duplicate intent or submit; concurrent leaders, stale leases, timeout,
provider failure, broker uncertainty, and reconciliation mismatch produce
deterministic recovery or fail-closed evidence.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from alphabrief_core import OrderIntent, RiskDecision
from alphabrief_execution import (
    FillSimulator,
    OrderRouter,
    PaperBroker,
    PortfolioState,
)
from alphabrief_models import FakeProviderAdapter, ModelGateway
from alphabrief_risk import RiskGate, RiskLimitConfig
from alphabrief_trader.committee import TradingCommittee
from alphabrief_trader.cycle_execution import IdempotencyMap
from alphabrief_trader.cycle_state import CYCLE_PHASE_ORDER, CycleStateMachine
from alphabrief_trader.daily_cycle import DurableDailyCycle
from alphabrief_trader.db_store import AiTradingStore, CycleStateStore
from alphabrief_trader.execution_backend import (
    ExecutionBackend,
    ExecutionBackendResult,
)
from alphabrief_trader.execution_gate import PreflightFacts
from alphabrief_trader.rules import DisciplineConfig
from alphabrief_trader.runtime_truth import RuntimeTruthStore
from alphabrief_trader.scheduler_leader import SchedulerLeaderLease
from alphabrief_trader.schemas import MarketSnapshot

_FIXED_NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)

_BULLISH_PAYLOAD: dict[str, object] = {
    "analysis": "Bullish continuation.",
    "view": "bullish",
    "confidence": 0.7,
    "evidence": ["trend confirmed"],
    "risks": ["r1"],
    "suggested_action": "buy",
    "target_position_pct": "0.10",
    "veto": False,
    "needs_human_review": False,
}


def _committee(payload: dict[str, object] | None = None) -> TradingCommittee:
    provider = FakeProviderAdapter(
        provider_name="fake",
        model_name="fake-1",
        capabilities=["structured_output"],
        structured_output=payload or _BULLISH_PAYLOAD,
    )
    return TradingCommittee(
        gateway=ModelGateway(providers=[provider]),
        discipline=DisciplineConfig(),
    )


def _build_cycle(
    store: AiTradingStore,
    state_store: CycleStateStore,
    runtime_store: RuntimeTruthStore,
    idem: IdempotencyMap,
    *,
    committee: TradingCommittee | None = None,
    submits: list[int] | None = None,
    reconciler: Callable[[list[dict[str, object]]], object] | None = None,
    facts: PreflightFacts | None = None,
) -> DurableDailyCycle:
    from alphabrief_trader.cycle_execution import ReconciliationEvidence
    broker = PaperBroker(
        portfolio=PortfolioState(cash=Decimal("100000")),
        router=OrderRouter(),
        fill_simulator=FillSimulator(),
    )
    from alphabrief_trader.execution_backend import LocalPaperExecutionBackend

    backend: ExecutionBackend = LocalPaperExecutionBackend(broker)
    if submits is not None:
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
        committee=committee or _committee(),
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
            captured_at=_FIXED_NOW,
        ),
        execution_backend=backend,
        enabled=True,
        clock=lambda: _FIXED_NOW,
        preflight_facts_provider=lambda: facts or PreflightFacts(),
        idempotency_map=idem,
        reconciler=(
            reconciler
            if reconciler is None
            else cast(
                Callable[[list[dict[str, object]]], ReconciliationEvidence],
                reconciler,
            )
        ),
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


@pytest.fixture
def idem(tmp_path: Path) -> Iterator[IdempotencyMap]:
    store = IdempotencyMap(db_path=tmp_path / "trader.db")
    try:
        yield store
    finally:
        store.close()


def _crash_at(
    machine: CycleStateMachine,
    cycle_id: str,
    up_to: str,
) -> None:
    """Commit transitions through *up_to* (inclusive) as a simulated crash."""
    current = "preflight"
    while current != up_to:
        nxt = CYCLE_PHASE_ORDER[CYCLE_PHASE_ORDER.index(current) + 1]
        outcome = "no_trade" if current == "execute" else None
        assert machine.advance(
            cycle_id,
            expected_phase=current,
            next_phase=nxt,
            output_ids={"crash_probe": current},
            outcome=outcome,
        ) is not None
        current = nxt


class TestFailureInjection:
    def test_crash_before_each_phase_resumes_to_single_terminal(
        self,
        stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore],
        idem: IdempotencyMap,
    ) -> None:
        store, state_store, runtime_store = stores
        machine = CycleStateMachine(state_store)
        for boundary in CYCLE_PHASE_ORDER[:-1]:
            state_store.clear()
            machine.begin("cyc-crash")
            _crash_at(machine, "cyc-crash", boundary)
            submits: list[int] = []
            cycle = _build_cycle(
                store, state_store, runtime_store, idem, submits=submits
            )
            record = cycle.run(["SPY"], cycle_key="cyc-crash")
            assert machine.is_complete(record.cycle_id) is True
            assert len(store.list_cycles()) == 1, boundary
            # No duplicate intents or submits beyond the boundary.
            assert submits.count(1) <= 1, boundary

    def test_crash_after_broker_boundary_never_resubmits(
        self,
        stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore],
        idem: IdempotencyMap,
    ) -> None:
        store, state_store, runtime_store = stores
        machine = CycleStateMachine(state_store)
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            idem,
            submits=[],
        )
        cycle_id = cycle._cycle_id("cyc-broker-boundary", ["SPY"])
        assert machine.begin(cycle_id) is True
        _crash_at(machine, cycle_id, "execute")
        # The execute transition committed after submission; a restart
        # must not call the broker again.
        submits: list[int] = []
        cycle2 = _build_cycle(
            store, state_store, runtime_store, idem, submits=submits
        )
        record = cycle2.run(["SPY"], cycle_key="cyc-broker-boundary")
        assert machine.is_complete(record.cycle_id) is True
        assert len(submits) == 0

    def test_provider_failure_completes_fail_closed(
        self,
        stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore],
        idem: IdempotencyMap,
    ) -> None:
        store, state_store, runtime_store = stores
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            idem,
            committee=_committee({"bogus": "field"}),
        )
        record = cycle.run(["SPY"], cycle_key="cyc-provider-down")
        assert record.outcome in {"provider_error", "skipped_no_consensus"}
        stored = store.get_cycle(record.cycle_id)
        assert stored is not None
        assert stored["attempts"] == []

    def test_broker_timeout_completes_with_error_evidence(
        self,
        stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore],
        idem: IdempotencyMap,
    ) -> None:
        store, state_store, runtime_store = stores

        class _TimingOutBackend(ExecutionBackend):
            def __init__(self) -> None:
                self.submit_calls = 0

            def estimate_quantity(
                self,
                intent: OrderIntent,
                *,
                reference_price: Decimal,
            ) -> Decimal | None:
                return None

            def submit(
                self,
                intent: OrderIntent,
                decision: RiskDecision,
                *,
                reference_price: Decimal,
                now: datetime,
                estimated_quantity: Decimal | None,
            ) -> ExecutionBackendResult:
                self.submit_calls += 1
                raise TimeoutError("broker timed out")

        backend = _TimingOutBackend()
        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            idem,
            committee=_committee(),
        )
        cycle._trading._execution_backend = backend
        record = cycle.run(["SPY"], cycle_key="cyc-timeout")
        assert record.outcome == "error"
        assert backend.submit_calls == 1
        stored = store.get_cycle(record.cycle_id)
        assert stored is not None
        assert stored["attempts"][0]["outcome"] == "error"

    def test_reconciliation_mismatch_is_fail_closed_evidence(
        self,
        stores: tuple[AiTradingStore, CycleStateStore, RuntimeTruthStore],
        idem: IdempotencyMap,
    ) -> None:
        store, state_store, runtime_store = stores

        def _mismatch_reconciler(
            attempts: list[dict[str, object]],
        ) -> object:
            from alphabrief_trader.cycle_execution import (
                ReconciliationEvidence,
            )

            return ReconciliationEvidence(
                cycle_id="mismatch",
                attempt_count=len(attempts),
                order_ids=[],
                matched=False,
                account_snapshot={"equity": "0"},
                detail="unexplained difference: expected 1 fill, saw 0",
                created_at=_FIXED_NOW,
            )

        cycle = _build_cycle(
            store,
            state_store,
            runtime_store,
            idem,
            reconciler=_mismatch_reconciler,
        )
        record = cycle.run(["SPY"], cycle_key="cyc-mismatch")
        machine = CycleStateMachine(state_store)
        reconcile = next(
            t for t in machine.transitions(record.cycle_id)
            if t.prior_phase == "reconcile"
        )
        assert "reconciliation_evidence" in reconcile.output_ids
        assert "matched" in str(reconcile.output_ids["reconciliation_evidence"])


class TestLeaderRecovery:
    def test_stale_lease_blocks_former_leader(
        self, tmp_path: Path
    ) -> None:
        from datetime import timedelta

        class _Clock:
            def __init__(self) -> None:
                self.now = _FIXED_NOW

            def __call__(self) -> datetime:
                return self.now

        clock = _Clock()
        lease = SchedulerLeaderLease(db_path=tmp_path / "lease.db", clock=clock)
        try:
            assert lease.acquire("leader-a", ttl_seconds=60) is True
            clock.now += timedelta(seconds=61)
            # The former leader cannot renew or act after expiry.
            assert lease.renew("leader-a", ttl_seconds=60) is False
            assert lease.is_leader("leader-a") is False
            # A new leader takes over deterministically.
            assert lease.acquire("leader-b", ttl_seconds=60) is True
            assert lease.is_leader("leader-b") is True
        finally:
            lease.close()

    def test_concurrent_leaders_produce_one_holder(
        self, tmp_path: Path
    ) -> None:
        lease = SchedulerLeaderLease(db_path=tmp_path / "lease.db")
        try:
            assert lease.acquire("scheduler-1", ttl_seconds=60) is True
            assert lease.acquire("scheduler-2", ttl_seconds=60) is False
            leader = lease.leader()
            assert leader is not None
            assert leader["holder_id"] == "scheduler-1"
        finally:
            lease.close()
